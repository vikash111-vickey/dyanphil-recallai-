"""Tests for the API layer: query understanding, tone detection, composer, /ask and /open."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection, init_db, upsert_file_record
from app.main import app
from app.search.composer import compose_reply
from app.search.query import compute_date_threshold, parse_query
from app.search.tone import detect_tone

client = TestClient(app)


# --- 1. Query Understanding Tests ---


def test_query_cleaning_filler_words():
    """Verify filler words and phrases in English and Hinglish are removed."""
    q1 = parse_query("show me where is my passport please")
    assert q1.cleaned_query == "passport"

    q2 = parse_query("mera budget dhundo")
    assert q2.cleaned_query == "budget"

    q3 = parse_query("where is tax document chahiye")
    assert q3.cleaned_query == "tax document"

    q4 = parse_query("can you find meeting notes dikhao")
    assert "meeting" in q4.cleaned_query


def test_query_cleaning_file_types():
    """Verify file type keywords map to extensions and are extracted."""
    q_pdf = parse_query("find resume pdf")
    assert q_pdf.file_types == [".pdf"]
    assert q_pdf.cleaned_query == "resume"

    q_sheet = parse_query("show me budget sheet")
    assert ".xlsx" in q_sheet.file_types
    assert ".csv" in q_sheet.file_types
    assert q_sheet.cleaned_query == "budget"

    q_notes = parse_query("financial notes")
    assert ".txt" in q_notes.file_types
    assert ".md" in q_notes.file_types
    assert q_notes.cleaned_query == "financial"

    q_img = parse_query("id photo")
    assert ".png" in q_img.file_types
    assert q_img.cleaned_query == "id"


def test_query_cleaning_date_filters():
    """Verify relative date words create appropriate threshold timestamps."""
    fixed_now = datetime(2026, 11, 21, 12, 0, 0)

    q_today = parse_query("expenses today", now=fixed_now)
    assert q_today.min_modified is not None
    assert q_today.cleaned_query == "expenses"
    expected_today = fixed_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    assert abs(q_today.min_modified - expected_today) < 1.0

    q_yesterday = parse_query("invoices yesterday", now=fixed_now)
    assert q_yesterday.min_modified is not None
    assert q_yesterday.cleaned_query == "invoices"

    q_week = parse_query("reports last week", now=fixed_now)
    assert q_week.min_modified is not None
    assert q_week.cleaned_query == "reports"


# --- 2. Tone Detection Tests ---


def test_tone_detection_urgent():
    """Verify urgent signals, keywords, and high urgency."""
    res1 = detect_tone("I need the passport asap urgent!")
    assert res1["tone"] == "urgent"
    assert res1["urgency"] == "high"

    res2 = detect_tone("jaldi turant send invoice")
    assert res2["tone"] == "urgent"

    res3 = detect_tone("WHERE IS MY DOCUMENT!!!")
    assert res3["urgency"] == "high"


def test_tone_detection_stressed():
    """Verify stressed tone and medium/high urgency."""
    res = detect_tone("help please I lost my insurance card and am worried")
    assert res["tone"] == "stressed"
    assert res["urgency"] in ("medium", "high")


def test_tone_detection_frustrated():
    """Verify frustrated tone when files cannot be found or things are not working."""
    res1 = detect_tone("I can't find my medical receipt, this is not working")
    assert res1["tone"] == "frustrated"
    assert res1["urgency"] == "medium"

    res2 = detect_tone("yaar file kaha chala gaya nahi mil raha")
    assert res2["tone"] == "frustrated"


def test_tone_detection_casual():
    """Verify casual greetings and low urgency."""
    res = detect_tone("hey bro just checking the budget sheet")
    assert res["tone"] == "casual"
    assert res["urgency"] == "low"


def test_tone_detection_neutral():
    """Verify neutral fallback tone."""
    res = detect_tone("quarterly tax document 2025")
    assert res["tone"] == "neutral"
    assert res["urgency"] == "low"


# --- 3. Composer Tests ---


def test_composer_urgent_and_stressed():
    """Urgent/stressed: one short calm sentence, result first."""
    results = [
        {"filename": "policy.pdf", "path": "D:/docs/Insurance/policy.pdf"}
    ]
    msg = compose_reply("urgent", results)
    assert msg == "Found policy.pdf in Insurance."

    msg_stressed = compose_reply("stressed", results)
    assert msg_stressed == "Found policy.pdf in Insurance."


def test_composer_frustrated():
    """Frustrated: empathy line first, then result."""
    results = [
        {"filename": "notes.md", "path": "D:/vault/notes.md"}
    ]
    msg = compose_reply("frustrated", results)
    assert msg.startswith("I understand this is frustrating.")
    assert "Found notes.md in vault." in msg


def test_composer_casual_and_neutral():
    """Casual/neutral: friendly, mentions a second match if present."""
    single = [{"filename": "budget.csv", "path": "D:/finances/budget.csv"}]
    msg_single = compose_reply("casual", single)
    assert msg_single == "Here is budget.csv from finances."

    double = [
        {"filename": "doc1.txt", "path": "D:/docs/doc1.txt"},
        {"filename": "doc2.txt", "path": "D:/archive/doc2.txt"},
    ]
    msg_double = compose_reply("neutral", double)
    assert "Here is doc1.txt from docs." in msg_double
    assert "I also found doc2.txt in archive" in msg_double


def test_composer_not_found():
    """Not found: gentle message offering to try similar words."""
    msg = compose_reply("neutral", [])
    assert "couldn't find any matching files" in msg


# --- 4. API /ask and /open Tests ---


@pytest.fixture
def populated_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up an isolated database with sample files for API tests."""
    temp_data_dir = tmp_path / "data"
    temp_data_dir.mkdir(parents=True, exist_ok=True)
    temp_db = temp_data_dir / "recall.db"
    monkeypatch.setattr(settings, "data_dir", temp_data_dir)
    monkeypatch.setattr(settings, "db_path", temp_db)
    init_db(temp_db)

    # Create dummy files on disk
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    f1 = docs_dir / "passport_scan.pdf"
    f1.write_text("Official government passport identity card verification document.", encoding="utf-8")

    f2 = docs_dir / "tax_summary.xlsx"
    f2.write_text("Tax summary report calculations for 2025.", encoding="utf-8")

    spaced_dir = tmp_path / "My Certifications" / "NASA Course"
    spaced_dir.mkdir(parents=True, exist_ok=True)
    f3 = spaced_dir / "NASA Achievement Certificate 2026.pdf"
    f3.write_text("NASA Certificate of achievement in orbital astrophysics.", encoding="utf-8")

    conn = get_connection(temp_db)
    try:
        upsert_file_record(
            conn,
            path=str(f1.resolve()),
            filename="passport_scan.pdf",
            ext=".pdf",
            size=100,
            created_at=1000.0,
            modified_at=1000.0,
            content_hash="hash_p",
            indexed_at=1000.0,
            status="indexed",
            text="Official government passport identity card verification document.",
        )
        upsert_file_record(
            conn,
            path=str(f2.resolve()),
            filename="tax_summary.xlsx",
            ext=".xlsx",
            size=200,
            created_at=1000.0,
            modified_at=1000.0,
            content_hash="hash_t",
            indexed_at=1000.0,
            status="indexed",
            text="Tax summary report calculations for 2025.",
        )
        upsert_file_record(
            conn,
            path=str(f3.resolve()),
            filename="NASA Achievement Certificate 2026.pdf",
            ext=".pdf",
            size=300,
            created_at=1000.0,
            modified_at=1000.0,
            content_hash="hash_nasa",
            indexed_at=1000.0,
            status="indexed",
            text="NASA Certificate of achievement in orbital astrophysics.",
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "db": temp_db,
        "f1": f1.resolve(),
        "f2": f2.resolve(),
        "f3": f3.resolve(),
    }


def test_api_ask_endpoint(populated_test_db):
    """Test POST /ask with natural language query."""
    response = client.post("/ask", json={"message": "where is my passport please"})
    assert response.status_code == 200
    data = response.json()

    assert "tone" in data
    assert "urgency" in data
    assert "message" in data
    assert "results" in data
    assert len(data["results"]) >= 1

    first = data["results"][0]
    assert first["filename"] == "passport_scan.pdf"
    assert first["source"] == "local file"
    assert isinstance(first["breadcrumb"], list)
    assert first["exists"] is True
    assert "match_type" in first
    assert "modified" in first


def test_api_ask_empty():
    """Test POST /ask with empty message returns empty results with gentle message."""
    response = client.post("/ask", json={"message": "   "})
    assert response.status_code == 200
    data = response.json()
    assert data["results"] == []
    assert "couldn't find" in data["message"]


def test_api_open_file(populated_test_db, monkeypatch):
    """Test POST /open opens a registered file."""
    f1_path = str(populated_test_db["f1"])

    mock_startfile = MagicMock()
    monkeypatch.setattr(os, "startfile", mock_startfile, raising=False)

    response = client.post("/open", json={"path": f1_path, "folder": False})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "File opened successfully" in data["message"]
    mock_startfile.assert_called_once_with(f1_path)


def test_api_open_folder(populated_test_db):
    """Test POST /open opens folder with file selected."""
    f1_path = str(populated_test_db["f1"])

    with patch("subprocess.Popen") as mock_sub:
        response = client.post("/open", json={"path": f1_path, "folder": True})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "Folder opened successfully" in data["message"]
        mock_sub.assert_called_once()
        cmd_arg = mock_sub.call_args[0][0]
        assert "explorer.exe" in cmd_arg
        assert f'/select,"{f1_path}"' in cmd_arg


def test_api_open_path_with_spaces_and_backslashes(populated_test_db, monkeypatch):
    """Test POST /open with a path containing spaces and backslashes, plus slashes/casing normalisation."""
    f3_path = str(populated_test_db["f3"])
    assert " " in f3_path  # Contains spaces

    mock_startfile = MagicMock()
    monkeypatch.setattr(os, "startfile", mock_startfile, raising=False)

    # 1. Open file with exact Windows backslashes and spaces
    res1 = client.post("/open", json={"path": f3_path, "folder": False})
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["ok"] is True
    assert "File opened successfully" in data1["message"]

    # 2. Open folder with spaces using explorer argument
    with patch("subprocess.Popen") as mock_sub:
        res2 = client.post("/open", json={"path": f3_path, "folder": True})
        assert res2.status_code == 200
        assert res2.json()["ok"] is True
        mock_sub.assert_called_once()
        cmd_arg = mock_sub.call_args[0][0]
        assert "explorer.exe" in cmd_arg
        assert f'/select,"{f3_path}"' in cmd_arg

    # 3. Path normalisation: test with forward slashes
    forward_slash_path = f3_path.replace("\\", "/")
    res3 = client.post("/open", json={"path": forward_slash_path, "folder": False})
    assert res3.status_code == 200
    assert res3.json()["ok"] is True

    # 4. Path normalisation: test with case variation (e.g. lowercase)
    lower_path = f3_path.lower()
    res4 = client.post("/open", json={"path": lower_path, "folder": False})
    assert res4.status_code == 200
    assert res4.json()["ok"] is True


def test_api_open_path_not_in_db(populated_test_db):
    """Test POST /open returns ok=False if path is not in database."""
    fake_path = r"D:\nonexistent\fake file with spaces.txt"
    response = client.post("/open", json={"path": fake_path, "folder": False})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "Path not found" in data["message"]


def test_api_open_file_missing_on_disk(populated_test_db):
    """Test POST /open returns ok=False if file was deleted on disk."""
    f1 = populated_test_db["f1"]
    f1_path = str(f1)
    f1.unlink()  # Delete from disk

    response = client.post("/open", json={"path": f1_path, "folder": False})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "File no longer exists on disk" in data["message"]


def test_api_open_file_startfile_error(populated_test_db, monkeypatch):
    """Test POST /open returns ok=False when os.startfile raises an OS exception."""
    f1_path = str(populated_test_db["f1"])

    def raise_err(p):
        raise OSError("Access denied")

    monkeypatch.setattr(os, "startfile", raise_err, raising=False)

    response = client.post("/open", json={"path": f1_path, "folder": False})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "Failed to open file" in data["message"]
