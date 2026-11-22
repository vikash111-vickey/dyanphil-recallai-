"""Tests for resilient error handling: embedding model failure fallback and database busy/missing."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Generator
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection, init_db
from app.main import API_COOKIE_NAME, app, get_api_token


@pytest.fixture
def temp_err_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Provide isolated database for error handling tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "test_err.db"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "db_path", db_file)
    init_db()
    yield db_file


def test_ask_embedding_model_failure_fallback_to_keyword(temp_err_db: Path):
    """If the embedding model is missing or fails to load, /ask must fall back to keyword search with zero technical messages."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO files (path, filename, ext, size, created_at, modified_at, indexed_at, status, doc_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("D:\\docs\\quarterly_report.pdf", "quarterly_report.pdf", ".pdf", 2000, 100, 200, 200, "indexed", "financial"),
        )
        fid = cur.lastrowid
        conn.execute("INSERT INTO contents (file_id, text) VALUES (?, ?)", (fid, "Financial earnings and quarterly report summary"))
        conn.commit()
    finally:
        conn.close()

    client = TestClient(app)
    client.cookies.set(API_COOKIE_NAME, get_api_token())

    # Simulate FastEmbed / ONNX failure
    with patch("app.search.hybrid.get_embedder", side_effect=RuntimeError("ONNX Runtime binary missing")):
        resp = client.post("/ask", json={"message": "quarterly report"})
        assert resp.status_code == 200
        data = resp.json()

        # Say nothing technical to the user
        msg = data["message"].lower()
        assert "onnx" not in msg
        assert "runtimeerror" not in msg
        assert "traceback" not in msg
        assert "fastembed" not in msg

        # Results were successfully retrieved via keyword search fallback
        assert len(data["results"]) >= 1
        assert data["results"][0]["filename"] == "quarterly_report.pdf"


def test_ask_database_locked_returns_friendly_message(temp_err_db: Path):
    """If the database is locked, /ask returns a friendly message."""
    client = TestClient(app)
    client.cookies.set(API_COOKIE_NAME, get_api_token())

    with patch("app.api.routes.get_connection", side_effect=sqlite3.OperationalError("database is locked")):
        resp = client.post("/ask", json={"message": "any document"})
        assert resp.status_code == 200
        data = resp.json()
        assert "busy" in data["message"].lower() or "unavailable" in data["message"].lower()
        assert data["results"] == []


def test_ask_database_missing_returns_friendly_message(temp_err_db: Path):
    """If the database file is missing or unopenable, /ask returns a friendly message."""
    client = TestClient(app)
    client.cookies.set(API_COOKIE_NAME, get_api_token())

    with patch("app.api.routes.get_connection", side_effect=FileNotFoundError("Database file not found")):
        resp = client.post("/ask", json={"message": "any document"})
        assert resp.status_code == 200
        data = resp.json()
        assert "unavailable" in data["message"].lower() or "busy" in data["message"].lower()
        assert data["results"] == []
