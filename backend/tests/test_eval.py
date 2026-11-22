"""Tests for the evaluation CLI command."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Generator
import pytest

from app.cli import handle_eval
from app.config import settings
from app.db import get_connection, init_db


@pytest.fixture
def temp_eval_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Provide isolated database for eval testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "test_eval.db"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "db_path", db_file)
    init_db()
    yield db_file


def test_eval_cli_runs_and_writes_report(temp_eval_db: Path):
    """Test handle_eval runs, computes metrics, and writes data/eval_report.txt."""
    conn = get_connection()
    try:
        # Seed several indexed files
        files_to_seed = [
            ("D:\\my certif\\nasa.pdf", "nasa.pdf", ".pdf", "certificate"),
            ("D:\\docs\\passport.pdf", "passport.pdf", ".pdf", "id_document"),
            ("D:\\finance\\electric_bill.pdf", "electric_bill.pdf", ".pdf", "financial"),
            ("D:\\resumes\\jane_doe_cv.docx", "jane_doe_cv.docx", ".docx", "resume"),
        ]
        for path, fname, ext, dtype in files_to_seed:
            cur = conn.execute(
                """
                INSERT INTO files (path, filename, ext, size, created_at, modified_at, indexed_at, status, doc_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (path, fname, ext, 1000, 100, 200, 200, "indexed", dtype),
            )
            fid = cur.lastrowid
            conn.execute("INSERT INTO contents (file_id, text) VALUES (?, ?)", (fid, f"Sample text for {fname}"))
        conn.commit()
    finally:
        conn.close()

    args = argparse.Namespace()
    rc = handle_eval(args)
    assert rc == 0

    report_file = settings.data_dir / "eval_report.txt"
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "=== Dyanphil Search Evaluation Report ===" in content
    assert "Recall@5:" in content
    assert "MRR:" in content
