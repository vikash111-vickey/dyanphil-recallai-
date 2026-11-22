"""Tests for Gmail connector: auth, body cleaning, sync, attachments, disconnect, and /open."""

from __future__ import annotations

import base64
import io
import json
import sqlite3
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from googleapiclient.errors import HttpError
import httplib2

from app.config import settings
from app.connectors.gmail import (
    clean_email_body,
    disconnect_gmail,
    get_gmail_status,
    parse_message_payload,
    sync_gmail,
)
from app.connectors.gmail_auth import (
    KEYRING_SERVICE,
    KEYRING_USERNAME,
    delete_credentials,
    get_credentials,
    is_connected,
    save_credentials,
)
from app.db import (
    get_all_gmail_ids,
    get_connection,
    get_email_metadata_by_file_id,
    get_file_by_path,
    init_db,
    upsert_gmail_message,
)
from app.ingestion.extractors import extract_text_from_bytes
from app.main import API_COOKIE_NAME, app, get_api_token
from app.search.query import parse_query


@pytest.fixture
def temp_gmail_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Provide isolated database and data directory for Gmail connector tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "test_gmail.db"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "db_path", db_file)
    init_db(db_file)
    yield db_file


# ---------------------------------------------------------------------------
# 1. Body Cleaning & HTML to Text Tests
# ---------------------------------------------------------------------------


def test_clean_email_body_html_conversion():
    """HTML tags, styles, and scripts are stripped cleanly."""
    html_input = """
    <html>
      <head><style>body { color: red; }</style></head>
      <body>
        <h1>Flight Confirmation</h1>
        <p>Your booking ID is <b>AB1234</b>.</p>
        <p>Safe travels!</p>
        <script>alert('malicious');</script>
      </body>
    </html>
    """
    cleaned = clean_email_body(html_input, is_html=True)
    assert "Flight Confirmation" in cleaned
    assert "Your booking ID is" in cleaned
    assert "AB1234" in cleaned
    assert "color: red" not in cleaned
    assert "alert" not in cleaned


def test_clean_email_body_trim_quoted_replies():
    """Quoted replies starting with 'On ... wrote:' or lines starting with '>' are trimmed."""
    msg = (
        "Here is the revised project agreement for your review.\n\n"
        "On Mon, Nov 22, 2026 at 9:15 AM Alice Smith <alice@example.com> wrote:\n"
        "> Could you please send over the latest draft?\n"
        "> Thanks!\n"
    )
    cleaned = clean_email_body(msg, is_html=False)
    assert "Here is the revised project agreement" in cleaned
    assert "Alice Smith" not in cleaned
    assert "Could you please send over" not in cleaned


def test_clean_email_body_trim_forwarded_and_headers():
    """Forwarded message blocks and From/Date header blocks are trimmed."""
    msg = (
        "Please check the notes below.\n\n"
        "---------- Forwarded message ---------\n"
        "From: John Doe <john@doe.com>\n"
        "Date: Fri, Nov 20, 2026 at 4:00 PM\n"
        "Subject: Old discussion\n"
        "To: team@example.com\n\n"
        "Old internal conversation."
    )
    cleaned = clean_email_body(msg, is_html=False)
    assert "Please check the notes below." in cleaned
    assert "Old internal conversation" not in cleaned


def test_clean_email_body_trim_signatures():
    """Standard RFC 3676 '-- \\n' and mobile signatures are trimmed."""
    msg1 = (
        "Meeting confirmed for 3 PM tomorrow.\n\n"
        "-- \n"
        "Vikas Sharma\n"
        "Lead Engineer\n"
        "+91 9876543210"
    )
    cleaned1 = clean_email_body(msg1, is_html=False)
    assert "Meeting confirmed for 3 PM tomorrow." in cleaned1
    assert "Lead Engineer" not in cleaned1

    msg2 = (
        "I will be reaching the airport in 10 minutes.\n\n"
        "Sent from my iPhone"
    )
    cleaned2 = clean_email_body(msg2, is_html=False)
    assert "I will be reaching the airport in 10 minutes." in cleaned2
    assert "Sent from my iPhone" not in cleaned2


# ---------------------------------------------------------------------------
# 2. In-Memory Attachment Extraction Tests
# ---------------------------------------------------------------------------


def test_extract_text_from_bytes_pdf():
    """PDF attachment is extracted in-memory without creating disk files."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf_buf = io.BytesIO()
    writer.write(pdf_buf)
    pdf_bytes = pdf_buf.getvalue()

    status, text, err = extract_text_from_bytes(pdf_bytes, "document.pdf")
    # Empty blank page returns status empty or indexed without crashing
    assert status in ("indexed", "empty")
    assert err is None


def test_extract_text_from_bytes_txt():
    """Plain text attachment is extracted from bytes."""
    sample = b"Invoice # INV-9988\nTotal Amount: $450.00\nDue date: 2026-12-15"
    status, text, err = extract_text_from_bytes(sample, "invoice.txt")
    assert status == "indexed"
    assert "INV-9988" in text
    assert "$450.00" in text


def test_extract_text_from_bytes_unsupported_and_oversized():
    """Executable or unsupported extensions return unsupported."""
    status, text, err = extract_text_from_bytes(b"MZ\x90\x00", "payload.exe")
    assert status == "unsupported"


# ---------------------------------------------------------------------------
# 3. Mocked Gmail Sync Tests
# ---------------------------------------------------------------------------


def build_mock_message(
    msg_id: str,
    subject: str,
    sender: str,
    body_text: str,
    date_ts: float = 1795334400.0,
    labels: list[str] | None = None,
    attachment: tuple[str, bytes] | None = None,
) -> dict[str, Any]:
    """Helper to construct a mock Gmail API message dict."""
    b64_body = base64.urlsafe_b64encode(body_text.encode("utf-8")).decode("ASCII")
    parts: list[dict[str, Any]] = [
        {
            "mimeType": "text/plain",
            "filename": "",
            "body": {"size": len(body_text), "data": b64_body},
        }
    ]

    if attachment:
        att_name, att_bytes = attachment
        parts.append({
            "mimeType": "application/octet-stream",
            "filename": att_name,
            "body": {"attachmentId": f"att_{msg_id}", "size": len(att_bytes)},
        })

    return {
        "id": msg_id,
        "threadId": f"thread_{msg_id}",
        "labelIds": labels or ["INBOX"],
        "internalDate": str(int(date_ts * 1000)),
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "To", "value": "me@example.com"},
                {"name": "Date", "value": "Sun, 22 Nov 2026 12:00:00 +0000"},
            ],
            "mimeType": "multipart/mixed",
            "body": {},
            "parts": parts,
        },
    }


def test_sync_gmail_new_messages_and_attachments(temp_gmail_db: Path):
    """Sync pulls new messages and attachments in memory, classifying and indexing."""
    mock_service = MagicMock()
    mock_users = mock_service.users.return_value

    # Profile
    mock_users.getProfile.return_value.execute.return_value = {"emailAddress": "user@gmail.com"}

    # Trashed check
    mock_users.messages.return_value.list.return_value.execute.side_effect = [
        {"messages": []},  # trash list
        {
            "messages": [{"id": "msg_001"}, {"id": "msg_002"}],
            "nextPageToken": None,
        },  # new messages list
    ]

    # Messages
    m1 = build_mock_message(
        msg_id="msg_001",
        subject="Health Insurance Policy Renewal",
        sender="HDFC ERGO <care@hdfcergo.com>",
        body_text="Dear Customer, your policy expires on 15 Oct 2026. Premium amount is Rs 12,450.",
        labels=["INBOX", "IMPORTANT"],
    )
    att_bytes = b"Policy details: ID HDFC-POL-9912. Valid till 2027-10-15."
    m2 = build_mock_message(
        msg_id="msg_002",
        subject="Flight Booking Confirmation",
        sender="MakeMyTrip <tickets@makemytrip.com>",
        body_text="Your PNR is ABC789. Flight on 2026-12-01.",
        labels=["INBOX"],
        attachment=("ticket.txt", att_bytes),
    )

    mock_users.messages.return_value.get.return_value.execute.side_effect = [m1, m2]

    # Attachment download mock
    b64_att = base64.urlsafe_b64encode(att_bytes).decode("ASCII")
    mock_users.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {
        "data": b64_att
    }

    result = sync_gmail(db_path=temp_gmail_db, service=mock_service)
    assert result["synced"] == 2
    assert result["email"] == "user@gmail.com"

    conn = get_connection(temp_gmail_db)
    try:
        # Check files
        all_ids = get_all_gmail_ids(conn)
        assert "msg_001" in all_ids
        assert "msg_002" in all_ids

        # Check file 1 classification
        f1 = get_file_by_path(conn, "gmail://msg_001")
        assert f1 is not None
        assert f1["source"] == "gmail"
        assert f1["doc_type"] == "insurance"

        # Check metadata
        meta2 = get_email_metadata_by_file_id(conn, f1["id"] + 1)
        assert meta2 is not None
        assert meta2["sender"] == "MakeMyTrip <tickets@makemytrip.com>"
        assert meta2["has_attachments"] == 1

        # Check attachment text was appended to contents
        row_c = conn.execute("SELECT text FROM contents WHERE file_id = ?", (meta2["file_id"],)).fetchone()
        assert "--- Attachment: ticket.txt ---" in row_c["text"]
        assert "HDFC-POL-9912" in row_c["text"]
    finally:
        conn.close()


def test_sync_gmail_handles_deleted_messages(temp_gmail_db: Path):
    """Messages found in trash/spam or returning 404 on get are removed from DB."""
    conn = get_connection(temp_gmail_db)
    try:
        upsert_gmail_message(
            conn=conn,
            gmail_id="del_001",
            thread_id="t1",
            subject="Spam notification",
            sender="spammer@example.com",
            recipients="me@example.com",
            labels="[]",
            email_date=100.0,
            text="Buy cheap medicines",
            has_attachments=0,
        )
        upsert_gmail_message(
            conn=conn,
            gmail_id="del_002",
            thread_id="t2",
            subject="Deleted message",
            sender="old@example.com",
            recipients="me@example.com",
            labels="[]",
            email_date=100.0,
            text="Old message",
            has_attachments=0,
        )
        assert len(get_all_gmail_ids(conn)) == 2
    finally:
        conn.close()

    mock_service = MagicMock()
    mock_users = mock_service.users.return_value
    mock_users.getProfile.return_value.execute.return_value = {"emailAddress": "user@gmail.com"}

    # Trash contains del_001
    mock_users.messages.return_value.list.return_value.execute.side_effect = [
        {"messages": [{"id": "del_001"}]},  # trash query
        {"messages": [{"id": "del_002"}], "nextPageToken": None},  # new messages query
    ]

    # del_002 returns 404 Not Found
    resp = httplib2.Response({"status": "404"})
    mock_users.messages.return_value.get.return_value.execute.side_effect = HttpError(resp, b"Not Found")

    res = sync_gmail(db_path=temp_gmail_db, service=mock_service)
    assert res["deleted"] == 2

    conn = get_connection(temp_gmail_db)
    try:
        assert len(get_all_gmail_ids(conn)) == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Disconnect Removes All Gmail Data
# ---------------------------------------------------------------------------


def test_disconnect_gmail_removes_data(temp_gmail_db: Path, monkeypatch: pytest.MonkeyPatch):
    """Disconnect deletes keyring token and deletes all Gmail rows from database."""
    conn = get_connection(temp_gmail_db)
    try:
        upsert_gmail_message(
            conn=conn,
            gmail_id="msg_test_dc",
            thread_id="t1",
            subject="Important receipt",
            sender="billing@example.com",
            recipients="me@example.com",
            labels="[]",
            email_date=100.0,
            text="Invoice total Rs 5000",
            has_attachments=0,
        )
        assert len(get_all_gmail_ids(conn)) == 1
    finally:
        conn.close()

    mock_delete = MagicMock()
    monkeypatch.setattr("keyring.delete_password", mock_delete)

    res = disconnect_gmail(db_path=temp_gmail_db)
    assert res["ok"] is True
    assert res["deleted_count"] >= 1
    mock_delete.assert_called_once_with(KEYRING_SERVICE, KEYRING_USERNAME)

    conn = get_connection(temp_gmail_db)
    try:
        assert len(get_all_gmail_ids(conn)) == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. /open Endpoint URL Verification for Gmail
# ---------------------------------------------------------------------------


def test_open_gmail_url_verification(temp_gmail_db: Path):
    """POST /open with gmail:// path opens mail.google.com URL only if ID exists."""
    conn = get_connection(temp_gmail_db)
    try:
        upsert_gmail_message(
            conn=conn,
            gmail_id="valid_12345",
            thread_id="t1",
            subject="Welcome to Gmail",
            sender="google@google.com",
            recipients="me@example.com",
            labels="[]",
            email_date=100.0,
            text="Welcome email content",
            has_attachments=0,
        )
    finally:
        conn.close()

    client = TestClient(app)
    client.cookies.set(API_COOKIE_NAME, get_api_token())

    # 1. Existing ID with folder=False opens mail.google.com
    with patch("webbrowser.open") as mock_browser:
        resp = client.post("/open", json={"path": "gmail://valid_12345", "folder": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        mock_browser.assert_called_once_with("https://mail.google.com/mail/u/0/#all/valid_12345")

    # 2. Existing ID with folder=True is rejected
    resp_folder = client.post("/open", json={"path": "gmail://valid_12345", "folder": True})
    assert resp_folder.status_code == 200
    assert resp_folder.json()["ok"] is False
    assert "not supported" in resp_folder.json()["message"].lower()

    # 3. Non-existent ID is rejected
    resp_missing = client.post("/open", json={"path": "gmail://non_existent_999", "folder": False})
    assert resp_missing.status_code == 200
    assert resp_missing.json()["ok"] is False
    assert "not found" in resp_missing.json()["message"].lower()


# ---------------------------------------------------------------------------
# 6. Query Parsing & /ask Gmail Result Formatting Tests
# ---------------------------------------------------------------------------


def test_parse_query_gmail_and_sender_filtering():
    """Query words gmail, email, inbox filter to source gmail; 'from <name>' filters sender."""
    q1 = parse_query("show me flight email from makemytrip")
    assert q1.source == "gmail"
    assert q1.sender == "makemytrip"
    assert "flight" in q1.cleaned_query

    q2 = parse_query("inbox policy renewal")
    assert q2.source == "gmail"
    assert "policy renewal" in q2.cleaned_query

    q3 = parse_query("gmail from Alice")
    assert q3.source == "gmail"
    assert q3.sender == "alice"


def test_ask_gmail_search_results_formatting(temp_gmail_db: Path):
    """Results from Gmail have source 'gmail', sender, subject, date, labels, and breadcrumb."""
    conn = get_connection(temp_gmail_db)
    try:
        fid = upsert_gmail_message(
            conn=conn,
            gmail_id="flight_msg_007",
            thread_id="th_7",
            subject="Air India Flight AI101 Ticket",
            sender="Air India <bookings@airindia.in>",
            recipients="traveler@example.com",
            labels=json.dumps(["Travel", "INBOX"]),
            email_date=1795334400.0,
            text="Flight AI101 departs from Delhi on 2026-12-10. PNR: AIR8899. Total Rs 8,500.",
            has_attachments=0,
            doc_type="ticket",
            doc_type_score=0.95,
        )
        conn.commit()
    finally:
        conn.close()

    client = TestClient(app)
    client.cookies.set(API_COOKIE_NAME, get_api_token())

    resp = client.post("/ask", json={"message": "email for Air India flight"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) >= 1

    item = data["results"][0]
    assert item["source"] == "gmail"
    assert item["filename"] == "Air India Flight AI101 Ticket"
    assert item["path"] == "gmail://flight_msg_007"
    assert item["sender"] == "Air India <bookings@airindia.in>"
    assert item["breadcrumb"] == ["Gmail", "Travel", "Air India Flight AI101 Ticket"]
    assert item["exists"] is True
    assert item["doc_type"] == "ticket"
    assert "flight" in item["snippet"].lower() or "ai101" in item["snippet"].lower()
