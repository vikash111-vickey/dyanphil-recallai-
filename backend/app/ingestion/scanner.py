"""Filesystem scanner and incremental indexer."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generator

from app.db import (
    delete_facts_by_file_id,
    delete_file_by_path,
    get_all_file_paths,
    get_connection,
    get_file_by_path,
    init_db,
    insert_facts_batch,
    update_file_classification,
    upsert_file_record,
    IMAGE_EXTENSIONS,
    get_excluded_folders,
    get_image_folders,
    is_path_excluded,
    is_path_in_image_folder,
)
from app.ingestion.classifier import classify_file
from app.ingestion.extractors import SUPPORTED_EXTENSIONS, extract_text
from app.ingestion.facts import extract_facts

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB
BATCH_SIZE = 50

SKIP_DIR_NAMES = {
    ".venv",
    "node_modules",
    ".git",
    "__pycache__",
    "appdata",
    "windows",
    "program files",
    "program files (x86)",
    "$recycle.bin",
    "system volume information",
}


FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
FILE_ATTRIBUTE_OFFLINE = 0x00001000
CLOUD_ONLY_ATTRIBUTES = (
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
    | FILE_ATTRIBUTE_RECALL_ON_OPEN
    | FILE_ATTRIBUTE_OFFLINE
)

EXACT_IGNORE_FILENAMES = {
    "thumbs.db",
    "desktop.ini",
    ".ds_store",
}


def should_ignore_file(file_name: str) -> bool:
    """
    Check if a file should be ignored (temporary and system files):
    - Starts with '~$' or '.~lock'
    - Ends with '.tmp' (case-insensitive)
    - Exact names: 'Thumbs.db', 'desktop.ini', '.DS_Store' (case-insensitive)
    """
    if file_name.startswith("~$") or file_name.startswith(".~lock"):
        return True
    lower_name = file_name.lower()
    if lower_name.endswith(".tmp"):
        return True
    if lower_name in EXACT_IGNORE_FILENAMES:
        return True
    return False


@dataclass
class IndexStats:
    scanned: int = 0
    indexed: int = 0
    unchanged: int = 0
    skipped: int = 0
    cloud_only: int = 0
    needs_ocr: int = 0
    errors: int = 0
    permission_denied: int = 0
    time_taken: float = 0.0


def is_cloud_only(stat_res: Any) -> bool:
    """Check if file has Windows cloud-only/dehydrated file attributes."""
    attrs = getattr(stat_res, "st_file_attributes", 0)
    return bool(attrs & CLOUD_ONLY_ATTRIBUTES)


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file efficiently in 64KB chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def should_skip_directory(dir_name: str) -> bool:
    """Determine whether a directory should be skipped."""
    if dir_name.startswith("."):
        return True
    if dir_name.lower() in SKIP_DIR_NAMES:
        return True
    return False


def is_permission_error(exc: Exception) -> bool:
    """Check whether an exception represents access denied or permission error."""
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError):
        # Windows error 5: ERROR_ACCESS_DENIED; POSIX errno 13: EACCES
        if getattr(exc, "winerror", None) == 5 or getattr(exc, "errno", None) == 13:
            return True
    return False


def walk_directory(
    folder: Path,
    stats: IndexStats,
    progress_callback: Callable[[int, str], None] | None = None,
    excluded_folders: list[str] | None = None,
    image_folders: list[str] | None = None,
) -> Generator[Path, None, None]:
    """
    Recursively walk a directory using pathlib.
    Skips ignored directory hierarchies, excluded folders, and files larger than 25 MB.
    Catches permission errors without crashing.
    """
    try:
        entries = list(folder.iterdir())
    except Exception as exc:
        if is_permission_error(exc):
            stats.permission_denied += 1
        else:
            stats.errors += 1
        return

    if progress_callback:
        progress_callback(stats.scanned, str(folder))

    for entry in entries:
        try:
            if entry.is_dir():
                if should_skip_directory(entry.name) or is_path_excluded(entry, excluded_folders):
                    continue
                yield from walk_directory(entry, stats, progress_callback, excluded_folders, image_folders)
            elif entry.is_file():
                if entry.name.startswith("."):
                    continue
                if should_ignore_file(entry.name):
                    continue
                if is_path_excluded(entry, excluded_folders):
                    continue
                ext = entry.suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                if ext in IMAGE_EXTENSIONS and not is_path_in_image_folder(entry, image_folders):
                    continue

                stats.scanned += 1
                if progress_callback and stats.scanned % 10 == 0:
                    progress_callback(stats.scanned, str(folder))

                try:
                    stat_res = entry.stat()
                    file_size = stat_res.st_size
                except Exception as exc:
                    if is_permission_error(exc):
                        stats.permission_denied += 1
                    else:
                        stats.errors += 1
                    continue

                if is_cloud_only(stat_res):
                    stats.cloud_only += 1
                    continue

                if file_size > MAX_FILE_SIZE_BYTES:
                    stats.skipped += 1
                    continue

                yield entry.resolve()
        except Exception as exc:
            if is_permission_error(exc):
                stats.permission_denied += 1
            else:
                stats.errors += 1
            continue


def scan_and_index(
    folders: list[Path | str],
    db_path: Path | str | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> IndexStats:
    """
    Scan folders recursively and incrementally update the SQLite database.
    Commits in batches of BATCH_SIZE so interruptions/crashes preserve work.
    """
    start_time = time.time()
    stats = IndexStats()

    resolved_folders: list[Path] = []
    for f in folders:
        p = Path(f).resolve()
        if p.exists() and p.is_dir():
            resolved_folders.append(p)
        else:
            try:
                # If access is denied to the root folder itself
                if not p.exists():
                    pass
            except Exception as exc:
                if is_permission_error(exc):
                    stats.permission_denied += 1

    conn = get_connection(db_path)
    try:
        init_db(db_path)
        excluded_folders = get_excluded_folders(conn)
        image_folders = get_image_folders(conn)

        # 1. Discover all candidate files
        candidate_files: list[Path] = []
        for folder in resolved_folders:
            if is_path_excluded(folder, excluded_folders):
                continue
            for file_path in walk_directory(folder, stats, progress_callback, excluded_folders, image_folders):
                candidate_files.append(file_path)

        scanned_paths_set = {str(p) for p in candidate_files}

        # 2. Cleanup files in DB:
        # a) Cleanup for any DB rows matching temporary/system ignore rules or excluded folders
        # b) Files inside scanned folders that no longer exist or are no longer valid candidates
        batch_counter = 0
        all_db_paths = get_all_file_paths(conn)
        for recorded_path in all_db_paths:
            rec_p = Path(recorded_path)

            if should_ignore_file(rec_p.name) or is_path_excluded(rec_p, excluded_folders):
                delete_file_by_path(conn, recorded_path)
                batch_counter += 1
                if batch_counter >= BATCH_SIZE:
                    conn.commit()
                    batch_counter = 0
                continue

            if rec_p.suffix.lower() in IMAGE_EXTENSIONS and not is_path_in_image_folder(rec_p, image_folders):
                delete_file_by_path(conn, recorded_path)
                batch_counter += 1
                if batch_counter >= BATCH_SIZE:
                    conn.commit()
                    batch_counter = 0
                continue

            is_under_scanned = False
            for folder_root in resolved_folders:
                try:
                    if rec_p.is_relative_to(folder_root):
                        is_under_scanned = True
                        break
                except ValueError:
                    continue

            if is_under_scanned:
                # If file was deleted or is no longer an active candidate file
                if not rec_p.exists() or recorded_path not in scanned_paths_set:
                    delete_file_by_path(conn, recorded_path)
                    batch_counter += 1
                    if batch_counter >= BATCH_SIZE:
                        conn.commit()
                        batch_counter = 0

        # Commit any deletes
        if batch_counter > 0:
            conn.commit()
            batch_counter = 0

        # 3. Process candidate files incrementally
        for idx, file_path in enumerate(candidate_files, start=1):
            if progress_callback:
                progress_callback(idx, str(file_path.parent))

            path_str = str(file_path)
            try:
                stat = file_path.stat()
                size = stat.st_size
                mtime = stat.st_mtime
                ctime = stat.st_ctime
            except Exception as exc:
                if is_permission_error(exc):
                    stats.permission_denied += 1
                else:
                    stats.errors += 1
                continue

            if is_cloud_only(stat):
                stats.cloud_only += 1
                continue

            existing = get_file_by_path(conn, path_str)

            # Skip unchanged files
            if existing is not None:
                size_match = existing["size"] == size
                mtime_match = abs(existing["modified_at"] - mtime) < 1e-4
                if size_match and mtime_match:
                    stats.unchanged += 1
                    continue

            # File is new or changed: compute SHA-256 only now
            content_hash = None
            try:
                content_hash = compute_sha256(file_path)
            except Exception as exc:
                if is_permission_error(exc):
                    stats.permission_denied += 1
                else:
                    stats.errors += 1
                continue

            if is_cloud_only(stat):
                stats.cloud_only += 1
                continue

            status, text, err = extract_text(file_path)

            if status == "error" and err and ("PermissionError" in err or "Access is denied" in err):
                stats.permission_denied += 1
                continue

            file_id = upsert_file_record(
                conn=conn,
                path=path_str,
                filename=file_path.name,
                ext=file_path.suffix.lower(),
                size=size,
                created_at=ctime,
                modified_at=mtime,
                content_hash=content_hash,
                indexed_at=time.time(),
                status=status,
                error=err,
                text=text,
            )

            if file_id is not None:
                doc_type, score = classify_file(path_str, file_path.name, text or "")
                update_file_classification(conn, file_id, doc_type, score)
                delete_facts_by_file_id(conn, file_id)
                if text:
                    extracted = extract_facts(text, filename=file_path.name, path=path_str)
                    if extracted:
                        insert_facts_batch(
                            conn,
                            [
                                (file_id, f.kind, f.label, f.value, f.value_date, f.snippet)
                                for f in extracted
                            ],
                        )

            batch_counter += 1
            if batch_counter >= BATCH_SIZE:
                conn.commit()
                batch_counter = 0

            if status == "indexed":
                stats.indexed += 1
            elif status == "needs_ocr":
                stats.needs_ocr += 1
            elif status == "error":
                stats.errors += 1
            elif status in ("empty", "unsupported"):
                stats.skipped += 1

        if batch_counter > 0:
            conn.commit()

    except KeyboardInterrupt:
        conn.commit()
        stats.time_taken = time.time() - start_time
        raise
    finally:
        conn.close()

    stats.time_taken = time.time() - start_time
    return stats
