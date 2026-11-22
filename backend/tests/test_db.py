"""Tests for database initialization, schemas, triggers, and foreign keys."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.db import get_connection, init_db


def test_init_db_creates_all_tables_and_triggers(tmp_path: Path):
    """Test that init_db creates files, contents, file_fts, and triggers."""
    db_file = tmp_path / "test_recall.db"
    init_db(db_file)

    assert db_file.exists()

    conn = get_connection(db_file)
    try:
        # Check foreign keys enabled
        fk_cursor = conn.execute("PRAGMA foreign_keys;")
        assert fk_cursor.fetchone()[0] == 1

        # Check tables exist
        tables_cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow') ORDER BY name;"
        )
        table_names = {row["name"] for row in tables_cursor.fetchall()}
        assert "files" in table_names
        assert "contents" in table_names
        assert "file_fts" in table_names

        # Check columns of files table
        col_cursor = conn.execute("PRAGMA table_info(files);")
        columns = {row["name"] for row in col_cursor.fetchall()}
        expected_cols = {
            "id",
            "path",
            "filename",
            "ext",
            "size",
            "created_at",
            "modified_at",
            "content_hash",
            "indexed_at",
            "status",
            "error",
        }
        assert expected_cols.issubset(columns)

        # Check columns of contents table
        contents_col_cursor = conn.execute("PRAGMA table_info(contents);")
        contents_cols = {row["name"] for row in contents_col_cursor.fetchall()}
        assert {"file_id", "text"}.issubset(contents_cols)

        # Check triggers exist
        trigger_cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name;"
        )
        triggers = {row["name"] for row in trigger_cursor.fetchall()}
        assert "files_ai_fts" in triggers
        assert "files_ad_fts" in triggers
        assert "files_au_fts" in triggers
        assert "contents_ai_fts" in triggers
        assert "contents_au_fts" in triggers
        assert "contents_ad_fts" in triggers
    finally:
        conn.close()


def test_db_foreign_keys_and_fts_sync(tmp_path: Path):
    """Test that foreign keys cascade on delete and file_fts stays in sync."""
    db_file = tmp_path / "test_sync.db"
    init_db(db_file)

    conn = get_connection(db_file)
    try:
        # Insert a file
        conn.execute(
            """
            INSERT INTO files (id, path, filename, ext, size, created_at, modified_at, content_hash, indexed_at, status, error)
            VALUES (1, 'D:/docs/sample.txt', 'sample.txt', '.txt', 100, 1.0, 1.0, 'hash1', 1.0, 'indexed', NULL);
            """
        )
        conn.execute("INSERT INTO contents (file_id, text) VALUES (1, 'Searchable document body');")
        conn.commit()

        # Check FTS matches
        fts_res = conn.execute("SELECT * FROM file_fts WHERE file_fts MATCH 'Searchable';").fetchall()
        assert len(fts_res) == 1

        # Delete from files should cascade delete contents and delete from file_fts via triggers
        conn.execute("DELETE FROM files WHERE id = 1;")
        conn.commit()

        contents_res = conn.execute("SELECT * FROM contents WHERE file_id = 1;").fetchall()
        assert len(contents_res) == 0

        fts_res_after = conn.execute("SELECT * FROM file_fts WHERE file_fts MATCH 'Searchable';").fetchall()
        assert len(fts_res_after) == 0
    finally:
        conn.close()
