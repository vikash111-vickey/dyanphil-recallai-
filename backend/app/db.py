"""Database layer using standard sqlite3 and FTS5 for Dyanphil."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from app.config import settings

CREATE_TABLES_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    ext TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at REAL NOT NULL,
    modified_at REAL NOT NULL,
    content_hash TEXT,
    indexed_at REAL NOT NULL,
    status TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS contents (
    file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    text TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS file_fts USING fts5 (
    filename,
    path,
    content,
    tokenize='unicode61 remove_diacritics 2'
);

-- Triggers keeping file_fts synchronized with files and contents

CREATE TRIGGER IF NOT EXISTS files_ai_fts AFTER INSERT ON files BEGIN
    INSERT INTO file_fts(rowid, filename, path, content)
    VALUES (new.id, new.filename, new.path, '');
END;

CREATE TRIGGER IF NOT EXISTS files_ad_fts AFTER DELETE ON files BEGIN
    DELETE FROM file_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS files_au_fts AFTER UPDATE OF filename, path ON files BEGIN
    UPDATE file_fts SET filename = new.filename, path = new.path WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS contents_ai_fts AFTER INSERT ON contents BEGIN
    UPDATE file_fts SET content = new.text WHERE rowid = new.file_id;
END;

CREATE TRIGGER IF NOT EXISTS contents_au_fts AFTER UPDATE OF text ON contents BEGIN
    UPDATE file_fts SET content = new.text WHERE rowid = old.file_id;
END;

CREATE TRIGGER IF NOT EXISTS contents_ad_fts AFTER DELETE ON contents BEGIN
    UPDATE file_fts SET content = '' WHERE rowid = old.file_id;
END;
"""


def get_db_path(custom_path: Path | str | None = None) -> Path:
    """Resolve database path, defaulting to configured settings."""
    if custom_path is not None:
        return Path(custom_path)
    return settings.resolved_db_path


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Create and return a configured sqlite3 connection."""
    target_path = get_db_path(db_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection | None = None, db_path: Path | str | None = None) -> None:
    """Initialize database tables, virtual tables, and triggers."""
    should_close = False
    if conn is None:
        conn = get_connection(db_path)
        should_close = True

    try:
        conn.executescript(CREATE_TABLES_SQL)
        conn.commit()
    finally:
        if should_close:
            conn.close()


def get_file_by_path(conn: sqlite3.Connection, path: str) -> sqlite3.Row | None:
    """Retrieve file record by its normalized path."""
    cursor = conn.execute("SELECT * FROM files WHERE path = ?", (path,))
    return cursor.fetchone()


def upsert_file_record(
    conn: sqlite3.Connection,
    path: str,
    filename: str,
    ext: str,
    size: int,
    created_at: float,
    modified_at: float,
    content_hash: str | None,
    indexed_at: float,
    status: str,
    error: str | None = None,
    text: str | None = None,
) -> int:
    """
    Insert or update a file record and its extracted content.
    Synchronizes with the FTS virtual table via triggers.
    """
    with conn:
        existing = get_file_by_path(conn, path)
        if existing:
            file_id = existing["id"]
            conn.execute(
                """
                UPDATE files
                SET filename = ?, ext = ?, size = ?, created_at = ?,
                    modified_at = ?, content_hash = ?, indexed_at = ?,
                    status = ?, error = ?
                WHERE id = ?
                """,
                (
                    filename,
                    ext,
                    size,
                    created_at,
                    modified_at,
                    content_hash,
                    indexed_at,
                    status,
                    error,
                    file_id,
                ),
            )
            # Remove any previous contents before inserting new text
            conn.execute("DELETE FROM contents WHERE file_id = ?", (file_id,))
        else:
            cursor = conn.execute(
                """
                INSERT INTO files (
                    path, filename, ext, size, created_at,
                    modified_at, content_hash, indexed_at, status, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    path,
                    filename,
                    ext,
                    size,
                    created_at,
                    modified_at,
                    content_hash,
                    indexed_at,
                    status,
                    error,
                ),
            )
            file_id = cursor.lastrowid

        if status == "indexed" and text is not None and text.strip():
            conn.execute(
                "INSERT INTO contents (file_id, text) VALUES (?, ?)",
                (file_id, text),
            )

    return file_id


def delete_file_by_path(conn: sqlite3.Connection, path: str) -> bool:
    """Delete a file by path, cascading to contents and FTS."""
    with conn:
        cursor = conn.execute("DELETE FROM files WHERE path = ?", (path,))
        return cursor.rowcount > 0


def get_all_file_paths(conn: sqlite3.Connection) -> list[str]:
    """Return all recorded file paths."""
    cursor = conn.execute("SELECT path FROM files")
    return [row["path"] for row in cursor.fetchall()]


def search_fts(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """
    Execute FTS5 search on filename, path, and extracted content.
    Returns ranked matches with metadata and snippet.
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    sql = """
        SELECT
            f.id,
            f.filename,
            f.path,
            f.modified_at,
            snippet(file_fts, -1, '>>>', '<<<', '...', 15) AS snippet,
            bm25(file_fts) AS rank_score
        FROM file_fts
        JOIN files f ON f.id = file_fts.rowid
        WHERE file_fts MATCH ?
        ORDER BY rank_score ASC
        LIMIT ?
    """

    try:
        cursor = conn.execute(sql, (clean_query, limit))
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        # Fallback: tokenize words into quoted terms to avoid FTS syntax errors
        tokens = re.findall(r"\w+", clean_query)
        if not tokens:
            return []
        safe_query = " ".join(f'"{token}"' for token in tokens)
        try:
            cursor = conn.execute(sql, (safe_query, limit))
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            return []

    results = []
    for rank, row in enumerate(rows, start=1):
        results.append({
            "rank": rank,
            "id": row["id"],
            "filename": row["filename"],
            "path": row["path"],
            "modified_at": row["modified_at"],
            "snippet": row["snippet"] or "",
            "score": row["rank_score"],
        })
    return results


def get_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Retrieve indexing statistics grouped by status and extension."""
    total_cursor = conn.execute("SELECT COUNT(*) AS total FROM files")
    total_files = total_cursor.fetchone()["total"]

    status_cursor = conn.execute(
        "SELECT status, COUNT(*) AS count FROM files GROUP BY status ORDER BY count DESC"
    )
    by_status = {row["status"]: row["count"] for row in status_cursor.fetchall()}

    ext_cursor = conn.execute(
        "SELECT ext, COUNT(*) AS count FROM files GROUP BY ext ORDER BY count DESC"
    )
    by_ext = {row["ext"]: row["count"] for row in ext_cursor.fetchall()}

    return {
        "total_files": total_files,
        "by_status": by_status,
        "by_extension": by_ext,
    }
