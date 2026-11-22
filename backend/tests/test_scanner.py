"""Tests for scanner, incremental indexing, error/permission handling, and CLI commands."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.cli import handle_list, handle_open, handle_search, handle_stats
from app.db import (
    get_connection,
    get_file_by_path,
    get_stats,
    init_db,
    search_fts,
)
from app.ingestion.scanner import scan_and_index


def test_skipped_folders(tmp_path: Path):
    """Test that all designated skip directories and hidden folders are excluded."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    skip_dirs = [
        ".venv",
        "node_modules",
        ".git",
        "__pycache__",
        "AppData",
        "Windows",
        "Program Files",
        "Program Files (x86)",
        "$Recycle.Bin",
        "System Volume Information",
        ".hidden_folder",
    ]
    for d in skip_dirs:
        sub = docs_dir / d
        sub.mkdir(parents=True)
        (sub / "ignore.txt").write_text(f"Ignore this from {d}", encoding="utf-8")

    valid_file = docs_dir / "valid.txt"
    valid_file.write_text("Valid searchable content", encoding="utf-8")

    stats = scan_and_index([docs_dir], db_path=db_file)
    assert stats.indexed == 1

    conn = get_connection(db_file)
    try:
        results = search_fts(conn, "Ignore")
        assert len(results) == 0

        valid_res = search_fts(conn, "searchable")
        assert len(valid_res) == 1
        assert valid_res[0]["filename"] == "valid.txt"
    finally:
        conn.close()


def test_size_limit(tmp_path: Path):
    """Test that files larger than 25 MB are skipped."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    # Create 26 MB sparse file (consumes virtually no disk on NTFS)
    large_file = docs_dir / "oversized.txt"
    with large_file.open("wb") as f:
        f.seek(26 * 1024 * 1024)
        f.write(b"E")

    stats = scan_and_index([docs_dir], db_path=db_file)
    assert stats.scanned == 1
    assert stats.skipped == 1
    assert stats.indexed == 0

    conn = get_connection(db_file)
    try:
        assert get_file_by_path(conn, str(large_file.resolve())) is None
    finally:
        conn.close()


def test_incremental_reindex(tmp_path: Path):
    """Test skipping unchanged files and re-indexing modified files."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    test_file = docs_dir / "article.txt"
    test_file.write_text("Initial text version", encoding="utf-8")

    # Run 1: new file
    s1 = scan_and_index([docs_dir], db_path=db_file)
    assert s1.indexed == 1
    assert s1.unchanged == 0

    # Run 2: unchanged
    s2 = scan_and_index([docs_dir], db_path=db_file)
    assert s2.indexed == 0
    assert s2.unchanged == 1

    # Modify content and timestamp
    time.sleep(0.05)
    test_file.write_text("Modified text version with new insights", encoding="utf-8")
    future_mtime = time.time() + 10.0
    import os
    os.utime(test_file, (future_mtime, future_mtime))

    # Run 3: modified file re-indexed
    s3 = scan_and_index([docs_dir], db_path=db_file)
    assert s3.indexed == 1
    assert s3.unchanged == 0

    conn = get_connection(db_file)
    try:
        res = search_fts(conn, "insights")
        assert len(res) == 1
    finally:
        conn.close()


def test_deleted_file_cleanup(tmp_path: Path):
    """Test cleanup of database rows when files are removed from scanned folders."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    keep_file = docs_dir / "keep.txt"
    keep_file.write_text("Permanent notes", encoding="utf-8")

    del_file = docs_dir / "temp.txt"
    del_file.write_text("Confidential ephemeral notes", encoding="utf-8")

    scan_and_index([docs_dir], db_path=db_file)

    conn = get_connection(db_file)
    try:
        assert len(search_fts(conn, "ephemeral")) == 1
    finally:
        conn.close()

    # Delete the temporary file
    del_file.unlink()

    scan_and_index([docs_dir], db_path=db_file)

    conn = get_connection(db_file)
    try:
        assert len(search_fts(conn, "ephemeral")) == 0
        assert get_file_by_path(conn, str(del_file.resolve())) is None
        assert get_file_by_path(conn, str(keep_file.resolve())) is not None
    finally:
        conn.close()


def test_corrupt_file_handling(tmp_path: Path):
    """Test that a corrupt file does not crash the run and records status 'error'."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    corrupt_file = docs_dir / "damaged.docx"
    corrupt_file.write_bytes(b"INVALID_CORRUPT_BYTES_NOT_ZIP")

    stats = scan_and_index([docs_dir], db_path=db_file)
    assert stats.errors == 1

    conn = get_connection(db_file)
    try:
        rec = get_file_by_path(conn, str(corrupt_file.resolve()))
        assert rec is not None
        assert rec["status"] == "error"
        assert rec["error"] is not None
    finally:
        conn.close()


def test_permission_denied_mock(tmp_path: Path):
    """Test that permission-denied directories or files are skipped and counted."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    restricted_dir = docs_dir / "locked_folder"
    restricted_dir.mkdir()
    (restricted_dir / "secret.txt").write_text("Secret", encoding="utf-8")

    db_file = tmp_path / "test.db"

    orig_iterdir = Path.iterdir

    def mock_iterdir(self):
        if self.name == "locked_folder":
            raise PermissionError("Access is denied")
        return orig_iterdir(self)

    with patch.object(Path, "iterdir", side_effect=mock_iterdir, autospec=True):
        stats = scan_and_index([docs_dir], db_path=db_file)
        assert stats.permission_denied >= 1


def test_search_returning_correct_path_and_open_cli(tmp_path: Path, monkeypatch):
    """Test search result correctness and CLI open command validation."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    f1 = docs_dir / "quantum.txt"
    f1.write_text("Quantum entanglement and superposition experiments.", encoding="utf-8")

    f2 = docs_dir / "culinary.md"
    f2.write_text("Culinary gastronomy fermentation guide.", encoding="utf-8")

    scan_and_index([docs_dir], db_path=db_file)

    conn = get_connection(db_file)
    try:
        matches = search_fts(conn, "entanglement")
        assert len(matches) == 1
        assert matches[0]["path"] == str(f1.resolve())
        assert matches[0]["filename"] == "quantum.txt"
        assert ">>>entanglement<<<" in matches[0]["snippet"]
    finally:
        conn.close()

    # Test CLI search and last_search caching
    search_cache_file = tmp_path / "last_search.json"
    import app.cli
    monkeypatch.setattr(app.cli, "LAST_SEARCH_FILE", search_cache_file)
    from app.config import settings
    monkeypatch.setattr(settings, "db_path", db_file)

    import argparse
    search_args = argparse.Namespace(words="entanglement", limit=10)
    assert app.cli.handle_search(search_args) == 0
    assert search_cache_file.exists()

    cached_data = json.loads(search_cache_file.read_text(encoding="utf-8"))
    assert len(cached_data) == 1
    assert cached_data[0]["path"] == str(f1.resolve())

    # Test CLI open with os.startfile mock
    mock_startfile = MagicMock()
    monkeypatch.setattr(os, "startfile", mock_startfile, raising=False)

    open_args = argparse.Namespace(number=1, folder=False)
    assert app.cli.handle_open(open_args) == 0
    mock_startfile.assert_called_once_with(str(f1.resolve()))

    # Test CLI open with non-existent file
    f1.unlink()
    assert app.cli.handle_open(open_args) == 1


def test_cloud_only_files_skipped(tmp_path: Path):
    """Test that Windows cloud-only/dehydrated files are skipped and counted."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    cloud_recall_data = docs_dir / "cloud_recall_data.txt"
    cloud_recall_data.write_text("Should never be read", encoding="utf-8")

    cloud_recall_open = docs_dir / "cloud_recall_open.txt"
    cloud_recall_open.write_text("Should never be read", encoding="utf-8")

    cloud_offline = docs_dir / "cloud_offline.txt"
    cloud_offline.write_text("Should never be read", encoding="utf-8")

    local_file = docs_dir / "local.txt"
    local_file.write_text("Local text content", encoding="utf-8")

    orig_stat = Path.stat

    def mock_stat(self, **kwargs):
        real_stat = orig_stat(self, **kwargs)
        attrs = 0
        if self.name == "cloud_recall_data.txt":
            attrs = 0x400000
        elif self.name == "cloud_recall_open.txt":
            attrs = 0x40000
        elif self.name == "cloud_offline.txt":
            attrs = 0x1000

        class StatProxy:
            def __init__(self, stat_obj, attr_val):
                self._s = stat_obj
                self.st_file_attributes = attr_val
                self.st_size = stat_obj.st_size
                self.st_mtime = stat_obj.st_mtime
                self.st_ctime = stat_obj.st_ctime

            def __getattr__(self, name):
                return getattr(self._s, name)

        return StatProxy(real_stat, attrs)

    with patch.object(Path, "stat", side_effect=mock_stat, autospec=True):
        stats = scan_and_index([docs_dir], db_path=db_file)
        assert stats.cloud_only == 3
        assert stats.indexed == 1

    conn = get_connection(db_file)
    try:
        assert get_file_by_path(conn, str(local_file.resolve())) is not None
        assert get_file_by_path(conn, str(cloud_recall_data.resolve())) is None
        assert get_file_by_path(conn, str(cloud_recall_open.resolve())) is None
        assert get_file_by_path(conn, str(cloud_offline.resolve())) is None
    finally:
        conn.close()


def test_cli_list_command(tmp_path: Path, monkeypatch, capsys):
    """Test python -m app.cli list --status error|needs_ocr|indexed [--limit 50]."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    f_ok = docs_dir / "good.txt"
    f_ok.write_text("Good content", encoding="utf-8")

    f_err = docs_dir / "bad.docx"
    f_err.write_bytes(b"CORRUPT_BYTES")

    f_ocr = docs_dir / "blank.pdf"
    import pypdf
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with f_ocr.open("wb") as f:
        writer.write(f)

    scan_and_index([docs_dir], db_path=db_file)

    from app.config import settings
    monkeypatch.setattr(settings, "db_path", db_file)
    import app.cli
    import argparse

    # Test list --status indexed
    args_indexed = argparse.Namespace(status="indexed", limit=50)
    capsys.readouterr()
    assert app.cli.handle_list(args_indexed) == 0
    out_indexed = capsys.readouterr().out
    assert str(f_ok.resolve()) in out_indexed

    # Test list --status error
    args_err = argparse.Namespace(status="error", limit=50)
    assert app.cli.handle_list(args_err) == 0
    out_err = capsys.readouterr().out
    assert str(f_err.resolve()) in out_err
    assert "Error:" in out_err

    # Test list --status needs_ocr
    args_ocr = argparse.Namespace(status="needs_ocr", limit=50)
    assert app.cli.handle_list(args_ocr) == 0
    out_ocr = capsys.readouterr().out
    assert str(f_ocr.resolve()) in out_ocr


def test_ignore_temporary_and_system_files(tmp_path: Path):
    """Test that files starting with ~$, .~lock, ending in .tmp, Thumbs.db, desktop.ini, .DS_Store are skipped."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    # Files matching ignore rules
    (docs_dir / "~$document.docx").write_bytes(b"temp office lock")
    (docs_dir / ".~lock.file.docx#").write_bytes(b"libreoffice lock")
    (docs_dir / "scratch.tmp").write_text("temporary data", encoding="utf-8")
    (docs_dir / "UPPERCASE.TMP").write_text("temporary data", encoding="utf-8")
    (docs_dir / "Thumbs.db").write_bytes(b"binary cache")
    (docs_dir / "desktop.ini").write_text("[ShellClassInfo]", encoding="utf-8")
    (docs_dir / ".DS_Store").write_bytes(b"mac metadata")

    # One valid file
    valid_file = docs_dir / "valid_document.txt"
    valid_file.write_text("Keep and index this document", encoding="utf-8")

    stats = scan_and_index([docs_dir], db_path=db_file)
    assert stats.indexed == 1

    conn = get_connection(db_file)
    try:
        paths = [row["path"] for row in conn.execute("SELECT path FROM files").fetchall()]
        assert len(paths) == 1
        assert str(valid_file.resolve()) in paths
    finally:
        conn.close()


def test_cleanup_ignored_files_from_db(tmp_path: Path):
    """Test one-time cleanup removes already-indexed rows that match ignore rules."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    init_db(db_file)
    conn = get_connection(db_file)
    try:
        # Pre-populate database with ignored files
        conn.execute(
            "INSERT INTO files (id, path, filename, ext, size, created_at, modified_at, content_hash, indexed_at, status, error) VALUES (1, 'D:/docs/~$old.docx', '~$old.docx', '.docx', 10, 1.0, 1.0, 'h1', 1.0, 'error', 'PackageNotFoundError')"
        )
        conn.execute(
            "INSERT INTO files (id, path, filename, ext, size, created_at, modified_at, content_hash, indexed_at, status, error) VALUES (2, 'D:/docs/Thumbs.db', 'Thumbs.db', '.db', 100, 1.0, 1.0, 'h2', 1.0, 'unsupported', NULL)"
        )
        conn.execute(
            "INSERT INTO files (id, path, filename, ext, size, created_at, modified_at, content_hash, indexed_at, status, error) VALUES (3, 'D:/docs/test.tmp', 'test.tmp', '.tmp', 50, 1.0, 1.0, 'h3', 1.0, 'indexed', NULL)"
        )
        conn.execute(
            "INSERT INTO files (id, path, filename, ext, size, created_at, modified_at, content_hash, indexed_at, status, error) VALUES (4, 'D:/docs/real.txt', 'real.txt', '.txt', 20, 1.0, 1.0, 'h4', 1.0, 'indexed', NULL)"
        )
        conn.commit()
    finally:
        conn.close()

    # Valid file on disk
    (docs_dir / "real.txt").write_text("Real content", encoding="utf-8")

    # Run scan_and_index
    scan_and_index([docs_dir], db_path=db_file)

    conn = get_connection(db_file)
    try:
        remaining_files = [row["filename"] for row in conn.execute("SELECT filename FROM files").fetchall()]
        assert "~$old.docx" not in remaining_files
        assert "Thumbs.db" not in remaining_files
        assert "test.tmp" not in remaining_files
        assert "real.txt" in remaining_files
    finally:
        conn.close()
