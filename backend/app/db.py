"""Database module using standard sqlite3 and FTS5 for Dyanphil."""

from __future__ import annotations

import datetime
import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.config import settings

CREATE_TABLES_SQL = """
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
    error TEXT,
    doc_type TEXT,
    doc_type_score REAL,
    source TEXT DEFAULT 'file',
    external_id TEXT
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

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    embedding BLOB NOT NULL,
    model TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_file_id ON chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_chunks_model ON chunks(model);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    value_date TEXT,
    snippet TEXT
);

CREATE INDEX IF NOT EXISTS idx_facts_file_id ON facts(file_id);
CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind);
CREATE INDEX IF NOT EXISTS idx_facts_value_date ON facts(value_date);

CREATE TABLE IF NOT EXISTS vault (
    id INTEGER PRIMARY KEY,
    file_id INTEGER UNIQUE REFERENCES files(id) ON DELETE CASCADE,
    label TEXT,
    created_at REAL
);

CREATE INDEX IF NOT EXISTS idx_vault_file_id ON vault(file_id);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS emails (
    file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    gmail_id TEXT UNIQUE,
    thread_id TEXT,
    sender TEXT,
    recipients TEXT,
    labels TEXT,
    has_attachments INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_emails_gmail_id ON emails(gmail_id);

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
    """Resolve database path, ensuring data directory exists."""
    if custom_path is not None:
        target = Path(custom_path)
    else:
        target = settings.resolved_db_path
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _normcase_path(p: str | None) -> str:
    """Canonical Windows path normalizer using normcase and normpath."""
    if not p:
        return ""
    clean = str(p).strip().strip('"').strip("'")
    if clean.startswith("gmail://"):
        return clean
    return os.path.normcase(os.path.normpath(clean))


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Create and return a configured sqlite3 connection with foreign keys enabled."""
    target_path = get_db_path(db_path)
    conn = sqlite3.connect(str(target_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.create_function("normcase_path", 1, _normcase_path)
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize database tables, virtual tables, triggers, and migrations."""
    conn = get_connection(db_path)
    try:
        # Migration: ensure doc_type, doc_type_score, source, external_id exist before triggers/indexes
        try:
            cur = conn.execute("PRAGMA table_info(files)")
            columns = {row["name"] for row in cur.fetchall()}
            if columns:
                if "doc_type" not in columns:
                    conn.execute("ALTER TABLE files ADD COLUMN doc_type TEXT")
                if "doc_type_score" not in columns:
                    conn.execute("ALTER TABLE files ADD COLUMN doc_type_score REAL")
                if "source" not in columns:
                    conn.execute("ALTER TABLE files ADD COLUMN source TEXT DEFAULT 'file'")
                if "external_id" not in columns:
                    conn.execute("ALTER TABLE files ADD COLUMN external_id TEXT")
                conn.commit()
        except Exception:
            pass

        conn.executescript(CREATE_TABLES_SQL)

        # Ensure columns exist if files table was created anew
        cur = conn.execute("PRAGMA table_info(files)")
        columns = {row["name"] for row in cur.fetchall()}
        if "doc_type" not in columns:
            conn.execute("ALTER TABLE files ADD COLUMN doc_type TEXT")
        if "doc_type_score" not in columns:
            conn.execute("ALTER TABLE files ADD COLUMN doc_type_score REAL")
        if "source" not in columns:
            conn.execute("ALTER TABLE files ADD COLUMN source TEXT DEFAULT 'file'")
        if "external_id" not in columns:
            conn.execute("ALTER TABLE files ADD COLUMN external_id TEXT")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_source ON files(source);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_external_id ON files(external_id);")
        conn.commit()
    finally:
        conn.close()


def normalize_windows_path(path_str: str) -> str:
    """Normalize Windows path using os.path.normcase and os.path.normpath."""
    return _normcase_path(path_str)


def get_file_by_path(conn: sqlite3.Connection, path: str) -> sqlite3.Row | None:
    """Retrieve file record by path with robust Windows normalization:
    - Strips quotes/spaces
    - Canonical lookup via os.path.normcase(os.path.normpath(...))
    - Case and slash agnostic
    """
    if not path:
        return None

    clean = path.strip().strip('"').strip("'")
    norm = _normcase_path(clean)

    # 1. Exact match with original cleaned path string
    cursor = conn.execute("SELECT * FROM files WHERE path = ?", (clean,))
    row = cursor.fetchone()
    if row:
        return row

    # 2. Case-insensitive exact match
    cursor = conn.execute("SELECT * FROM files WHERE path = ? COLLATE NOCASE", (clean,))
    row = cursor.fetchone()
    if row:
        return row

    # 3. Match using normcase_path SQLite custom function
    try:
        cursor = conn.execute("SELECT * FROM files WHERE normcase_path(path) = ?", (norm,))
        row = cursor.fetchone()
        if row:
            return row
    except sqlite3.OperationalError:
        pass

    # 4. Slash-agnostic and case-insensitive comparison
    query_slash = norm.replace("\\", "/")
    cursor = conn.execute(
        "SELECT * FROM files WHERE replace(lower(path), '\\', '/') = ?",
        (query_slash,),
    )
    row = cursor.fetchone()
    if row:
        return row

    # 5. In-memory scan fallback
    try:
        for r in conn.execute("SELECT * FROM files").fetchall():
            if _normcase_path(r["path"]) == norm:
                return r
    except Exception:
        pass

    return None


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
    Caller manages transactions / batch commits.
    """
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
    cursor = conn.execute("DELETE FROM files WHERE path = ?", (path,))
    return cursor.rowcount > 0


def get_all_file_paths(conn: sqlite3.Connection) -> list[str]:
    """Return all recorded file paths."""
    cursor = conn.execute("SELECT path FROM files")
    return [row["path"] for row in cursor.fetchall()]


GENERIC_WORDS: set[str] = {
    # English generic / document / file type terms
    "certificate", "certificates", "file", "files", "document", "documents",
    "pdf", "pdfs", "doc", "docs", "docx", "report", "reports", "paper", "papers",
    "my", "copy", "new", "folder", "scan", "scanned", "page", "pages", "txt", "text",
    "notes", "sheet", "sheets", "excel", "presentation", "slide", "slides",
    # Hinglish generic terms
    "mera", "meri", "mere", "naya", "nayi", "purana", "purani", "karo", "dikhao",
    "dhundo", "chahiye", "wala", "wali", "kaha",
}


def compute_term_idfs(conn: sqlite3.Connection, terms: list[str]) -> dict[str, float]:
    """
    Compute simple IDF per term from file_fts:
    IDF = log((N + 1) / (df + 0.5)) + 1.0
    where N is total files and df is document frequency matching term*.
    Generic words are given low weight (0.05).
    """
    if not terms:
        return {}

    try:
        total_cursor = conn.execute("SELECT count(*) FROM files")
        total_row = total_cursor.fetchone()
        total_files = total_row[0] if total_row else 1
    except Exception:
        total_files = 1
    total_files = max(1, total_files)

    idfs: dict[str, float] = {}
    for term in terms:
        clean_term = term.strip().lower()
        if not clean_term:
            continue
        if clean_term in GENERIC_WORDS:
            idfs[clean_term] = 0.05
            continue
        try:
            cur = conn.execute(
                "SELECT count(DISTINCT rowid) FROM file_fts WHERE file_fts MATCH ?",
                (f'"{clean_term}"*',),
            )
            df = cur.fetchone()[0]
        except Exception:
            df = 1
        df = max(1, df)
        idf = math.log((total_files + 1.0) / (df + 0.5)) + 1.0
        idfs[clean_term] = max(0.5, idf)

    return idfs


def search_fts(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 10,
    w_filename: float = 10.0,
    w_path: float = 2.0,
    w_content: float = 1.0,
) -> list[dict[str, Any]]:
    """
    Execute FTS5 search trying AND first, then falling back to OR with:
    score = sum of weights of matched terms.
    Weights columns with bm25(file_fts, 10.0, 2.0, 1.0).
    Rare words win: term weight = IDF, strong boost if rare query term is in filename or folder names.
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    terms = [t.lower() for t in re.findall(r"\w+", clean_query) if t.strip()]
    if not terms:
        return []

    # 1. Compute IDF per term (generic words assigned low weight)
    idfs = compute_term_idfs(conn, terms)
    rare_terms = [t for t in terms if t not in GENERIC_WORDS and idfs.get(t, 0.0) >= 0.5]
    if not rare_terms and terms:
        rare_terms = [max(terms, key=lambda t: idfs.get(t, 0.0))]

    pool_size = max(50, limit * 4)

    # 2. Try AND first, then fall back to OR
    and_query = " AND ".join(f'"{t}"*' for t in terms)
    or_query = " OR ".join(f'"{t}"*' for t in terms)

    sql = f"""
        SELECT
            f.id,
            f.filename,
            f.path,
            f.modified_at,
            snippet(file_fts, -1, '>>>', '<<<', '...', 15) AS snippet,
            bm25(file_fts, {w_filename}, {w_path}, {w_content}) AS rank_score
        FROM file_fts
        JOIN files f ON f.id = file_fts.rowid
        WHERE file_fts MATCH ?
        ORDER BY rank_score ASC
        LIMIT ?
    """

    rows = []
    # Try AND first when multiple terms
    if len(terms) > 1:
        try:
            cursor = conn.execute(sql, (and_query, pool_size))
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            rows = []

    # Fall back to OR if AND returned nothing or single term
    if not rows:
        try:
            cursor = conn.execute(sql, (or_query, pool_size))
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            safe_query = " OR ".join(f"{t}*" for t in terms)
            try:
                cursor = conn.execute(sql, (safe_query, pool_size))
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                return []

    scored_items: list[dict[str, Any]] = []
    for row in rows:
        fn = row["filename"]
        fn_lower = fn.lower()
        path = row["path"]
        path_lower = path.lower()
        snippet = row["snippet"] or ""
        snippet_lower = snippet.lower()

        # Extract folder names from path (excluding filename)
        try:
            folder_parts = [p.lower() for p in Path(path).parts[:-1]]
            folder_text = " ".join(folder_parts)
        except Exception:
            folder_text = path_lower

        # Identify which query terms matched
        matched_terms = [
            t for t in terms
            if (t in fn_lower or t in folder_text or t in snippet_lower or f">>>{t}" in snippet_lower)
        ]
        # Base score: sum of weights of matched terms
        score = sum(idfs.get(t, 0.05) for t in matched_terms)

        # Invert negative FTS5 bm25 as a secondary score component
        bm_score = -row["rank_score"] if row["rank_score"] is not None else 0.0
        score += max(0.0, bm_score) * 0.05

        # Rare-word boost: if rare query term appears in filename or folder names
        has_rare_in_fn = False
        has_rare_in_folder = False
        for rt in rare_terms:
            idf_val = idfs.get(rt, 1.0)
            if rt in fn_lower:
                score += idf_val * 100.0  # Strong boost for rare term in filename
                has_rare_in_fn = True
            elif rt in folder_text:
                score += idf_val * 50.0   # Strong boost for rare term in folder
                has_rare_in_folder = True

        scored_items.append({
            "id": row["id"],
            "filename": fn,
            "path": path,
            "modified_at": row["modified_at"],
            "snippet": snippet,
            "score": score,
            "has_rare_in_fn": has_rare_in_fn,
            "has_rare_in_folder": has_rare_in_folder,
        })

    # Sort scored items: files with rare term in filename first, then rare term in folder, then score descending
    scored_items.sort(
        key=lambda item: (
            1.0 if item["has_rare_in_fn"] else (0.5 if item["has_rare_in_folder"] else 0.0),
            item["score"],
        ),
        reverse=True,
    )

    results = []
    for rank, item in enumerate(scored_items[:limit], start=1):
        results.append({
            "rank": rank,
            "id": item["id"],
            "filename": item["filename"],
            "path": item["path"],
            "modified_at": item["modified_at"],
            "snippet": item["snippet"],
            "score": item["score"],
        })

    return results


def get_stats(conn: sqlite3.Connection, db_path: Path | str | None = None) -> dict[str, Any]:
    """Retrieve indexing statistics grouped by status, extension, and DB size."""
    target_path = get_db_path(db_path)
    db_size_bytes = target_path.stat().st_size if target_path.exists() else 0

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

    chunk_cursor = conn.execute("SELECT COUNT(*) AS total FROM chunks")
    chunk_count = chunk_cursor.fetchone()["total"]

    return {
        "total_files": total_files,
        "by_status": by_status,
        "by_extension": by_ext,
        "db_size_bytes": db_size_bytes,
        "chunk_count": chunk_count,
        "embedding_model": settings.embedding_model,
    }


def get_files_by_status(conn: sqlite3.Connection, status: str, limit: int = 50) -> list[sqlite3.Row]:
    """Retrieve files filtered by status up to limit."""
    cursor = conn.execute(
        "SELECT path, error, status FROM files WHERE status = ? ORDER BY id ASC LIMIT ?",
        (status, limit),
    )
    return cursor.fetchall()


def delete_chunks_by_file_id(conn: sqlite3.Connection, file_id: int) -> int:
    """Delete all chunks for a specific file_id."""
    cursor = conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    return cursor.rowcount


def insert_chunks_batch(
    conn: sqlite3.Connection,
    chunks_data: list[tuple[int, int, str, str, bytes, str]],
) -> None:
    """Insert a batch of chunk tuples (file_id, chunk_index, kind, text, embedding, model)."""
    conn.executemany(
        """
        INSERT INTO chunks (file_id, chunk_index, kind, text, embedding, model)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        chunks_data,
    )


def get_chunks_for_model(conn: sqlite3.Connection, model: str) -> list[sqlite3.Row]:
    """Retrieve all chunks and parent file details for vector similarity search."""
    cursor = conn.execute(
        """
        SELECT
            c.id AS chunk_id,
            c.file_id,
            c.chunk_index,
            c.kind,
            c.text,
            c.embedding,
            f.path,
            f.filename,
            f.modified_at
        FROM chunks c
        JOIN files f ON f.id = c.file_id
        WHERE c.model = ?
        """,
        (model,),
    )
    return cursor.fetchall()


def get_embedded_file_info(conn: sqlite3.Connection, model: str) -> dict[int, dict[str, Any]]:
    """Return mapping of file_id -> {chunk_count: int, max_id: int} for a model."""
    cursor = conn.execute(
        """
        SELECT file_id, COUNT(*) AS count
        FROM chunks
        WHERE model = ?
        GROUP BY file_id
        """,
        (model,),
    )
    return {row["file_id"]: {"count": row["count"]} for row in cursor.fetchall()}


def update_file_classification(
    conn: sqlite3.Connection,
    file_id: int,
    doc_type: str,
    doc_type_score: float,
) -> None:
    """Update doc_type and doc_type_score for a file."""
    conn.execute(
        "UPDATE files SET doc_type = ?, doc_type_score = ? WHERE id = ?",
        (doc_type, doc_type_score, file_id),
    )


def delete_facts_by_file_id(conn: sqlite3.Connection, file_id: int) -> int:
    """Delete all facts extracted for a file."""
    cur = conn.execute("DELETE FROM facts WHERE file_id = ?", (file_id,))
    return cur.rowcount


def insert_facts_batch(
    conn: sqlite3.Connection,
    facts_data: list[tuple[int, str, str, str, str | None, str | None]],
) -> None:
    """Insert a batch of facts tuples (file_id, kind, label, value, value_date, snippet)."""
    if not facts_data:
        return
    conn.executemany(
        """
        INSERT INTO facts (file_id, kind, label, value, value_date, snippet)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        facts_data,
    )


def get_facts_by_file_id(
    conn: sqlite3.Connection,
    file_id: int,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Retrieve facts for a specific file."""
    sql = "SELECT id, file_id, kind, label, value, value_date, snippet FROM facts WHERE file_id = ? ORDER BY id ASC"
    if limit is not None and limit > 0:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, (file_id,)).fetchall()


def get_expiring_facts(
    conn: sqlite3.Connection,
    days: int = 60,
    reference_date: datetime.date | None = None,
) -> list[dict[str, Any]]:
    """
    Retrieve facts representing expiry or due dates within the next N days,
    as well as already expired ones, ordered by value_date ASC.
    """
    ref = reference_date or datetime.date.today()
    cutoff = (ref + datetime.timedelta(days=days)).isoformat()

    cursor = conn.execute(
        """
        SELECT
            ft.id AS fact_id,
            ft.file_id,
            ft.kind,
            ft.label,
            ft.value,
            ft.value_date,
            ft.snippet,
            f.filename,
            f.path,
            f.doc_type
        FROM facts ft
        JOIN files f ON f.id = ft.file_id
        WHERE (
            ft.kind IN ('expiry', 'due_date')
            OR lower(ft.label) LIKE '%expir%'
            OR lower(ft.label) LIKE '%valid%'
            OR lower(ft.label) LIKE '%due%'
            OR lower(ft.label) LIKE '%renew%'
        )
        AND ft.value_date IS NOT NULL
        AND ft.value_date != ''
        AND ft.value_date <= ?
        ORDER BY ft.value_date ASC
        """,
        (cutoff,),
    )
    rows = cursor.fetchall()
    results: list[dict[str, Any]] = []
    for r in rows:
        v_date_str = r["value_date"]
        try:
            val_d = datetime.date.fromisoformat(v_date_str)
            days_diff = (val_d - ref).days
            is_expired = days_diff < 0
        except Exception:
            days_diff = 0
            is_expired = False

        results.append({
            "fact_id": r["fact_id"],
            "file_id": r["file_id"],
            "kind": r["kind"],
            "label": r["label"],
            "value": r["value"],
            "value_date": v_date_str,
            "snippet": r["snippet"] or "",
            "filename": r["filename"],
            "path": r["path"],
            "doc_type": r["doc_type"] or "other",
            "days_remaining": days_diff,
            "is_expired": is_expired,
        })
    return results


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    """Retrieve setting value by key."""
    cursor = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    return row["value"] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Insert or update setting value by key."""
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


DEFAULT_EXCLUDED_FOLDER_NAMES: set[str] = {
    "pictures",
    "photos",
    "camera roll",
    "screenshots",
    "saved pictures",
}

IMAGE_EXTENSIONS: set[str] = {".png", ".jpg", ".jpeg"}
DOCUMENT_EXTENSIONS: set[str] = {".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv"}


def get_default_excluded_folders() -> list[str]:
    """Return default excluded folders including common photo folders and OneDrive\\Pictures."""
    defaults = ["Pictures", "Photos", "Camera Roll", "Screenshots", "Saved Pictures"]
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if onedrive:
        od_pics = Path(onedrive) / "Pictures"
        defaults.append(str(od_pics))
    else:
        defaults.append(str(Path.home() / "OneDrive" / "Pictures"))
    home_pics = Path.home() / "Pictures"
    if str(home_pics) not in defaults:
        defaults.append(str(home_pics))
    return defaults


def get_excluded_folders(conn: sqlite3.Connection) -> list[str]:
    """Retrieve excluded folders list from settings. Defaults to standard photo/OneDrive folders."""
    raw = get_setting(conn, "excluded_folders")
    if raw is None:
        defaults = get_default_excluded_folders()
        set_setting(conn, "excluded_folders", json.dumps(defaults))
        return defaults
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return [str(p) for p in val]
    except Exception:
        pass
    return get_default_excluded_folders()


def save_excluded_folders(conn: sqlite3.Connection, folders: list[str]) -> None:
    """Save excluded folders list to settings table."""
    set_setting(conn, "excluded_folders", json.dumps(folders))


def get_image_folders(conn: sqlite3.Connection) -> list[str]:
    """Retrieve image folders list from settings table. Defaults to empty list []."""
    raw = get_setting(conn, "image_folders")
    if not raw:
        return []
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return [str(p) for p in val]
    except Exception:
        pass
    return []


def save_image_folders(conn: sqlite3.Connection, folders: list[str]) -> None:
    """Save image folders list to settings table."""
    set_setting(conn, "image_folders", json.dumps(folders))


def is_path_excluded(p: Path | str, excluded_folders: list[str] | None = None) -> bool:
    """
    Check if a path is inside an excluded folder:
    - Any directory part matches DEFAULT_EXCLUDED_FOLDER_NAMES or a single-name excluded_folder
    - Path is relative to or inside any directory path in excluded_folders
    """
    p_obj = Path(p) if not isinstance(p, Path) else p
    p_parts_lower = [part.lower() for part in p_obj.parts]

    for part in p_parts_lower:
        if part in DEFAULT_EXCLUDED_FOLDER_NAMES:
            return True

    if not excluded_folders:
        return False

    norm_p = os.path.normcase(os.path.normpath(str(p_obj)))

    for ef in excluded_folders:
        ef_clean = ef.strip().strip('"').strip("'")
        if not ef_clean:
            continue
        if "\\" not in ef_clean and "/" not in ef_clean:
            if ef_clean.lower() in p_parts_lower:
                return True
        else:
            norm_ef = os.path.normcase(os.path.normpath(ef_clean))
            if norm_p == norm_ef or norm_p.startswith(norm_ef + os.sep) or norm_p.startswith(norm_ef + "/"):
                return True
            try:
                if p_obj.resolve().is_relative_to(Path(ef_clean).resolve()):
                    return True
            except Exception:
                pass

    return False


def is_path_in_image_folder(p: Path | str, image_folders: list[str] | None = None) -> bool:
    """
    Check if a path is inside one of the configured image folders.
    If image_folders is empty or None, returns False.
    """
    if not image_folders:
        return False

    p_obj = Path(p) if not isinstance(p, Path) else p
    norm_p = os.path.normcase(os.path.normpath(str(p_obj)))

    for im_f in image_folders:
        im_clean = im_f.strip().strip('"').strip("'")
        if not im_clean:
            continue
        norm_im = os.path.normcase(os.path.normpath(im_clean))
        if norm_p == norm_im or norm_p.startswith(norm_im + os.sep) or norm_p.startswith(norm_im + "/"):
            return True
        try:
            if p_obj.resolve().is_relative_to(Path(im_clean).resolve()):
                return True
        except Exception:
            pass

    return False


def pin_file_to_vault(conn: sqlite3.Connection, file_id: int, label: str | None = None) -> int:
    """Pin a file to the emergency vault. If already pinned, update label."""
    now = datetime.datetime.now().timestamp()
    cursor = conn.execute(
        """
        INSERT INTO vault (file_id, label, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(file_id) DO UPDATE SET label = excluded.label
        """,
        (file_id, label or "", now),
    )
    conn.commit()
    if cursor.lastrowid:
        return cursor.lastrowid
    cur = conn.execute("SELECT id FROM vault WHERE file_id = ?", (file_id,))
    row = cur.fetchone()
    return row["id"] if row else 0


def unpin_file_from_vault(conn: sqlite3.Connection, vault_id: int) -> bool:
    """Remove a pinned file from the vault by vault id."""
    cursor = conn.execute("DELETE FROM vault WHERE id = ?", (vault_id,))
    conn.commit()
    return cursor.rowcount > 0


def get_vault_file_ids(conn: sqlite3.Connection) -> set[int]:
    """Return the set of all file_ids currently pinned in the vault."""
    cursor = conn.execute("SELECT file_id FROM vault")
    return {row["file_id"] for row in cursor.fetchall()}


def get_vault_items(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Retrieve all pinned vault files with path, breadcrumb, doc_type, key facts, and exists flag."""
    cursor = conn.execute(
        """
        SELECT
            v.id AS id,
            v.file_id,
            v.label,
            v.created_at,
            f.filename,
            f.path,
            f.ext,
            f.size,
            f.modified_at,
            f.doc_type,
            f.status
        FROM vault v
        JOIN files f ON f.id = v.file_id
        ORDER BY v.created_at DESC
        """
    )
    rows = cursor.fetchall()
    items: list[dict[str, Any]] = []
    for r in rows:
        p = Path(r["path"])
        fid = r["file_id"]
        facts = get_facts_by_file_id(conn, fid, limit=3)
        formatted_facts = [
            {
                "kind": ft["kind"],
                "label": ft["label"],
                "value": ft["value"],
                "value_date": ft["value_date"],
            }
            for ft in facts
        ]
        mtime_str = (
            datetime.datetime.fromtimestamp(r["modified_at"]).strftime("%Y-%m-%d %H:%M:%S")
            if r["modified_at"]
            else ""
        )
        try:
            exists = p.exists()
        except Exception:
            exists = False

        items.append({
            "id": r["id"],
            "file_id": fid,
            "label": r["label"] or "",
            "filename": r["filename"],
            "path": r["path"],
            "breadcrumb": list(p.parts),
            "doc_type": r["doc_type"] or "other",
            "modified": mtime_str,
            "modified_at": r["modified_at"],
            "created_at": r["created_at"],
            "exists": exists,
            "facts": formatted_facts,
        })
    return items


def get_vault_suggestions(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    """
    Retrieve top indexed files eligible for the emergency vault
    (doc_type in 'id_document', 'insurance', 'medical', 'ticket', 'warranty')
    that are not pinned yet.
    """
    cursor = conn.execute(
        """
        SELECT
            f.id AS file_id,
            f.filename,
            f.path,
            f.ext,
            f.size,
            f.modified_at,
            f.doc_type,
            f.doc_type_score
        FROM files f
        WHERE f.status = 'indexed'
          AND f.doc_type IN ('id_document', 'insurance', 'medical', 'ticket', 'warranty')
          AND f.id NOT IN (SELECT file_id FROM vault)
        ORDER BY f.doc_type_score DESC, f.modified_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    suggestions: list[dict[str, Any]] = []
    for r in rows:
        p = Path(r["path"])
        fid = r["file_id"]
        facts = get_facts_by_file_id(conn, fid, limit=3)
        formatted_facts = [
            {
                "kind": ft["kind"],
                "label": ft["label"],
                "value": ft["value"],
                "value_date": ft["value_date"],
            }
            for ft in facts
        ]
        mtime_str = (
            datetime.datetime.fromtimestamp(r["modified_at"]).strftime("%Y-%m-%d %H:%M:%S")
            if r["modified_at"]
            else ""
        )
        try:
            exists = p.exists()
        except Exception:
            exists = False

        suggestions.append({
            "file_id": fid,
            "filename": r["filename"],
            "path": r["path"],
            "breadcrumb": list(p.parts),
            "doc_type": r["doc_type"] or "other",
            "doc_type_score": r["doc_type_score"],
            "modified": mtime_str,
            "modified_at": r["modified_at"],
            "exists": exists,
            "facts": formatted_facts,
        })
    return suggestions


def upsert_gmail_message(
    conn: sqlite3.Connection,
    gmail_id: str,
    thread_id: str,
    subject: str,
    sender: str,
    recipients: str,
    labels: str,
    email_date: float,
    text: str,
    has_attachments: int,
    doc_type: str | None = None,
    doc_type_score: float | None = None,
) -> int:
    """
    Store or update a Gmail message as a file and email record.
    Reuses existing file_id if present, updating contents, files, and emails.
    """
    cur = conn.execute("SELECT id FROM files WHERE source = 'gmail' AND external_id = ?", (gmail_id,))
    row = cur.fetchone()
    path_uri = f"gmail://{gmail_id}"
    size_bytes = len(text.encode("utf-8", errors="replace"))
    now = time.time()

    if row:
        file_id = row["id"]
        conn.execute(
            """
            UPDATE files
            SET filename = ?, size = ?, modified_at = ?, indexed_at = ?, status = 'indexed',
                doc_type = ?, doc_type_score = ?
            WHERE id = ?
            """,
            (subject, size_bytes, email_date, now, doc_type, doc_type_score, file_id),
        )
        conn.execute("INSERT OR REPLACE INTO contents (file_id, text) VALUES (?, ?)", (file_id, text))
        conn.execute(
            """
            INSERT OR REPLACE INTO emails (file_id, gmail_id, thread_id, sender, recipients, labels, has_attachments)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (file_id, gmail_id, thread_id, sender, recipients, labels, has_attachments),
        )
    else:
        cur_ins = conn.execute(
            """
            INSERT INTO files (path, filename, ext, size, created_at, modified_at, indexed_at, status, doc_type, doc_type_score, source, external_id)
            VALUES (?, ?, '.eml', ?, ?, ?, ?, 'indexed', ?, ?, 'gmail', ?)
            """,
            (path_uri, subject, size_bytes, email_date, email_date, now, doc_type, doc_type_score, gmail_id),
        )
        file_id = cur_ins.lastrowid
        conn.execute("INSERT INTO contents (file_id, text) VALUES (?, ?)", (file_id, text))
        conn.execute(
            """
            INSERT INTO emails (file_id, gmail_id, thread_id, sender, recipients, labels, has_attachments)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (file_id, gmail_id, thread_id, sender, recipients, labels, has_attachments),
        )

    conn.commit()
    return file_id


def delete_gmail_message(conn: sqlite3.Connection, gmail_id: str) -> None:
    """Delete a Gmail message by gmail_id with cascading cleanup."""
    conn.execute("DELETE FROM files WHERE source = 'gmail' AND external_id = ?", (gmail_id,))
    conn.commit()


def delete_all_gmail_data(conn: sqlite3.Connection) -> int:
    """Delete all Gmail messages, cascading to contents, emails, chunks, and facts."""
    cur = conn.execute("SELECT COUNT(*) AS cnt FROM files WHERE source = 'gmail'")
    row = cur.fetchone()
    count = row["cnt"] if row else 0
    conn.execute("DELETE FROM files WHERE source = 'gmail'")
    conn.commit()
    return count


def get_all_gmail_ids(conn: sqlite3.Connection) -> set[str]:
    """Retrieve all stored gmail_ids."""
    cur = conn.execute("SELECT external_id FROM files WHERE source = 'gmail' AND external_id IS NOT NULL")
    return {row["external_id"] for row in cur.fetchall()}


def get_email_metadata_by_file_id(conn: sqlite3.Connection, file_id: int) -> dict[str, Any] | None:
    """Retrieve email metadata for a given file_id."""
    cur = conn.execute("SELECT * FROM emails WHERE file_id = ?", (file_id,))
    row = cur.fetchone()
    if not row:
        return None
    return dict(row)


def get_gmail_status_db(conn: sqlite3.Connection) -> int:
    """Return count of stored Gmail messages."""
    cur = conn.execute("SELECT COUNT(*) AS cnt FROM files WHERE source = 'gmail'")
    row = cur.fetchone()
    return row["cnt"] if row else 0

