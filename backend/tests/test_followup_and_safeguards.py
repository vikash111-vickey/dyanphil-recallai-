"""Tests for follow-up session commands, emergency urgent-first behavior, and answer safeguards."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db import (
    get_connection,
    init_db,
    pin_file_to_vault,
    upsert_file_record,
)
from app.main import app
from app.search.followup import reset_sessions
from app.vault.service import reset_vault_state


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path: Path):
    db_file = tmp_path / "test_followup.db"
    init_db(db_file)
    reset_vault_state()
    reset_sessions()

    with patch("app.api.routes.get_connection", side_effect=lambda: get_connection(db_file)), \
         patch("app.db.get_connection", side_effect=lambda: get_connection(db_file)), \
         patch("app.search.facts_answer.hybrid_search") as mock_hs, \
         patch("app.api.routes.hybrid_search") as mock_api_hs:

        # Default hybrid_search mock
        def fake_hybrid(conn, query, mode="hybrid", limit=15, **kwargs):
            q_pat = f"%{query}%"
            cur = conn.execute(
                """
                SELECT f.id, f.path, f.filename, f.modified_at, f.doc_type
                FROM files f
                LEFT JOIN contents c ON c.file_id = f.id
                WHERE f.filename LIKE ? OR f.path LIKE ? OR c.text LIKE ?
                """,
                (q_pat, q_pat, q_pat),
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r["id"],
                    "path": r["path"],
                    "filename": r["filename"],
                    "modified_at": r["modified_at"],
                    "doc_type": r["doc_type"] or "other",
                    "match_type": "both",
                    "snippet": f"Found text in {r['filename']}",
                }
                for r in rows
            ]

        mock_hs.side_effect = fake_hybrid
        mock_api_hs.side_effect = fake_hybrid

        yield db_file

    reset_vault_state()
    reset_sessions()


def test_follow_up_open_commands_english_and_hinglish(tmp_path: Path):
    db_file = tmp_path / "test_followup.db"
    conn = get_connection(db_file)

    p1 = str(tmp_path / "tax_doc1.pdf")
    p2 = str(tmp_path / "tax_doc2.pdf")
    p3 = str(tmp_path / "tax_doc3.pdf")

    # Create dummy files on disk so safe_file_exists passes
    Path(p1).write_text("doc 1")
    Path(p2).write_text("doc 2")
    Path(p3).write_text("doc 3")

    fid1 = upsert_file_record(conn, p1, "tax_doc1.pdf", ".pdf", 100, 1000, 1000, "h1", 1000, "indexed", None, "tax document 1")
    fid2 = upsert_file_record(conn, p2, "tax_doc2.pdf", ".pdf", 200, 2000, 2000, "h2", 2000, "indexed", None, "tax document 2")
    fid3 = upsert_file_record(conn, p3, "tax_doc3.pdf", ".pdf", 300, 3000, 3000, "h3", 3000, "indexed", None, "tax document 3")
    conn.commit()
    conn.close()

    client = TestClient(app)
    sess_id = "sess_test_1"

    # Initial query
    res = client.post("/ask", json={"message": "tax", "session_id": sess_id})
    assert res.status_code == 200
    assert len(res.json()["results"]) >= 3

    # Mock perform_open
    with patch("app.api.routes.perform_open", return_value=(True, "File opened successfully")) as mock_open:
        # 1. "open it" -> opens index 0 (tax_doc1.pdf)
        res_open = client.post("/ask", json={"message": "open it", "session_id": sess_id})
        assert res_open.status_code == 200
        mock_open.assert_called_with(p1, False)
        assert "tax_doc1.pdf" in res_open.json()["message"]

        # 2. "dusra kholo" -> opens index 1 (tax_doc2.pdf)
        res_2 = client.post("/ask", json={"message": "dusra kholo", "session_id": sess_id})
        assert res_2.status_code == 200
        mock_open.assert_called_with(p2, False)
        assert "tax_doc2.pdf" in res_2.json()["message"]

        # 3. "open the third one" -> opens index 2 (tax_doc3.pdf)
        res_3 = client.post("/ask", json={"message": "open the third one", "session_id": sess_id})
        assert res_3.status_code == 200
        mock_open.assert_called_with(p3, False)
        assert "tax_doc3.pdf" in res_3.json()["message"]

        # 4. "folder kholo" -> opens folder with folder=True
        res_f = client.post("/ask", json={"message": "folder kholo", "session_id": sess_id})
        assert res_f.status_code == 200
        mock_open.assert_called_with(p1, True)
        assert "folder" in res_f.json()["message"].lower()


def test_follow_up_older_and_newer(tmp_path: Path):
    db_file = tmp_path / "test_followup.db"
    conn = get_connection(db_file)

    p_old = str(tmp_path / "statement_old.pdf")
    p_new = str(tmp_path / "statement_new.pdf")
    Path(p_old).write_text("old")
    Path(p_new).write_text("new")

    upsert_file_record(conn, p_old, "statement_old.pdf", ".pdf", 100, 1000, 1000.0, "h1", 1000, "indexed", None, "statement")
    upsert_file_record(conn, p_new, "statement_new.pdf", ".pdf", 100, 2000, 5000.0, "h2", 2000, "indexed", None, "statement")
    conn.commit()
    conn.close()

    client = TestClient(app)
    sess = "sess_time_test"
    res_init = client.post("/ask", json={"message": "statement", "session_id": sess})
    assert res_init.status_code == 200
    assert len(res_init.json()["results"]) >= 2

    with patch("app.api.routes.perform_open", return_value=(True, "File opened successfully")) as mock_open:
        # "the older one"
        res_old = client.post("/ask", json={"message": "the older one", "session_id": sess})
        assert res_old.status_code == 200
        mock_open.assert_called_with(p_old, False)
        assert "statement_old.pdf" in res_old.json()["message"]

        # "naya wala"
        res_new = client.post("/ask", json={"message": "naya wala", "session_id": sess})
        assert res_new.status_code == 200
        mock_open.assert_called_with(p_new, False)
        assert "statement_new.pdf" in res_new.json()["message"]


def test_follow_up_show_more_and_empty_session():
    client = TestClient(app)

    # Empty session follow-up
    res = client.post("/ask", json={"message": "open it", "session_id": "fresh_empty_sess"})
    assert res.status_code == 200
    assert "no recent search results" in res.json()["message"].lower() or "no previous results" in res.json()["message"].lower()

    # "show more" in empty session
    res_more = client.post("/ask", json={"message": "aur dikhao", "session_id": "fresh_empty_sess"})
    assert res_more.status_code == 200
    assert "no additional results" in res_more.json()["message"].lower() or "all the matching" in res_more.json()["message"].lower()


def test_emergency_vault_urgent_first(tmp_path: Path):
    db_file = tmp_path / "test_followup.db"
    conn = get_connection(db_file)

    p_pass = str(tmp_path / "passport.pdf")
    p_other = str(tmp_path / "other_cert.pdf")
    Path(p_pass).write_text("passport text")
    Path(p_other).write_text("other text")

    fid1 = upsert_file_record(conn, p_pass, "passport.pdf", ".pdf", 100, 1000, 1000, "h1", 1000, "indexed", "passport id")
    fid2 = upsert_file_record(conn, p_other, "other_cert.pdf", ".pdf", 100, 2000, 2000, "h2", 2000, "indexed", "certificate")
    conn.execute("UPDATE files SET doc_type = 'id_document' WHERE id = ?", (fid1,))
    conn.commit()

    # Pin passport to emergency vault
    pin_file_to_vault(conn, fid1, label="Emergency Passport")
    conn.close()

    client = TestClient(app)

    # Urgent query matching passport: "urgent emergency need my passport right now"
    res = client.post("/ask", json={"message": "urgent emergency need my passport right now!"})
    assert res.status_code == 200
    data = res.json()
    assert data["urgency"] == "high"

    # Pinned file must be first
    assert len(data["results"]) >= 1
    assert data["results"][0]["filename"] == "passport.pdf"

    # Reply message mentions prioritizing emergency vault
    assert "emergency vault" in data["message"].lower()

    # Pinned result must be a standard SearchResultItem (no secret vault keys leaked)
    item = data["results"][0]
    assert "filename" in item
    assert "path" in item
    assert "doc_type" in item
    assert "pin" not in item
    assert "token" not in item


def test_safeguards_fact_citation_and_never_guess(tmp_path: Path):
    db_file = tmp_path / "test_followup.db"
    conn = get_connection(db_file)

    p_ins = str(tmp_path / "insurance_policy.pdf")
    Path(p_ins).write_text("health insurance policy")
    fid = upsert_file_record(conn, p_ins, "insurance_policy.pdf", ".pdf", 500, 1000, 1000, "h1", 1000, "indexed", "health insurance policy")
    conn.execute("UPDATE files SET doc_type = 'insurance' WHERE id = ?", (fid,))

    # Insert a fact
    conn.execute(
        "INSERT INTO facts (file_id, kind, label, value, value_date) VALUES (?, ?, ?, ?, ?)",
        (fid, "expiry", "Expiry Date", "14 Aug 2027", "2027-08-14"),
    )
    conn.commit()
    conn.close()

    client = TestClient(app)

    # 1. Fact found: must cite the source filename and path
    res = client.post("/ask", json={"message": "when does my insurance expire"})
    assert res.status_code == 200
    data = res.json()
    assert "14 Aug 2027" in data["message"]
    assert "insurance_policy.pdf" in data["message"]
    assert len(data["results"]) == 1
    assert data["results"][0]["filename"] == "insurance_policy.pdf"
    assert data["results"][0]["path"] == p_ins

    # 2. Fact intent detected, but no fact exists in database: must say so and never guess
    res_nofact = client.post("/ask", json={"message": "what is my visa number"})
    assert res_nofact.status_code == 200
    data_nofact = res_nofact.json()
    assert "couldn't find" in data_nofact["message"].lower()
    assert data_nofact["results"] == []  # Never hallucinate random results as facts
