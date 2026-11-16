"""Filesystem scanning and incremental indexing module."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

from app.db import (
    delete_file_by_path,
    get_all_file_paths,
    get_connection,
    get_file_by_path,
    init_db,
    upsert_file_record,
)
from app.ingestion.extractors import SUPPORTED_EXTENSIONS, extract_file

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB

SKIP_DIR_NAMES = {
    ".venv",
    "node_modules",
    ".git",
    "__pycache__",
    "appdata",
    "windows",
    "program files",
    "$recycle.bin",
}


@dataclass
class IndexStats:
    scanned: int = 0
    indexed: int = 0
    skipped: int = 0
    unchanged: int = 0
    failed: int = 0
    needs_ocr: int = 0
    cleaned: int = 0


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file efficiently in 64KB chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def should_skip_directory(dir_name: str) -> bool:
    """Determine whether a directory should be skipped during recursive traversal."""
    lower_name = dir_name.lower()
    if dir_name.startswith("."):
        return True
    if lower_name in SKIP_DIR_NAMES:
        return True
    return False


def scan_directory(folder: Path) -> Generator[tuple[Path, bool], None, None]:
    """
    Recursively scan a directory using pathlib.
    Yields (file_path, is_too_large) for supported extensions.
    Skips ignored and hidden directory trees.
    """
    try:
        entries = list(folder.iterdir())
    except (PermissionError, OSError):
        return

    for entry in entries:
        try:
            if entry.is_dir():
                if should_skip_directory(entry.name):
                    continue
                yield from scan_directory(entry)
            elif entry.is_file():
                if entry.name.startswith("."):
                    continue
                if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue

                try:
                    size = entry.stat().st_size
                except (PermissionError, OSError):
                    continue

                if size > MAX_FILE_SIZE_BYTES:
                    yield (entry.resolve(), True)
                else:
                    yield (entry.resolve(), False)
        except (PermissionError, OSError):
            continue


def index_folders(
    folders: list[Path | str],
    db_path: Path | str | None = None,
) -> IndexStats:
    """
    Incrementally index the provided folders into the database.
    - Removes database rows for deleted or moved files.
    - Skips files whose size and modification timestamp are unchanged.
    - Extracts content and synchronizes FTS for new or modified files.
    """
    stats = IndexStats()
    resolved_folders: list[Path] = []
    for f in folders:
        p = Path(f).resolve()
        if p.exists() and p.is_dir():
            resolved_folders.append(p)

    conn = get_connection(db_path)
    try:
        init_db(conn)

        # 1. Discover all candidate files
        candidate_files: list[Path] = []
        for folder in resolved_folders:
            for file_path, is_too_large in scan_directory(folder):
                stats.scanned += 1
                if is_too_large:
                    stats.skipped += 1
                else:
                    candidate_files.append(file_path)

        scanned_paths_set = {str(p) for p in candidate_files}

        # 2. Cleanup deleted files from the database
        all_db_paths = get_all_file_paths(conn)
        for recorded_path in all_db_paths:
            rec_p = Path(recorded_path)
            # File deleted on disk
            if not rec_p.exists():
                delete_file_by_path(conn, recorded_path)
                stats.cleaned += 1
                continue

            # File is under one of the scanned folder trees but no longer a candidate
            is_under_scanned = False
            for folder_root in resolved_folders:
                try:
                    if rec_p.is_relative_to(folder_root):
                        is_under_scanned = True
                        break
                except ValueError:
                    continue

            if is_under_scanned and recorded_path not in scanned_paths_set:
                delete_file_by_path(conn, recorded_path)
                stats.cleaned += 1

        # 3. Process candidate files incrementally
        for file_path in candidate_files:
            path_str = str(file_path)
            try:
                stat = file_path.stat()
                size = stat.st_size
                mtime = stat.st_mtime
                ctime = stat.st_ctime
            except (PermissionError, OSError) as e:
                stats.failed += 1
                upsert_file_record(
                    conn=conn,
                    path=path_str,
                    filename=file_path.name,
                    ext=file_path.suffix.lower(),
                    size=0,
                    created_at=0.0,
                    modified_at=0.0,
                    content_hash=None,
                    indexed_at=time.time(),
                    status="error",
                    error=f"Stat error: {str(e)}",
                    text=None,
                )
                continue

            existing = get_file_by_path(conn, path_str)

            # Check if unchanged
            if existing is not None:
                size_match = existing["size"] == size
                mtime_match = abs(existing["modified_at"] - mtime) < 1e-4
                if size_match and mtime_match:
                    stats.unchanged += 1
                    continue

            # File is new or changed: compute SHA-256 and extract
            content_hash = None
            try:
                content_hash = compute_sha256(file_path)
            except Exception as e:
                stats.failed += 1
                upsert_file_record(
                    conn=conn,
                    path=path_str,
                    filename=file_path.name,
                    ext=file_path.suffix.lower(),
                    size=size,
                    created_at=ctime,
                    modified_at=mtime,
                    content_hash=None,
                    indexed_at=time.time(),
                    status="error",
                    error=f"Hashing error: {str(e)}",
                    text=None,
                )
                continue

            extraction = extract_file(file_path)

            upsert_file_record(
                conn=conn,
                path=path_str,
                filename=file_path.name,
                ext=file_path.suffix.lower(),
                size=size,
                created_at=ctime,
                modified_at=mtime,
                content_hash=content_hash,
                indexed_at=time.time(),
                status=extraction.status,
                error=extraction.error,
                text=extraction.text,
            )

            if extraction.status == "indexed":
                stats.indexed += 1
            elif extraction.status == "needs_ocr":
                stats.needs_ocr += 1
            elif extraction.status == "error":
                stats.failed += 1
            elif extraction.status in ("empty", "unsupported"):
                stats.skipped += 1

        return stats

    finally:
        conn.close()
