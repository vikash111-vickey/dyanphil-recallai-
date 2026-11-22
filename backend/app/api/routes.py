"""API routes for Dyanphil search assistant."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.db import (
    get_connection,
    get_email_metadata_by_file_id,
    get_expiring_facts,
    get_facts_by_file_id,
    get_file_by_path,
    get_setting,
    get_vault_file_ids,
    get_vault_items,
    get_vault_suggestions,
    normalize_windows_path,
    pin_file_to_vault,
    set_setting,
    unpin_file_from_vault,
)
from app.config import settings
from app.ingestion.auto_index import (
    add_configured_folder,
    get_auto_index_worker,
    get_configured_folders,
    remove_configured_folder,
    get_excluded_folders,
    add_excluded_folder,
    remove_excluded_folder,
    get_image_folders,
    add_image_folder,
    remove_image_folder,
)
from app.search.composer import compose_reply
from app.search.facts_answer import find_fact_answer
from app.search.followup import (
    detect_followup,
    execute_followup,
    get_session,
    record_message,
    reset_sessions,
)
from app.search.hybrid import hybrid_search, query_has_image_word
from app.search.query import parse_query
from app.search.tone import detect_tone
from app.search.verify import verify_faithfulness
from app.security.logger import format_safe_query
from app.security.masking import mask_all_sensitive, mask_obj
from app.vault.service import (
    is_pin_setup,
    setup_pin,
    unlock_vault,
    verify_token,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class AskRequest(BaseModel):
    message: str = Field(..., description="User query or instruction")
    session_id: str | None = Field(default=None, description="Optional conversation session ID")


class FactItem(BaseModel):
    kind: str
    label: str
    value: str
    value_date: str | None = None


class SearchResultItem(BaseModel):
    filename: str
    path: str
    breadcrumb: list[str]
    source: str = "local file"
    modified: str
    snippet: str
    match_type: str
    exists: bool
    doc_type: str = "other"
    facts: list[FactItem] = Field(default_factory=list)
    sender: str | None = None
    subject: str | None = None
    date: str | None = None
    labels: list[str] = Field(default_factory=list)


def format_search_result_item(conn: sqlite3.Connection, r: dict[str, Any]) -> SearchResultItem:
    """Format a raw result dict into SearchResultItem with full Gmail and local file support."""
    p_str = r["path"]
    is_gmail = p_str.startswith("gmail://") or r.get("source") == "gmail"
    p = Path(p_str)
    mtime_dt = (
        datetime.fromtimestamp(r["modified_at"]).strftime("%Y-%m-%d %H:%M:%S")
        if r.get("modified_at")
        else r.get("modified", "")
    )
    snippet = mask_all_sensitive(r.get("snippet", "").replace("\n", " ").strip())

    file_row = get_file_by_path(conn, p_str)
    fid = file_row["id"] if file_row else r.get("id") or r.get("file_id")
    file_facts: list[FactItem] = []
    doc_type = file_row["doc_type"] if file_row and file_row["doc_type"] else r.get("doc_type", "other")
    if fid:
        fact_rows = get_facts_by_file_id(conn, fid, limit=3)
        for fr in fact_rows:
            file_facts.append(
                FactItem(
                    kind=fr["kind"],
                    label=mask_all_sensitive(fr["label"]),
                    value=mask_all_sensitive(fr["value"]),
                    value_date=fr["value_date"],
                )
            )

    if is_gmail:
        email_meta = get_email_metadata_by_file_id(conn, fid) if fid else None
        sender = email_meta.get("sender") if email_meta else r.get("sender")
        labels_raw = email_meta.get("labels") if email_meta else r.get("labels")
        labels: list[str] = []
        if isinstance(labels_raw, str):
            try:
                labels = json.loads(labels_raw)
            except Exception:
                labels = [labels_raw]
        elif isinstance(labels_raw, list):
            labels = labels_raw
        first_label = labels[0] if labels else "Inbox"
        subject = r["filename"]
        breadcrumb = ["Gmail", first_label, subject]
        return SearchResultItem(
            filename=subject,
            path=p_str,
            breadcrumb=breadcrumb,
            source="gmail",
            modified=mtime_dt,
            snippet=snippet,
            match_type=r.get("match_type", "both"),
            exists=True,
            doc_type=doc_type,
            facts=file_facts,
            sender=sender,
            subject=subject,
            date=mtime_dt,
            labels=labels,
        )
    else:
        return SearchResultItem(
            filename=r["filename"],
            path=p_str,
            breadcrumb=r.get("breadcrumb") or list(p.parts),
            source="local file",
            modified=mtime_dt,
            snippet=snippet,
            match_type=r.get("match_type", "both"),
            exists=r.get("exists", safe_file_exists(p)),
            doc_type=doc_type,
            facts=file_facts,
            sender=None,
            subject=None,
            date=None,
            labels=[],
        )


class AskResponse(BaseModel):
    tone: str
    urgency: str
    message: str
    results: list[SearchResultItem]


class OpenRequest(BaseModel):
    path: str = Field(..., description="Full path to the file")
    folder: bool = Field(False, description="Open folder with file selected if True")


class OpenResponse(BaseModel):
    ok: bool
    message: str = ""


class DeleteAllRequest(BaseModel):
    confirm: str = Field(..., description="Must be exactly 'DELETE'")


class DeleteAllResponse(BaseModel):
    ok: bool = True
    message: str = "All data deleted successfully"
    deleted: dict[str, int]


class PrivacyInfoResponse(BaseModel):
    data_folder: str
    database_size: int
    database_size_formatted: str
    files_indexed: int
    folders_count: int
    folders: list[str]
    vault_pin_set: bool
    embedding_model: str


class VaultSetupRequest(BaseModel):
    pin: str = Field(..., description="4 to 8 digit numeric PIN")


class VaultUnlockRequest(BaseModel):
    pin: str = Field(..., description="4 to 8 digit numeric PIN")


class VaultUnlockResponse(BaseModel):
    ok: bool
    token: str
    expires_in: int = 600


class VaultPinRequest(BaseModel):
    path: str = Field(..., description="Path to the file to pin")
    label: str = Field("", description="Optional human-readable label")


class VaultItemResponse(BaseModel):
    id: int
    file_id: int
    label: str
    filename: str
    path: str
    breadcrumb: list[str]
    doc_type: str
    exists: bool
    created_at: float
    modified: str
    facts: list[FactItem] = Field(default_factory=list)


def safe_file_exists(p: Path | str) -> bool:
    """Check if file exists on disk, safely catching Windows permission and OS errors."""
    clean = str(p).strip().strip('"').strip("'")
    try:
        path_obj = Path(clean)
        if path_obj.exists():
            return True
        if path_obj.resolve().exists():
            return True
    except (PermissionError, OSError):
        pass
    try:
        return os.path.exists(clean)
    except Exception:
        return False


def perform_open(raw_path: str, folder: bool) -> tuple[bool, str]:
    """
    Open the file (os.startfile) or open its containing folder with the file selected.
    Verifies existence in DB and on disk.
    Used by POST /open and session follow-up commands.
    """
    clean_path = raw_path.strip().strip('"').strip("'")
    if not clean_path:
        err_msg = "Empty path provided"
        logger.error(err_msg)
        return False, err_msg

    # Handle Gmail message opening
    if clean_path.startswith("gmail://"):
        msg_id = clean_path[len("gmail://"):].strip()
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id FROM files WHERE source = 'gmail' AND external_id = ?",
                (msg_id,),
            ).fetchone()
            if not row:
                err_msg = f"Email message ID not found in database: {msg_id}"
                logger.error(err_msg)
                return False, err_msg
        finally:
            conn.close()

        if folder:
            return False, "Folder view is not supported for Gmail messages."

        import webbrowser
        email_url = f"https://mail.google.com/mail/u/0/#all/{msg_id}"
        try:
            webbrowser.open(email_url)
            return True, f"Opened email in browser: {email_url}"
        except Exception as exc:
            err_msg = f"Failed to open email URL: {exc}"
            logger.error(err_msg)
            return False, err_msg

    # 1. Verify existence in database with normalized lookup (normcase and normpath)
    conn = get_connection()
    try:
        db_record = get_file_by_path(conn, clean_path)
    finally:
        conn.close()

    if db_record is not None:
        actual_path_str = db_record["path"]
    else:
        # Check if the path exists directly on disk
        if safe_file_exists(clean_path):
            actual_path_str = clean_path
        else:
            err_msg = f"Path not found in database: {clean_path}"
            logger.error(err_msg)
            return False, err_msg

    # 2. Verify existence on disk
    target_path = Path(actual_path_str)
    if not safe_file_exists(target_path):
        if not safe_file_exists(Path(clean_path)):
            err_msg = f"File no longer exists on disk: {actual_path_str}"
            logger.error(err_msg)
            return False, err_msg
        target_path = Path(clean_path)

    # 3. Robust canonical Windows path
    try:
        resolved_full_path = os.path.normpath(str(target_path.resolve()))
    except Exception:
        resolved_full_path = os.path.normpath(str(target_path))

    # 4. Perform open action
    if folder:
        try:
            subprocess.Popen(f'explorer.exe /select,"{resolved_full_path}"')
            return True, "Folder opened successfully"
        except Exception as exc:
            err_msg = f"Failed to open folder: {exc}"
            logger.error(err_msg, exc_info=True)
            return False, err_msg
    else:
        try:
            if hasattr(os, "startfile"):
                os.startfile(resolved_full_path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["cmd", "/c", "start", "", resolved_full_path], shell=True)
            return True, "File opened successfully"
        except Exception as exc:
            err_msg = f"Failed to open file: {exc}"
            logger.error(err_msg, exc_info=True)
            return False, err_msg


def require_vault_token(x_vault_token: str | None = Header(None, alias="X-Vault-Token")) -> str:
    """Dependency enforcing valid X-Vault-Token header for vault access."""
    if not x_vault_token or not verify_token(x_vault_token):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired vault token. Please unlock the vault first.",
        )
    return x_vault_token


@router.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@router.get("/expiring")
def expiring_documents(days: int = 60) -> list[dict[str, Any]]:
    """
    List files with an expiry or due date in the next N days,
    and already expired ones, sorted by date.
    All returned facts and snippets are masked for sensitive data.
    """
    conn = get_connection()
    try:
        items = get_expiring_facts(conn, days=days)
        return mask_obj(items)
    finally:
        conn.close()


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    """
    Search and answer endpoint:
    - Supports session_id for follow-up actions ("open it", "the older one", "aur dikhao")
    - Analyzes tone and urgency
    - Checks fact questions first ("when does X expire", "what is my X number", "how much is X")
    - Prioritizes emergency vault pinned matches when tone is urgent/stressed
    - Performs hybrid search with doc_type boost
    - Returns tailored message and up to 5 results with doc_type and up to 3 facts
    """
    user_msg = payload.message.strip()
    session_id = payload.session_id.strip() if payload.session_id else None

    # Privacy logging: log event name and query truncated to 80 chars
    logger.info("Event ask received: query='%s'", format_safe_query(user_msg, max_len=80))

    if session_id:
        record_message(session_id, "user", user_msg)

    if not user_msg:
        tone_info = {"tone": "neutral", "urgency": "low"}
        reply = compose_reply("neutral", [])
        if session_id:
            record_message(session_id, "assistant", reply)
        return AskResponse(
            tone=tone_info["tone"],
            urgency=tone_info["urgency"],
            message=reply,
            results=[],
        )

    # 1. Detect tone and urgency
    tone_info = detect_tone(user_msg)

    # 2. Check for follow-up commands if session_id is active
    if session_id:
        followup_cmd = detect_followup(user_msg)
        if followup_cmd is not None:
            action_type, action_arg = followup_cmd
            sess = get_session(session_id)
            reply_msg, follow_results = execute_followup(
                session=sess,
                action_type=action_type,
                action_arg=action_arg,
                tone=tone_info["tone"],
                open_handler=perform_open,
            )
            record_message(session_id, "assistant", reply_msg)

            formatted_follow: list[SearchResultItem] = []
            for r in follow_results:
                if isinstance(r, SearchResultItem):
                    formatted_follow.append(r)
                else:
                    p = Path(r["path"])
                    mtime_dt = (
                        datetime.fromtimestamp(r["modified_at"]).strftime("%Y-%m-%d %H:%M:%S")
                        if r.get("modified_at")
                        else r.get("modified", "")
                    )
                    snippet = mask_all_sensitive(r.get("snippet", "").replace("\n", " ").strip())
                    file_facts: list[FactItem] = []
                    for f in r.get("facts", []):
                        if isinstance(f, FactItem):
                            file_facts.append(
                                FactItem(
                                    kind=f.kind,
                                    label=mask_all_sensitive(f.label),
                                    value=mask_all_sensitive(f.value),
                                    value_date=f.value_date,
                                )
                            )
                        elif isinstance(f, dict):
                            file_facts.append(
                                FactItem(
                                    kind=f.get("kind", ""),
                                    label=mask_all_sensitive(f.get("label", "")),
                                    value=mask_all_sensitive(f.get("value", "")),
                                    value_date=f.get("value_date"),
                                )
                            )

                    formatted_follow.append(
                        SearchResultItem(
                            filename=r["filename"],
                            path=r["path"],
                            breadcrumb=r.get("breadcrumb", list(p.parts)),
                            source="local file",
                            modified=mtime_dt,
                            snippet=snippet,
                            match_type=r.get("match_type", "both"),
                            exists=r.get("exists", safe_file_exists(p)),
                            doc_type=r.get("doc_type", "other"),
                            facts=file_facts,
                        )
                    )

            return AskResponse(
                tone=tone_info["tone"],
                urgency=tone_info["urgency"],
                message=mask_all_sensitive(reply_msg),
                results=formatted_follow,
            )

    try:
        conn = get_connection()
    except (sqlite3.OperationalError, sqlite3.DatabaseError, FileNotFoundError, OSError) as exc:
        logger.error("Database connection error: %s", exc)
        friendly_msg = "The search database is currently busy or unavailable. Please try again in a moment."
        return AskResponse(
            tone="neutral",
            urgency="low",
            message=friendly_msg,
            results=[],
        )

    try:
        # 3. Check fact answering first
        fact_answer = find_fact_answer(conn, user_msg, tone=tone_info["tone"])
        if fact_answer is not None:
            raw_reply_msg, fact_results = fact_answer
            reply_msg, _ = verify_faithfulness(conn, raw_reply_msg, fact_results)
            formatted_results = [format_search_result_item(conn, r) for r in fact_results[:5]]

            if session_id:
                sess = get_session(session_id)
                sess.last_results = [res.model_dump() for res in formatted_results]
                sess.shown_offset = len(formatted_results)
                record_message(session_id, "assistant", reply_msg)

            return AskResponse(
                tone=tone_info["tone"],
                urgency=tone_info["urgency"],
                message=mask_all_sensitive(reply_msg),
                results=formatted_results,
            )

        # 4. Standard hybrid search
        parsed = parse_query(user_msg)
        search_query = parsed.cleaned_query if parsed.cleaned_query else user_msg

        try:
            raw_results = hybrid_search(
                conn=conn,
                query=search_query,
                mode="hybrid",
                limit=15,
                file_types=parsed.file_types,
                min_modified=parsed.min_modified,
                doc_types=parsed.doc_types,
                source=parsed.source,
                sender=parsed.sender,
            )
        except Exception as exc:
            logger.warning("Hybrid search encountered an error (%s); falling back to keyword search.", exc)
            raw_results = hybrid_search(
                conn=conn,
                query=search_query,
                mode="keyword",
                limit=15,
                file_types=parsed.file_types,
                min_modified=parsed.min_modified,
                doc_types=parsed.doc_types,
                source=parsed.source,
                sender=parsed.sender,
            )

        # 5. Emergency behaviour:
        # If tone is urgent/stressed (urgency high) and query matches a pinned vault file,
        # return pinned matches first and briefly say so in the reply.
        # Pinned files are returned strictly as normal SearchResultItems (no secret data leaked).
        vault_fids = get_vault_file_ids(conn)
        prioritized_vault = False

        if (tone_info["tone"] in ("urgent", "stressed") or tone_info["urgency"] == "high") and vault_fids:
            pinned_in_results: list[dict[str, Any]] = []
            for r in raw_results:
                row = get_file_by_path(conn, r["path"])
                if row and row["id"] in vault_fids:
                    pinned_in_results.append(r)

            # Also check direct title/path/label match from vault items
            vault_items = get_vault_items(conn)
            query_words = [w.lower() for w in search_query.split() if len(w) >= 2]
            direct_vault_matches: list[dict[str, Any]] = []
            for vi in vault_items:
                vi_text = f"{vi['filename']} {vi['label']} {vi['path']} {vi['doc_type']}".lower()
                if any(qw in vi_text for qw in query_words) or not query_words:
                    if not any(r["path"] == vi["path"] for r in pinned_in_results):
                        direct_vault_matches.append({
                            "id": vi["file_id"],
                            "path": vi["path"],
                            "filename": vi["filename"],
                            "ext": Path(vi["path"]).suffix,
                            "size": 0,
                            "modified_at": vi.get("modified_at", 0),
                            "doc_type": vi["doc_type"],
                            "match_type": "vault",
                            "snippet": f"Emergency Vault: {vi['label'] or vi['filename']}",
                        })

            all_vault_matches = pinned_in_results + direct_vault_matches
            if all_vault_matches:
                prioritized_vault = True
                seen_paths = {p["path"] for p in all_vault_matches}
                other_results = [r for r in raw_results if r["path"] not in seen_paths]
                raw_results = all_vault_matches + other_results

        # Format results for user response
        formatted_results = [format_search_result_item(conn, r) for r in raw_results]

        # Enforce image search policy:
        # Results of type image are returned ONLY when query has image word or < 3 doc results exist.
        # Documents never outranked by images for non-image queries.
        if not query_has_image_word(user_msg):
            def is_item_image(it: SearchResultItem) -> bool:
                ext = Path(it.path).suffix.lower()
                return ext in (".png", ".jpg", ".jpeg") or it.doc_type in ("image", "photo")

            doc_items = [it for it in formatted_results if not is_item_image(it)]
            img_items = [it for it in formatted_results if is_item_image(it)]
            if len(doc_items) >= 3:
                formatted_results = doc_items[:5]
            else:
                formatted_results = (doc_items + img_items)[:5]
        else:
            formatted_results = formatted_results[:5]

        dict_results = [res.model_dump() for res in formatted_results]
        base_reply = compose_reply(tone_info["tone"], dict_results)
        if prioritized_vault and formatted_results:
            first_fname = formatted_results[0].filename
            reply_message = f"I've prioritized your emergency vault document ({first_fname}) first. {base_reply}"
        else:
            reply_message = base_reply

        verified_reply, _ = verify_faithfulness(conn, reply_message, dict_results)
        masked_reply_message = mask_all_sensitive(verified_reply)

        # Save session history for follow-ups
        if session_id:
            sess = get_session(session_id)
            # Store full raw results list (up to 15) in session so "show more" works
            session_items: list[dict[str, Any]] = []
            for r in raw_results:
                item_obj = format_search_result_item(conn, r)
                session_items.append(item_obj.model_dump())
            sess.last_results = session_items
            sess.shown_offset = len(formatted_results)
            record_message(session_id, "assistant", masked_reply_message)

        return AskResponse(
            tone=tone_info["tone"],
            urgency=tone_info["urgency"],
            message=masked_reply_message,
            results=formatted_results,
        )
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
        logger.error("Database operational error during ask: %s", exc)
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            msg = "The database is currently busy with background tasks. Please try again in a moment."
        else:
            msg = "The search database is currently unavailable. Please try again in a moment."
        return AskResponse(
            tone="neutral",
            urgency="low",
            message=msg,
            results=[],
        )
    finally:
        conn.close()


@router.post("/open", response_model=OpenResponse)
def open_item(payload: OpenRequest) -> OpenResponse:
    """
    Open the file (os.startfile) or open its containing folder with the file selected.
    Requires path to exist in the database and on disk.
    Returns JSON {"ok": true|false, "message": "..."} and logs any error on the server.
    """
    ok, message = perform_open(payload.path, payload.folder)
    return OpenResponse(ok=ok, message=message)


# ─────────────────────────────────────────────────────────────────────────────
# Vault Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/vault/setup")
def setup_vault_pin(payload: VaultSetupRequest) -> dict[str, Any]:
    """Configure vault PIN (only if no PIN exists, 4-8 digits)."""
    conn = get_connection()
    try:
        setup_pin(conn, payload.pin)
        return {"ok": True, "message": "Vault PIN setup successfully"}
    finally:
        conn.close()


@router.post("/vault/unlock", response_model=VaultUnlockResponse)
def unlock_vault_endpoint(payload: VaultUnlockRequest) -> VaultUnlockResponse:
    """Unlock vault with PIN, returning a 10-minute session token. Locks 60s after 5 failed attempts."""
    conn = get_connection()
    try:
        token = unlock_vault(conn, payload.pin)
        return VaultUnlockResponse(ok=True, token=token, expires_in=600)
    finally:
        conn.close()


@router.get("/vault", response_model=list[VaultItemResponse])
def get_vault_files(token: str = Depends(require_vault_token)) -> list[dict[str, Any]]:
    """List pinned vault files with path, breadcrumb, doc_type, key facts, and exists flag."""
    conn = get_connection()
    try:
        items = get_vault_items(conn)
        return mask_obj(items)
    finally:
        conn.close()


@router.post("/vault/pin")
def pin_file(payload: VaultPinRequest, token: str = Depends(require_vault_token)) -> dict[str, Any]:
    """Pin a file to the emergency vault by its path."""
    conn = get_connection()
    try:
        file_row = get_file_by_path(conn, payload.path)
        if not file_row:
            raise HTTPException(
                status_code=404,
                detail=f"File not found in database: {payload.path}",
            )
        vault_id = pin_file_to_vault(conn, file_row["id"], payload.label)
        return {"ok": True, "id": vault_id, "message": "File pinned to vault"}
    finally:
        conn.close()


@router.delete("/vault/{vault_id}")
def unpin_file(vault_id: int, token: str = Depends(require_vault_token)) -> dict[str, Any]:
    """Unpin a file from the emergency vault by its vault id."""
    conn = get_connection()
    try:
        ok = unpin_file_from_vault(conn, vault_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Vault item not found")
        return {"ok": True, "message": "File unpinned from vault"}
    finally:
        conn.close()


@router.get("/vault/suggestions")
def vault_suggestions(token: str = Depends(require_vault_token)) -> list[dict[str, Any]]:
    """Retrieve top 20 indexed files eligible for the emergency vault not yet pinned."""
    conn = get_connection()
    try:
        items = get_vault_suggestions(conn, limit=20)
        return mask_obj(items)
    finally:
        conn.close()


class FolderSettingsRequest(BaseModel):
    path: str = Field(..., description="Absolute folder path to index")


class FolderSettingsResponse(BaseModel):
    ok: bool = True
    folders: list[str]


class IndexStatusResponse(BaseModel):
    running: bool
    current_task: str | None = None
    files_total: int
    by_status: dict[str, int]
    last_run_time: str | None = None
    pending_ocr_count: int


@router.get("/settings/folders")
def get_folders_endpoint() -> dict[str, Any]:
    """Retrieve list of configured indexed folders."""
    conn = get_connection()
    try:
        folders = get_configured_folders(conn)
        return {"ok": True, "folders": folders}
    finally:
        conn.close()


@router.post("/settings/folders")
def add_folder_endpoint(payload: FolderSettingsRequest) -> dict[str, Any]:
    """Add a folder to be indexed, rejecting non-existent and system directories."""
    conn = get_connection()
    try:
        try:
            updated = add_configured_folder(conn, payload.path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        worker = get_auto_index_worker()
        worker.update_watches()
        return {"ok": True, "folders": updated}
    finally:
        conn.close()


@router.delete("/settings/folders")
def delete_folder_endpoint(
    payload: FolderSettingsRequest | None = Body(None),
    path: str | None = None,
) -> dict[str, Any]:
    """Remove a folder from settings and remove its indexed files."""
    target_path = (payload.path if payload else None) or path
    if not target_path:
        raise HTTPException(status_code=400, detail="Missing folder path.")

    conn = get_connection()
    try:
        updated = remove_configured_folder(conn, target_path)
        worker = get_auto_index_worker()
        worker.update_watches()
        return {"ok": True, "folders": updated}
    finally:
        conn.close()


@router.get("/settings/excluded-folders")
def get_excluded_folders_endpoint() -> dict[str, Any]:
    """Retrieve list of excluded folders."""
    conn = get_connection()
    try:
        folders = get_excluded_folders(conn)
        return {"ok": True, "folders": folders}
    finally:
        conn.close()


@router.post("/settings/excluded-folders")
def add_excluded_folder_endpoint(payload: FolderSettingsRequest) -> dict[str, Any]:
    """Add a folder name or path to the excluded folders list."""
    conn = get_connection()
    try:
        try:
            updated = add_excluded_folder(conn, payload.path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        worker = get_auto_index_worker()
        worker.update_watches()
        return {"ok": True, "folders": updated}
    finally:
        conn.close()


@router.delete("/settings/excluded-folders")
def delete_excluded_folder_endpoint(
    payload: FolderSettingsRequest | None = Body(None),
    path: str | None = None,
) -> dict[str, Any]:
    """Remove a folder from the excluded folders list."""
    target_path = (payload.path if payload else None) or path
    if not target_path:
        raise HTTPException(status_code=400, detail="Missing folder path.")
    conn = get_connection()
    try:
        updated = remove_excluded_folder(conn, target_path)
        worker = get_auto_index_worker()
        worker.update_watches()
        return {"ok": True, "folders": updated}
    finally:
        conn.close()


@router.get("/settings/image-folders")
def get_image_folders_endpoint() -> dict[str, Any]:
    """Retrieve list of configured image folders."""
    conn = get_connection()
    try:
        folders = get_image_folders(conn)
        return {"ok": True, "folders": folders}
    finally:
        conn.close()


@router.post("/settings/image-folders")
def add_image_folder_endpoint(payload: FolderSettingsRequest) -> dict[str, Any]:
    """Add a folder to the image folders list."""
    conn = get_connection()
    try:
        try:
            updated = add_image_folder(conn, payload.path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        worker = get_auto_index_worker()
        worker.update_watches()
        return {"ok": True, "folders": updated}
    finally:
        conn.close()


@router.delete("/settings/image-folders")
def delete_image_folder_endpoint(
    payload: FolderSettingsRequest | None = Body(None),
    path: str | None = None,
) -> dict[str, Any]:
    """Remove a folder from the image folders list."""
    target_path = (payload.path if payload else None) or path
    if not target_path:
        raise HTTPException(status_code=400, detail="Missing folder path.")
    conn = get_connection()
    try:
        updated = remove_image_folder(conn, target_path)
        worker = get_auto_index_worker()
        worker.update_watches()
        return {"ok": True, "folders": updated}
    finally:
        conn.close()


@router.post("/index/run")
def trigger_index_run() -> dict[str, Any]:
    """Trigger incremental full scan and indexing in background."""
    worker = get_auto_index_worker()
    started = worker.enqueue_index()
    if not started:
        raise HTTPException(
            status_code=409,
            detail="A background task is already running",
        )
    return {"ok": True, "message": "Indexing started in background"}


@router.post("/ocr/run")
def trigger_ocr_run() -> dict[str, Any]:
    """Trigger background OCR processing for pending scanned files."""
    worker = get_auto_index_worker()
    started = worker.enqueue_ocr()
    if not started:
        raise HTTPException(
            status_code=409,
            detail="A background task is already running",
        )
    return {"ok": True, "message": "OCR started in background"}


@router.get("/index/status", response_model=IndexStatusResponse)
def index_status_endpoint() -> IndexStatusResponse:
    """Retrieve current background worker and indexing status."""
    worker = get_auto_index_worker()
    status = worker.get_status()
    return IndexStatusResponse(**status)


# ─────────────────────────────────────────────────────────────────────────────
# Privacy and Data Control Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/data/delete-all", response_model=DeleteAllResponse)
def delete_all_data(
    payload: DeleteAllRequest,
    x_vault_token: str | None = Header(None, alias="X-Vault-Token"),
) -> DeleteAllResponse:
    """
    Delete all data in the database, vacuum, clear cache files, and restart background worker.
    Requires confirm == 'DELETE'.
    If a vault PIN is set, requires a valid vault token in X-Vault-Token header.
    """
    if payload.confirm != "DELETE":
        raise HTTPException(
            status_code=400,
            detail="Confirmation failed. Must provide exactly 'DELETE'.",
        )

    conn = get_connection()
    try:
        if is_pin_setup(conn):
            if not x_vault_token or not verify_token(x_vault_token):
                raise HTTPException(
                    status_code=401,
                    detail="Valid vault token is required to delete all data when a vault PIN is configured.",
                )

        worker = get_auto_index_worker()
        worker.stop()

        def get_count(table: str) -> int:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                return int(row[0]) if row else 0
            except Exception:
                return 0

        counts = {
            "files": get_count("files"),
            "contents": get_count("contents"),
            "chunks": get_count("chunks"),
            "facts": get_count("facts"),
            "vault": get_count("vault"),
            "settings": get_count("settings"),
        }

        conn.execute("DELETE FROM contents;")
        conn.execute("DELETE FROM chunks;")
        conn.execute("DELETE FROM facts;")
        conn.execute("DELETE FROM vault;")
        conn.execute("DELETE FROM files;")
        conn.execute("DELETE FROM settings;")
        try:
            conn.execute("DELETE FROM file_fts;")
        except Exception:
            pass
        conn.commit()

        # Run VACUUM
        conn.execute("VACUUM;")

        # Clear in-memory sessions
        reset_sessions()

        # Delete data/last_search.json and cache files in data/
        data_dir = settings.data_dir
        if data_dir.exists():
            for f in data_dir.iterdir():
                if f.is_file():
                    fname = f.name.lower()
                    if (
                        fname == "last_search.json"
                        or fname.endswith(".cache")
                        or fname.endswith(".tmp")
                        or fname.startswith("cache_")
                    ):
                        try:
                            f.unlink()
                        except OSError:
                            pass

        worker.start()
        logger.info(
            "Event data_delete_all: files=%d chunks=%d facts=%d",
            counts["files"],
            counts["chunks"],
            counts["facts"],
        )
        return DeleteAllResponse(
            ok=True,
            message="All data deleted successfully",
            deleted=counts,
        )
    finally:
        conn.close()


@router.get("/privacy", response_model=PrivacyInfoResponse)
def get_privacy_info() -> PrivacyInfoResponse:
    """
    Returns privacy and storage status:
    data folder, database size, number of files indexed, number of folders,
    whether a vault PIN is set, and embedding model used.
    """
    conn = get_connection()
    try:
        data_folder = str(settings.data_dir)
        db_file = settings.resolved_db_path
        db_size = db_file.stat().st_size if db_file.exists() else 0
        if db_size >= 1024 * 1024:
            db_size_fmt = f"{db_size / (1024 * 1024):.2f} MB"
        elif db_size >= 1024:
            db_size_fmt = f"{db_size / 1024:.2f} KB"
        else:
            db_size_fmt = f"{db_size} bytes"

        row = conn.execute("SELECT COUNT(*) FROM files").fetchone()
        files_indexed = int(row[0]) if row else 0

        folders = get_configured_folders(conn)
        folders_count = len(folders)
        vault_pin_set = is_pin_setup(conn)
        embedding_model = settings.embedding_model

        return PrivacyInfoResponse(
            data_folder=data_folder,
            database_size=db_size,
            database_size_formatted=db_size_fmt,
            files_indexed=files_indexed,
            folders_count=folders_count,
            folders=folders,
            vault_pin_set=vault_pin_set,
            embedding_model=embedding_model,
        )
    finally:
        conn.close()


class GmailStatusResponse(BaseModel):
    connected: bool
    email: str | None = None
    last_sync: float | None = None
    message_count: int = 0


@router.post("/gmail/connect")
def gmail_connect():
    """Start the OAuth flow for Gmail on 127.0.0.1 and open the browser."""
    try:
        from app.connectors.gmail_auth import start_auth_flow
        from googleapiclient.discovery import build

        creds = start_auth_flow(open_browser=True)
        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        user_email = profile.get("emailAddress", "")
        conn = get_connection()
        try:
            if user_email:
                set_setting(conn, "gmail_connected_email", user_email)
        finally:
            conn.close()
        return {"ok": True, "connected": True, "email": user_email}
    except Exception as exc:
        logger.error("Gmail connect failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/gmail/status", response_model=GmailStatusResponse)
def gmail_status() -> GmailStatusResponse:
    """Return Gmail connection and synchronization status."""
    from app.connectors.gmail import get_gmail_status

    status = get_gmail_status()
    return GmailStatusResponse(**status)


@router.post("/gmail/sync")
def gmail_sync():
    """Trigger background incremental Gmail sync using the single heavy job lock."""
    from app.connectors.gmail_auth import is_connected

    if not is_connected():
        raise HTTPException(status_code=400, detail="Gmail is not connected. Please connect first.")

    worker = get_auto_index_worker()
    enqueued = worker.enqueue_gmail_sync()
    if not enqueued:
        raise HTTPException(
            status_code=409,
            detail=f"Another heavy task ({worker.current_task()}) is currently running. Please wait for it to finish.",
        )
    return {"ok": True, "message": "Gmail sync started in background."}


@router.post("/gmail/disconnect")
def gmail_disconnect():
    """Disconnect Gmail: delete credentials from keyring and delete all Gmail rows from database."""
    from app.connectors.gmail import disconnect_gmail

    res = disconnect_gmail()
    return res


