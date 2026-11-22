"""Gmail incremental sync, MIME parsing, and attachment text extraction."""

from __future__ import annotations

import base64
import email.utils
import gc
import json
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.connectors.gmail_auth import (
    delete_credentials,
    get_credentials,
    is_connected,
)
from app.db import (
    delete_all_gmail_data,
    delete_chunks_by_file_id,
    delete_facts_by_file_id,
    delete_gmail_message,
    get_all_gmail_ids,
    get_connection,
    get_gmail_status_db,
    get_setting,
    init_db,
    insert_chunks_batch,
    insert_facts_batch,
    set_setting,
    upsert_gmail_message,
)
from app.ingestion.chunker import chunk_file
from app.ingestion.classifier import classify_file
from app.ingestion.extractors import extract_text_from_bytes
from app.ingestion.facts import extract_facts
from app.search.embedder import get_embedder
from app.search.hybrid import invalidate_vector_cache

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_ATTACHMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv"}


def clean_email_body(content: str, is_html: bool = False) -> str:
    """
    Clean email body text:
    - HTML converted using BeautifulSoup
    - Quoted replies (e.g. On <date>, <author> wrote:; lines with >) trimmed
    - Signatures (standard -- \\n and common mobile footers) trimmed
    - Multiple blank lines normalized
    """
    if not content:
        return ""

    if is_html:
        try:
            soup = BeautifulSoup(content, "html.parser")
            for tag in soup(["script", "style", "head", "meta"]):
                tag.decompose()
            text = soup.get_text(separator="\n")
        except Exception:
            text = content
    else:
        text = content

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 1. Trim quoted reply headers:
    # "On ... wrote:"
    text = re.split(r"\n\s*On\s+.+?wrote:\s*", text, flags=re.IGNORECASE | re.DOTALL)[0]
    # "--- Forwarded message ---" or "--- Original Message ---"
    text = re.split(r"\n\s*-+\s*(?:Original|Forwarded)\s+Message\s*-+", text, flags=re.IGNORECASE)[0]
    # "From: ... Date: ... Subject: ..."
    text = re.split(r"\n\s*From:\s*.+?\n\s*(?:Sent|Date):\s*", text, flags=re.IGNORECASE)[0]

    # 2. Strip lines starting with '>'
    lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        lines.append(line)
    text = "\n".join(lines)

    # 3. Trim signatures:
    # RFC 3676 standard signature delimiter "\n-- \n" or "\n--\n"
    sig_split = re.split(r"\n--\s*\n", text, maxsplit=1)
    if len(sig_split) > 1:
        text = sig_split[0]

    # Common mobile signatures
    mobile_footers = [
        r"\bSent from my (?:iPhone|iPad|Android|Galaxy|mobile device)\b.*",
        r"\bGet Outlook for (?:iOS|Android)\b.*",
    ]
    for footer in mobile_footers:
        text = re.split(footer, text, flags=re.IGNORECASE)[0]

    # 4. Collapse excess whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def parse_message_payload(
    part: dict[str, Any],
    body_plain: list[str],
    body_html: list[str],
    attachments: list[dict[str, Any]],
) -> None:
    """
    Recursively parse MIME message parts:
    - Collects plain text and HTML body parts
    - Identifies eligible attachments (pdf, docx, xlsx, txt up to 10 MB)
    """
    mime_type = part.get("mimeType", "").lower()
    filename = part.get("filename", "").strip()
    body = part.get("body", {})

    attachment_id = body.get("attachmentId")
    if filename and attachment_id:
        size = body.get("size", 0)
        ext = Path(filename).suffix.lower()
        if ext in ALLOWED_ATTACHMENT_EXTENSIONS and size <= MAX_ATTACHMENT_SIZE_BYTES:
            attachments.append({
                "filename": filename,
                "attachment_id": attachment_id,
                "size": size,
                "mime_type": mime_type,
            })
    else:
        data_b64 = body.get("data")
        if data_b64:
            try:
                decoded = base64.urlsafe_b64decode(data_b64.encode("ASCII")).decode("utf-8", errors="replace")
                if mime_type == "text/plain":
                    body_plain.append(decoded)
                elif mime_type == "text/html":
                    body_html.append(decoded)
            except Exception:
                pass

    for child in part.get("parts", []):
        parse_message_payload(child, body_plain, body_html, attachments)


def execute_with_backoff(request: Any, max_retries: int = 5) -> Any:
    """Execute a Google API request with exponential backoff on rate-limit errors."""
    for attempt in range(max_retries):
        try:
            return request.execute()
        except HttpError as exc:
            status = exc.resp.status
            err_str = str(exc).lower()
            is_rate = status in (429, 503) or "ratelimit" in err_str or "quota" in err_str
            if is_rate and attempt < max_retries - 1:
                sleep_time = (2 ** attempt) + random.uniform(0.1, 0.5)
                logger.warning("Rate-limit received from Gmail API (%s). Retrying in %.2fs...", status, sleep_time)
                time.sleep(sleep_time)
                continue
            raise
        except Exception as exc:
            err_str = str(exc).lower()
            is_rate = any(k in err_str for k in ("429", "503", "rate limit", "ratelimit", "quota"))
            if is_rate and attempt < max_retries - 1:
                sleep_time = (2 ** attempt) + random.uniform(0.1, 0.5)
                time.sleep(sleep_time)
                continue
            raise


def sync_gmail(
    db_path: Path | str | None = None,
    service: Any = None,
    max_messages_override: int | None = None,
) -> dict[str, Any]:
    """
    Incremental sync of Gmail messages:
    - Uses users.messages.list and users.messages.get (format='full') in batches of 25
    - Exponential backoff on rate-limit errors
    - First sync: last 12 months, max 2000 messages (configurable via settings)
    - Next syncs: only messages newer than last_sync_time
    - Handles deleted messages (TRASH, SPAM, 404s)
    - Extracts attachments in-memory, appends to text, never writes to disk
    - Frees memory after each message
    """
    conn = get_connection(db_path)
    try:
        init_db(db_path)

        if service is None:
            creds = get_credentials()
            if not creds:
                raise RuntimeError("Gmail is not connected. Please connect first.")
            service = build("gmail", "v1", credentials=creds)

        # 1. Update connected email in settings
        try:
            profile = execute_with_backoff(service.users().getProfile(userId="me"))
            user_email = profile.get("emailAddress", "")
            if user_email:
                set_setting(conn, "gmail_connected_email", user_email)
        except Exception as exc:
            logger.warning("Failed to fetch Gmail profile: %s", exc)
            user_email = get_setting(conn, "gmail_connected_email") or ""

        # 2. Determine sync parameters
        last_sync_str = get_setting(conn, "gmail_last_sync_time")
        first_sync_months = int(get_setting(conn, "gmail_first_sync_months") or "12")
        first_sync_max = int(get_setting(conn, "gmail_first_sync_max_messages") or "2000")

        if max_messages_override is not None:
            max_messages = max_messages_override
        elif last_sync_str:
            max_messages = 2000
        else:
            max_messages = first_sync_max

        base_query = "-in:spam -in:trash -category:promotions"
        if last_sync_str:
            last_epoch = int(float(last_sync_str))
            query = f"{base_query} after:{last_epoch}"
        else:
            cutoff = int(time.time() - (first_sync_months * 30 * 86400))
            query = f"{base_query} after:{cutoff}"

        # 3. Reconcile deleted / trashed messages
        deleted_count = 0
        try:
            trash_resp = execute_with_backoff(
                service.users().messages().list(userId="me", q="in:trash OR in:spam", maxResults=500)
            )
            stored_ids = get_all_gmail_ids(conn)
            for m in trash_resp.get("messages", []):
                mid = m["id"]
                if mid in stored_ids:
                    delete_gmail_message(conn, mid)
                    deleted_count += 1
        except Exception as exc:
            logger.warning("Failed to check trashed messages: %s", exc)

        # 4. Sync messages in batches of 25
        synced_count = 0
        page_token = None
        embedder = None
        try:
            embedder = get_embedder()
        except Exception:
            pass

        while synced_count < max_messages:
            fetch_size = min(25, max_messages - synced_count)
            list_req = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=fetch_size,
                pageToken=page_token,
            )
            list_res = execute_with_backoff(list_req)
            msg_summaries = list_res.get("messages", [])
            if not msg_summaries:
                break

            for summary in msg_summaries:
                msg_id = summary["id"]
                try:
                    msg = execute_with_backoff(
                        service.users().messages().get(userId="me", id=msg_id, format="full")
                    )
                except HttpError as h_exc:
                    if h_exc.resp.status == 404:
                        delete_gmail_message(conn, msg_id)
                        deleted_count += 1
                        continue
                    raise
                except Exception as exc:
                    if "404" in str(exc) or "not found" in str(exc).lower():
                        delete_gmail_message(conn, msg_id)
                        deleted_count += 1
                        continue
                    logger.warning("Error fetching message %s: %s", msg_id, exc)
                    continue

                thread_id = msg.get("threadId", "")
                label_ids = msg.get("labelIds", [])
                labels_str = json.dumps(label_ids)
                payload = msg.get("payload", {})

                # Extract headers
                headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}
                subject = headers.get("subject", "").strip() or "(No Subject)"
                sender = headers.get("from", "").strip()
                recipients = headers.get("to", "").strip()

                # Parse date
                email_date = time.time()
                internal_date = msg.get("internalDate")
                if internal_date:
                    try:
                        email_date = float(internal_date) / 1000.0
                    except Exception:
                        pass
                elif "date" in headers:
                    try:
                        email_date = email.utils.parsedate_to_datetime(headers["date"]).timestamp()
                    except Exception:
                        pass

                # Extract body and attachments
                body_plain: list[str] = []
                body_html: list[str] = []
                attachments_meta: list[dict[str, Any]] = []
                parse_message_payload(payload, body_plain, body_html, attachments_meta)

                if body_plain:
                    cleaned_body = clean_email_body("\n\n".join(body_plain), is_html=False)
                elif body_html:
                    cleaned_body = clean_email_body("\n\n".join(body_html), is_html=True)
                else:
                    cleaned_body = clean_email_body(msg.get("snippet", ""), is_html=False)

                # Process attachments in memory
                attachment_texts: list[str] = []
                for att in attachments_meta:
                    try:
                        att_req = service.users().messages().attachments().get(
                            userId="me",
                            messageId=msg_id,
                            id=att["attachment_id"],
                        )
                        att_res = execute_with_backoff(att_req)
                        att_b64 = att_res.get("data", "")
                        if att_b64:
                            att_bytes = base64.urlsafe_b64decode(att_b64.encode("ASCII"))
                            status, att_text, _ = extract_text_from_bytes(att_bytes, att["filename"])
                            del att_bytes
                            del att_b64
                            if status == "indexed" and att_text.strip():
                                attachment_texts.append(
                                    f"\n\n--- Attachment: {att['filename']} ---\n{att_text.strip()}"
                                )
                    except Exception as att_exc:
                        logger.warning("Failed to extract attachment %s: %s", att.get("filename"), att_exc)

                full_text = cleaned_body + "".join(attachment_texts)
                has_attachments = 1 if attachments_meta else 0

                # Classification
                fake_path = "/".join(["Gmail"] + label_ids + [subject])
                doc_type, doc_type_score = classify_file(
                    path=fake_path,
                    filename=subject,
                    text=full_text,
                )

                # Upsert into database
                file_id = upsert_gmail_message(
                    conn=conn,
                    gmail_id=msg_id,
                    thread_id=thread_id,
                    subject=subject,
                    sender=sender,
                    recipients=recipients,
                    labels=labels_str,
                    email_date=email_date,
                    text=full_text,
                    has_attachments=has_attachments,
                    doc_type=doc_type,
                    doc_type_score=doc_type_score,
                )

                # Facts extraction
                delete_facts_by_file_id(conn, file_id)
                extracted_facts = extract_facts(full_text, filename=subject, path=f"gmail://{msg_id}")
                if extracted_facts:
                    insert_facts_batch(
                        conn,
                        [
                            (file_id, f.kind, f.label, f.value, f.value_date, f.snippet)
                            for f in extracted_facts
                        ],
                    )

                # Chunking & embedding
                delete_chunks_by_file_id(conn, file_id)
                chunks = chunk_file(f"gmail://{msg_id}", "indexed", full_text)
                if chunks and embedder is not None:
                    try:
                        chunk_texts = [c.text for c in chunks]
                        vectors = embedder.embed_texts(chunk_texts)
                        chunk_data = [
                            (file_id, c.chunk_index, c.kind, c.text, vectors[i].tobytes(), embedder.model_name)
                            for i, c in enumerate(chunks)
                        ]
                        insert_chunks_batch(conn, chunk_data)
                        del vectors
                    except Exception as emb_exc:
                        logger.warning("Failed to embed email chunks for %s: %s", msg_id, emb_exc)

                synced_count += 1

                # Clean up memory after each message
                del full_text
                del cleaned_body
                del attachment_texts
                del chunks
                gc.collect()

                if synced_count >= max_messages:
                    break

            page_token = list_res.get("nextPageToken")
            if not page_token:
                break

        # 5. Finalize sync
        now_ts = time.time()
        set_setting(conn, "gmail_last_sync_time", str(now_ts))
        conn.commit()
        invalidate_vector_cache()

        return {
            "synced": synced_count,
            "deleted": deleted_count,
            "email": user_email,
            "last_sync": now_ts,
        }
    finally:
        conn.close()


def disconnect_gmail(db_path: Path | str | None = None) -> dict[str, Any]:
    """
    Disconnect Gmail:
    - Deletes token from keyring
    - Deletes all Gmail rows from files (cascading to emails, contents, chunks, facts)
    - Cleans up settings
    - Invalidates vector cache
    """
    delete_credentials()

    conn = get_connection(db_path)
    try:
        init_db(db_path)
        deleted_count = delete_all_gmail_data(conn)
        conn.execute("DELETE FROM settings WHERE key IN ('gmail_connected_email', 'gmail_last_sync_time')")
        conn.commit()
    finally:
        conn.close()

    invalidate_vector_cache()
    return {
        "ok": True,
        "message": "Gmail disconnected and all email data deleted.",
        "deleted_count": deleted_count,
    }


def get_gmail_status(db_path: Path | str | None = None) -> dict[str, Any]:
    """Return Gmail connection and synchronization status."""
    connected = is_connected()
    conn = get_connection(db_path)
    try:
        init_db(db_path)
        email_addr = get_setting(conn, "gmail_connected_email")
        last_sync_str = get_setting(conn, "gmail_last_sync_time")
        last_sync = float(last_sync_str) if last_sync_str else None
        msg_count = get_gmail_status_db(conn)
        return {
            "connected": connected,
            "email": email_addr,
            "last_sync": last_sync,
            "message_count": msg_count,
        }
    finally:
        conn.close()
