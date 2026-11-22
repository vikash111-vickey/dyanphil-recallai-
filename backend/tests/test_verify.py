"""Tests for faithfulness verification of search answers."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Generator
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection, init_db, insert_facts_batch
from app.ingestion.facts import ExtractedFact
from app.main import API_COOKIE_NAME, app, get_api_token
from app.search.verify import verify_faithfulness


@pytest.fixture
def temp_verify_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Provide isolated database for verification testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "test_verify.db"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "db_path", db_file)
    init_db()
    yield db_file


def test_verified_fact_exact_match(temp_verify_db: Path):
    """When the claimed fact matches facts table, it is confirmed with filename and path."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO files (path, filename, ext, size, created_at, modified_at, indexed_at, status, doc_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("D:\\docs\\passport.pdf", "passport.pdf", ".pdf", 1000, 100, 200, 200, "indexed", "id_document"),
        )
        fid = cur.lastrowid
        conn.execute("INSERT INTO contents (file_id, text) VALUES (?, ?)", (fid, "Passport Number: A1234567"))
        insert_facts_batch(
            conn,
            [
                (fid, "id_number", "Passport Number", "A1234567", None, "Passport Number: A1234567"),
                (fid, "date", "Expires on", "2026-12-31", "2026-12-31", "Expires on 2026-12-31"),
            ],
        )
        conn.commit()

        results = [{
            "id": fid,
            "file_id": fid,
            "filename": "passport.pdf",
            "path": "D:\\docs\\passport.pdf",
        }]

        # Verified date
        msg_date = "Your passport expires on 2026-12-31."
        verified_date, ok_date = verify_faithfulness(conn, msg_date, results)
        assert ok_date is True
        assert "2026-12-31" in verified_date
        assert "passport.pdf" in verified_date
        assert "D:\\docs\\passport.pdf" in verified_date

        # Verified ID number
        msg_id = "Your passport number is A1234567."
        verified_id, ok_id = verify_faithfulness(conn, msg_id, results)
        assert ok_id is True
        assert "A1234567" in verified_id
        assert "passport.pdf" in verified_id
        assert "D:\\docs\\passport.pdf" in verified_id
    finally:
        conn.close()


def test_unconfirmed_fact_missing(temp_verify_db: Path):
    """When a claimed fact is missing, drop the claim, reply 'I couldn't confirm this from your files', keep matching files."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO files (path, filename, ext, size, created_at, modified_at, indexed_at, status, doc_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("D:\\docs\\insurance.pdf", "insurance.pdf", ".pdf", 1000, 100, 200, 200, "indexed", "insurance"),
        )
        fid = cur.lastrowid
        conn.execute("INSERT INTO contents (file_id, text) VALUES (?, ?)", (fid, "Health insurance policy"))
        conn.commit()

        results = [{
            "id": fid,
            "file_id": fid,
            "filename": "insurance.pdf",
            "path": "D:\\docs\\insurance.pdf",
        }]

        # Claim states 2029-05-15, which is nowhere in DB
        unverified_msg = "Your insurance expires on 2029-05-15."
        result_msg, ok = verify_faithfulness(conn, unverified_msg, results)

        assert ok is False
        assert "I couldn't confirm this from your files" in result_msg
        assert "2029-05-15" not in result_msg  # claim dropped
        assert "insurance.pdf" in result_msg   # includes filename
        assert "D:\\docs\\insurance.pdf" in result_msg  # includes path
    finally:
        conn.close()


def test_unconfirmed_fact_different(temp_verify_db: Path):
    """When a claimed fact is different from the stored fact, drop the claim and reply with safe message."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO files (path, filename, ext, size, created_at, modified_at, indexed_at, status, doc_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("D:\\docs\\ticket.pdf", "ticket.pdf", ".pdf", 1000, 100, 200, 200, "indexed", "ticket"),
        )
        fid = cur.lastrowid
        conn.execute("INSERT INTO contents (file_id, text) VALUES (?, ?)", (fid, "PNR: 9876543210"))
        insert_facts_batch(
            conn,
            [(fid, "id_number", "PNR", "9876543210", None, "PNR: 9876543210")],
        )
        conn.commit()

        results = [{
            "id": fid,
            "file_id": fid,
            "filename": "ticket.pdf",
            "path": "D:\\docs\\ticket.pdf",
        }]

        # Claim states different PNR: 1112223334
        fake_msg = "Your ticket number is 1112223334."
        result_msg, ok = verify_faithfulness(conn, fake_msg, results)

        assert ok is False
        assert "I couldn't confirm this from your files" in result_msg
        assert "1112223334" not in result_msg
        assert "ticket.pdf" in result_msg
        assert "D:\\docs\\ticket.pdf" in result_msg
    finally:
        conn.close()


def test_fact_confirmed_from_contents_text(temp_verify_db: Path):
    """If value is in contents text, it is confirmed even if absent in facts table."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO files (path, filename, ext, size, created_at, modified_at, indexed_at, status, doc_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("D:\\docs\\bill.pdf", "bill.pdf", ".pdf", 1000, 100, 200, 200, "indexed", "financial"),
        )
        fid = cur.lastrowid
        conn.execute("INSERT INTO contents (file_id, text) VALUES (?, ?)", (fid, "Total amount payable is Rs 4500"))
        conn.commit()

        results = [{
            "id": fid,
            "file_id": fid,
            "filename": "bill.pdf",
            "path": "D:\\docs\\bill.pdf",
        }]

        msg = "Your bill is Rs 4500."
        result_msg, ok = verify_faithfulness(conn, msg, results)
        assert ok is True
        assert "Rs 4500" in result_msg
        assert "bill.pdf" in result_msg
        assert "D:\\docs\\bill.pdf" in result_msg
    finally:
        conn.close()


def test_ask_endpoint_faithfulness_drop_claim(temp_verify_db: Path):
    """Verify /ask endpoint drops unconfirmable factual claims while returning matching files."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO files (path, filename, ext, size, created_at, modified_at, indexed_at, status, doc_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("D:\\docs\\passport.pdf", "passport.pdf", ".pdf", 1000, 100, 200, 200, "indexed", "id_document"),
        )
        fid = cur.lastrowid
        conn.execute("INSERT INTO contents (file_id, text) VALUES (?, ?)", (fid, "Passport Document without dates"))
        conn.commit()
    finally:
        conn.close()

    client = TestClient(app)
    client.cookies.set(API_COOKIE_NAME, get_api_token())

    # User asks "when does my passport expire"
    resp = client.post("/ask", json={"message": "when does my passport expire"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) >= 1
    assert "couldn't find an expiry" in data["message"].lower() or "couldn't confirm" in data["message"].lower()
