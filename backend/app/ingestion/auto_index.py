"""Auto-indexing, folder management, and background watchdog worker."""

from __future__ import annotations

import gc
import json
import logging
import os
import queue
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.db import (
    delete_chunks_by_file_id,
    delete_facts_by_file_id,
    delete_file_by_path,
    get_all_file_paths,
    get_connection,
    get_file_by_path,
    get_setting,
    init_db,
    insert_chunks_batch,
    insert_facts_batch,
    set_setting,
    update_file_classification,
    upsert_file_record,
    DEFAULT_EXCLUDED_FOLDER_NAMES,
    IMAGE_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    get_default_excluded_folders,
    get_excluded_folders,
    save_excluded_folders,
    get_image_folders,
    save_image_folders,
    is_path_excluded,
    is_path_in_image_folder,
)
from app.ingestion.chunker import chunk_file
from app.ingestion.classifier import classify_file
from app.ingestion.extractors import SUPPORTED_EXTENSIONS, extract_text
from app.ingestion.facts import extract_facts
from app.ingestion.ocr import extract_ocr_text
from app.ingestion.scanner import (
    MAX_FILE_SIZE_BYTES,
    SKIP_DIR_NAMES,
    compute_sha256,
    is_cloud_only,
    is_permission_error,
    should_ignore_file,
    walk_directory,
    IndexStats,
)
from app.search.embedder import get_embedder

logger = logging.getLogger(__name__)


def validate_folder_path(path_str: str) -> tuple[bool, str]:
    """
    Validate folder path for index configuration.
    Rejects:
    - Non-existent paths or non-directories
    - Root drive anchors (e.g. C:\\, D:\\)
    - Windows system directories (C:\\Windows, Program Files, ProgramData, AppData, etc.)
    - Special system volumes ($Recycle.Bin, System Volume Information)
    Returns:
    - (True, resolved_path_str) if valid
    - (False, error_reason) if rejected
    """
    if not path_str or not str(path_str).strip():
        return False, "Folder path cannot be empty."

    clean = str(path_str).strip().strip('"').strip("'")
    target = Path(clean)

    try:
        if not target.exists():
            return False, f"Folder does not exist: {clean}"
        if not target.is_dir():
            return False, f"Path is not a directory: {clean}"
    except Exception as exc:
        return False, f"Cannot access path: {exc}"

    try:
        resolved = target.resolve()
    except Exception as exc:
        return False, f"Cannot resolve path: {exc}"

    # Reject root drive directly (e.g. C:\ or D:\)
    if resolved.parent == resolved or len(resolved.parts) <= 1 or resolved == Path(resolved.anchor):
        return False, f"Indexing root drive directly is not permitted: {resolved}"

    # Gather system root paths to protect
    system_roots: list[Path] = []
    for env_var in ("SystemRoot", "windir"):
        val = os.environ.get(env_var)
        if val:
            try:
                system_roots.append(Path(val).resolve())
            except Exception:
                pass
    if not system_roots:
        system_roots.append(Path("C:\\Windows").resolve())

    for env_var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        val = os.environ.get(env_var)
        if val:
            try:
                system_roots.append(Path(val).resolve())
            except Exception:
                pass
    if len(system_roots) <= 1:
        system_roots.append(Path("C:\\Program Files").resolve())
        system_roots.append(Path("C:\\Program Files (x86)").resolve())

    val = os.environ.get("ProgramData")
    if val:
        try:
            system_roots.append(Path(val).resolve())
        except Exception:
            pass
    else:
        system_roots.append(Path("C:\\ProgramData").resolve())

    for sys_root in system_roots:
        try:
            if resolved == sys_root or resolved.is_relative_to(sys_root):
                return False, f"Indexing system folder is not permitted: {resolved}"
        except (ValueError, TypeError):
            continue

    # Special volume names in any part
    blocked_part_names = {"$recycle.bin", "system volume information"}
    for part in resolved.parts:
        if part.lower() in blocked_part_names:
            return False, f"Indexing system volume or recycle bin is not permitted: {resolved}"

    return True, str(resolved)


def get_configured_folders(conn: sqlite3.Connection) -> list[str]:
    """Retrieve the list of configured index folders from settings table."""
    raw = get_setting(conn, "folders")
    if not raw:
        return []
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return [str(p) for p in val]
    except Exception:
        pass
    return []


def save_configured_folders(conn: sqlite3.Connection, folders: list[str]) -> None:
    """Save the list of configured index folders to settings table."""
    set_setting(conn, "folders", json.dumps(folders))


def add_configured_folder(conn: sqlite3.Connection, folder_path: str) -> list[str]:
    """
    Validate and add a folder to the indexed folders list.
    Raises ValueError if validation fails.
    """
    valid, res = validate_folder_path(folder_path)
    if not valid:
        raise ValueError(res)

    norm_new = os.path.normcase(os.path.normpath(res))
    current = get_configured_folders(conn)
    for existing in current:
        if os.path.normcase(os.path.normpath(existing)) == norm_new:
            return current

    current.append(res)
    save_configured_folders(conn, current)
    return current


def remove_configured_folder(conn: sqlite3.Connection, folder_path: str) -> list[str]:
    """
    Remove a folder from the indexed folders list and delete all its files from the index.
    """
    clean = folder_path.strip().strip('"').strip("'")
    norm_target = os.path.normcase(os.path.normpath(clean))

    current = get_configured_folders(conn)
    updated = [
        f for f in current
        if os.path.normcase(os.path.normpath(f)) != norm_target
    ]
    save_configured_folders(conn, updated)

    # Delete files belonging to this folder from the database
    norm_prefix = norm_target if norm_target.endswith(("\\", "/")) else norm_target + os.sep
    all_paths = get_all_file_paths(conn)
    for p in all_paths:
        norm_p = os.path.normcase(os.path.normpath(p))
        if norm_p == norm_target or norm_p.startswith(os.path.normcase(norm_prefix)):
            delete_file_by_path(conn, p)

    conn.commit()
    return updated


def add_excluded_folder(conn: sqlite3.Connection, folder_path: str) -> list[str]:
    """
    Add a folder name or path to the excluded folders list and remove any currently indexed files under it.
    """
    clean = folder_path.strip().strip('"').strip("'")
    if not clean:
        raise ValueError("Excluded folder cannot be empty.")

    current = get_excluded_folders(conn)
    norm_clean = os.path.normcase(os.path.normpath(clean))
    for existing in current:
        if os.path.normcase(os.path.normpath(existing)) == norm_clean or existing.lower() == clean.lower():
            return current

    current.append(clean)
    save_excluded_folders(conn, current)

    # Delete existing indexed files matching this excluded folder
    all_paths = get_all_file_paths(conn)
    for p in all_paths:
        if is_path_excluded(Path(p), [clean]):
            delete_file_by_path(conn, p)
    conn.commit()

    return current


def remove_excluded_folder(conn: sqlite3.Connection, folder_path: str) -> list[str]:
    """
    Remove a folder name or path from the excluded folders list.
    """
    clean = folder_path.strip().strip('"').strip("'")
    norm_target = os.path.normcase(os.path.normpath(clean))

    current = get_excluded_folders(conn)
    updated = [
        f for f in current
        if os.path.normcase(os.path.normpath(f)) != norm_target and f.lower() != clean.lower()
    ]
    save_excluded_folders(conn, updated)
    return updated


def add_image_folder(conn: sqlite3.Connection, folder_path: str) -> list[str]:
    """
    Validate and add a folder to the image folders list.
    Raises ValueError if validation fails.
    """
    valid, res = validate_folder_path(folder_path)
    if not valid:
        raise ValueError(res)

    norm_new = os.path.normcase(os.path.normpath(res))
    current = get_image_folders(conn)
    for existing in current:
        if os.path.normcase(os.path.normpath(existing)) == norm_new:
            return current

    current.append(res)
    save_image_folders(conn, current)
    return current


def remove_image_folder(conn: sqlite3.Connection, folder_path: str) -> list[str]:
    """
    Remove a folder from the image folders list and delete images that are no longer in any image folder.
    """
    clean = folder_path.strip().strip('"').strip("'")
    norm_target = os.path.normcase(os.path.normpath(clean))

    current = get_image_folders(conn)
    updated = [
        f for f in current
        if os.path.normcase(os.path.normpath(f)) != norm_target
    ]
    save_image_folders(conn, updated)

    # Delete images in the database that are under the removed folder and not in other image folders
    all_paths = get_all_file_paths(conn)
    for p in all_paths:
        p_obj = Path(p)
        if p_obj.suffix.lower() in IMAGE_EXTENSIONS:
            if not is_path_in_image_folder(p_obj, updated):
                delete_file_by_path(conn, p)
    conn.commit()

    return updated


def is_ignored_path(
    p: Path,
    configured_folders: list[str] | None = None,
    excluded_folders: list[str] | None = None,
    image_folders: list[str] | None = None,
) -> bool:
    """Check if a file path should be ignored by scanner or watcher rules."""
    if p.name.startswith(".") or should_ignore_file(p.name):
        return True

    if is_path_excluded(p, excluded_folders):
        return True

    if image_folders is not None:
        ext = p.suffix.lower()
        if ext in IMAGE_EXTENSIONS and not is_path_in_image_folder(p, image_folders):
            return True

    if configured_folders:
        for conf in configured_folders:
            try:
                rel = p.resolve().relative_to(Path(conf).resolve())
                for part in rel.parts[:-1]:
                    if part.startswith(".") or part.lower() in SKIP_DIR_NAMES:
                        return True
                return False
            except (ValueError, TypeError):
                continue

    # Fallback: check only generic skip folders if configured roots are unspecified
    for part in p.parts[:-1]:
        part_lower = part.lower()
        if part.startswith(".") or part_lower in {
            ".venv",
            "node_modules",
            ".git",
            "__pycache__",
            "$recycle.bin",
            "system volume information",
        }:
            return True

    return False


def process_file_pipeline(
    conn: sqlite3.Connection,
    file_path: Path,
    embedder: Any = None,
) -> tuple[str, bool]:
    """
    Process a single changed file through the full pipeline:
    extract -> classify -> facts -> chunk -> embed, in that order, one file at a time.
    Scanned files (needs_ocr) are indexed with status 'needs_ocr' and wait for OCR button.
    Returns (status, changed_flag).
    """
    path_str = str(file_path.resolve())

    # If file no longer exists, remove from DB
    if not file_path.exists():
        deleted = delete_file_by_path(conn, path_str)
        conn.commit()
        return "deleted", deleted

    # Suffix check
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return "unsupported", False

    # Check excluded folders and image folders policy
    excluded = get_excluded_folders(conn)
    if is_path_excluded(file_path, excluded):
        return "ignored", False

    ext = file_path.suffix.lower()
    if ext in IMAGE_EXTENSIONS and not is_path_in_image_folder(file_path, get_image_folders(conn)):
        return "ignored", False

    # Ignore rules
    conf_folders = get_configured_folders(conn)
    image_folders = get_image_folders(conn)
    if is_ignored_path(file_path, conf_folders, excluded, image_folders):
        return "ignored", False

    # Stat checks
    try:
        stat = file_path.stat()
        file_size = stat.st_size
        mtime = stat.st_mtime
        ctime = stat.st_ctime
    except Exception as exc:
        if is_permission_error(exc):
            return "permission_denied", False
        return "error", False

    if is_cloud_only(stat):
        return "cloud_only", False

    if file_size > MAX_FILE_SIZE_BYTES:
        return "skipped_too_large", False

    # Check if unchanged
    existing = get_file_by_path(conn, path_str)
    if existing is not None:
        size_match = existing["size"] == file_size
        mtime_match = abs(existing["modified_at"] - mtime) < 1e-4
        if size_match and mtime_match:
            return "unchanged", False

    # Compute hash
    content_hash = None
    try:
        content_hash = compute_sha256(file_path)
    except Exception:
        pass

    # 1. extract
    status, text, err = extract_text(file_path)

    file_id = upsert_file_record(
        conn=conn,
        path=path_str,
        filename=file_path.name,
        ext=file_path.suffix.lower(),
        size=file_size,
        created_at=ctime,
        modified_at=mtime,
        content_hash=content_hash,
        indexed_at=time.time(),
        status=status,
        error=err,
        text=text if status == "indexed" else None,
    )
    conn.commit()

    # Scanned files (needs_ocr) are NOT processed automatically; they wait for the OCR button.
    if status == "needs_ocr":
        return "needs_ocr", True

    if status != "indexed" or not file_id:
        return status, True

    # 2. classify
    doc_type, score = classify_file(path_str, file_path.name, text or "")
    update_file_classification(conn, file_id, doc_type, score)

    # 3. facts
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

    # 4. chunk
    delete_chunks_by_file_id(conn, file_id)
    chunks = chunk_file(path_str, "indexed", text or "")

    # 5. embed
    if chunks:
        if embedder is None:
            embedder = get_embedder()
        chunk_texts = [c.text for c in chunks]
        vectors = embedder.embed_texts(chunk_texts)
        chunk_data = [
            (file_id, c.chunk_index, c.kind, c.text, vectors[i].tobytes(), embedder.model_name)
            for i, c in enumerate(chunks)
        ]
        insert_chunks_batch(conn, chunk_data)

    conn.commit()

    # Free memory
    del text
    del chunks
    if "vectors" in locals():
        del vectors
    gc.collect()

    return "indexed", True


def process_ocr_for_file(
    conn: sqlite3.Connection,
    file_id: int,
    path_str: str,
    filename: str,
    embedder: Any = None,
) -> bool:
    """
    Run OCR on a pending file, update record, classify, facts, chunk, and embed.
    Commits and frees memory.
    """
    target = Path(path_str)
    if not target.exists():
        delete_file_by_path(conn, path_str)
        conn.commit()
        return False

    excluded = get_excluded_folders(conn)
    if is_path_excluded(target, excluded):
        return False

    ext = target.suffix.lower()
    if ext in IMAGE_EXTENSIONS and not is_path_in_image_folder(target, get_image_folders(conn)):
        return False

    ocr_text = extract_ocr_text(target)
    if ocr_text and ocr_text.strip():
        conn.execute(
            "UPDATE files SET status = 'indexed', error = NULL WHERE id = ?",
            (file_id,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO contents (file_id, text) VALUES (?, ?)",
            (file_id, ocr_text),
        )

        doc_type, score = classify_file(path_str, filename, ocr_text)
        update_file_classification(conn, file_id, doc_type, score)

        delete_facts_by_file_id(conn, file_id)
        extracted = extract_facts(ocr_text, filename=filename, path=path_str)
        if extracted:
            insert_facts_batch(
                conn,
                [
                    (file_id, f.kind, f.label, f.value, f.value_date, f.snippet)
                    for f in extracted
                ],
            )

        delete_chunks_by_file_id(conn, file_id)
        chunks = chunk_file(path_str, "indexed", ocr_text)
        if chunks:
            if embedder is None:
                embedder = get_embedder()
            chunk_texts = [c.text for c in chunks]
            vectors = embedder.embed_texts(chunk_texts)
            chunk_data = [
                (file_id, c.chunk_index, c.kind, c.text, vectors[i].tobytes(), embedder.model_name)
                for i, c in enumerate(chunks)
            ]
            insert_chunks_batch(conn, chunk_data)

        conn.commit()
        del ocr_text
        del chunks
        if "vectors" in locals():
            del vectors
        gc.collect()
        return True
    else:
        conn.execute(
            "UPDATE files SET status = 'empty' WHERE id = ?",
            (file_id,),
        )
        delete_chunks_by_file_id(conn, file_id)
        conn.commit()
        return False


class AutoIndexWorker:
    """
    Background worker managing auto-indexing and watchdog file monitoring.
    - Single background thread with a task queue
    - Watchdog observer for configured folders
    - Debounces file changes by 10s (configurable)
    - Processes one file at a time (extract, classify, facts, chunk, embed)
    - Never runs two heavy jobs at the same time
    """

    def __init__(
        self,
        debounce_seconds: float = 10.0,
        db_path: Path | str | None = None,
    ) -> None:
        self.debounce_seconds = debounce_seconds
        self.db_path = db_path
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._task_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._pending_debounce: dict[str, float] = {}  # norm_path -> run_at_timestamp
        self._lock = threading.Lock()
        self._observer: Any = None
        self._watches: dict[str, Any] = {}
        self._current_task: str | None = None
        self._last_run_time: str | None = None

    def is_running(self) -> bool:
        """Check if a background task or batch pipeline is currently active."""
        with self._lock:
            return self._current_task is not None

    def current_task(self) -> str | None:
        """Return the name of the currently running task, or None if idle."""
        with self._lock:
            return self._current_task

    def notify_file_changed(self, file_path_str: str) -> None:
        """Register a created or modified file event for debouncing."""
        p = Path(file_path_str)
        if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return

        with self._lock:
            watched = list(self._watches.keys())

        conn = get_connection(self.db_path)
        try:
            excluded = get_excluded_folders(conn)
            image_folders = get_image_folders(conn)
        except Exception:
            excluded = None
            image_folders = None
        finally:
            conn.close()

        if is_ignored_path(p, watched, excluded, image_folders):
            return

        resolved_str = str(p.resolve())
        with self._lock:
            self._pending_debounce[resolved_str] = time.time() + self.debounce_seconds

    def notify_file_deleted(self, file_path_str: str) -> None:
        """Register a deleted file event."""
        resolved_str = str(Path(file_path_str).resolve())
        with self._lock:
            if resolved_str in self._pending_debounce:
                del self._pending_debounce[resolved_str]
        self._task_queue.put(("delete_file", resolved_str))

    def enqueue_index(self) -> bool:
        """Enqueue full incremental scan. Returns False if already busy."""
        with self._lock:
            if self._current_task is not None:
                return False
            self._current_task = "indexing"
        self._task_queue.put(("full_index", None))
        return True

    def enqueue_ocr(self) -> bool:
        """Enqueue OCR batch run for pending scanned files. Returns False if already busy."""
        with self._lock:
            if self._current_task is not None:
                return False
            self._current_task = "ocr"
        self._task_queue.put(("ocr_run", None))
        return True

    def enqueue_gmail_sync(self) -> bool:
        """Enqueue Gmail sync task. Returns False if already busy."""
        with self._lock:
            if self._current_task is not None:
                return False
            self._current_task = "gmail_sync"
        self._task_queue.put(("gmail_sync", None))
        return True

    def update_watches(self) -> None:
        """Signal worker to update watchdog observer watches for configured folders."""
        self._task_queue.put(("update_watches", None))

    def get_status(self) -> dict[str, Any]:
        """Return comprehensive indexer and background worker status."""
        conn = get_connection(self.db_path)
        try:
            init_db(self.db_path)
            rows = conn.execute("SELECT status, COUNT(*) AS cnt FROM files GROUP BY status").fetchall()
            by_status = {r["status"]: r["cnt"] for r in rows}
            files_total = sum(by_status.values())
            pending_ocr_count = by_status.get("needs_ocr", 0)
            last_run = self._last_run_time or get_setting(conn, "last_run_time")
            return {
                "running": self.is_running(),
                "current_task": self.current_task(),
                "files_total": files_total,
                "by_status": by_status,
                "last_run_time": last_run,
                "pending_ocr_count": pending_ocr_count,
            }
        finally:
            conn.close()

    def start(self) -> None:
        """Start the background worker thread and watchdog observer."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="AutoIndexWorker")
        self._thread.start()
        self._start_watchdog()

    def stop(self) -> None:
        """Stop background worker thread and watchdog observer cleanly."""
        self._stop_event.set()
        self._stop_watchdog()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _start_watchdog(self) -> None:
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class _Handler(FileSystemEventHandler):
                def __init__(h_self, w: AutoIndexWorker):
                    h_self.w = w

                def on_created(h_self, event):
                    if not event.is_directory:
                        h_self.w.notify_file_changed(event.src_path)

                def on_modified(h_self, event):
                    if not event.is_directory:
                        h_self.w.notify_file_changed(event.src_path)

                def on_moved(h_self, event):
                    if not event.is_directory:
                        h_self.w.notify_file_deleted(event.src_path)
                        h_self.w.notify_file_changed(event.dest_path)

                def on_deleted(h_self, event):
                    if not event.is_directory:
                        h_self.w.notify_file_deleted(event.src_path)

            self._observer = Observer()
            self._watchdog_handler = _Handler(self)
            self._sync_watches()
            self._observer.start()
        except Exception as exc:
            logger.warning("Could not start watchdog observer: %s", exc)
            self._observer = None

    def _stop_watchdog(self) -> None:
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception:
                pass
            self._observer = None
            self._watches.clear()

    def _sync_watches(self) -> None:
        if self._observer is None:
            return
        conn = get_connection(self.db_path)
        try:
            folders = get_configured_folders(conn)
        finally:
            conn.close()

        # Unschedule existing watches
        for watch in list(self._watches.values()):
            try:
                self._observer.unschedule(watch)
            except Exception:
                pass
        self._watches.clear()

        # Schedule configured folders
        for folder_str in folders:
            p = Path(folder_str)
            if p.exists() and p.is_dir():
                try:
                    watch = self._observer.schedule(
                        self._watchdog_handler,
                        str(p.resolve()),
                        recursive=True,
                    )
                    self._watches[folder_str] = watch
                except Exception as exc:
                    logger.warning("Failed to watch folder %s: %s", folder_str, exc)

    def _worker_loop(self) -> None:
        """Main loop of the single-threaded worker."""
        while not self._stop_event.is_set():
            try:
                # 1. Process expired debounced files
                ready_paths: list[str] = []
                now = time.time()
                with self._lock:
                    for p_str, due_time in list(self._pending_debounce.items()):
                        if now >= due_time:
                            ready_paths.append(p_str)
                            del self._pending_debounce[p_str]

                if ready_paths:
                    with self._lock:
                        if self._current_task is None:
                            self._current_task = "indexing"

                    conn = get_connection(self.db_path)
                    try:
                        embedder = get_embedder()
                        for p_str in ready_paths:
                            if self._stop_event.is_set():
                                break
                            process_file_pipeline(conn, Path(p_str), embedder)
                    finally:
                        conn.close()
                        with self._lock:
                            if self._current_task == "indexing" and self._task_queue.empty():
                                self._current_task = None
                                self._record_run_time()

                # 2. Check task queue
                try:
                    task_name, payload = self._task_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                if task_name == "full_index":
                    self._run_full_index()
                elif task_name == "ocr_run":
                    self._run_ocr_batch()
                elif task_name == "gmail_sync":
                    self._run_gmail_sync()
                elif task_name == "delete_file":
                    self._delete_file_from_index(payload)
                elif task_name == "update_watches":
                    self._sync_watches()

                self._task_queue.task_done()

            except Exception as exc:
                logger.error("AutoIndexWorker loop error: %s", exc, exc_info=True)
                with self._lock:
                    self._current_task = None
                time.sleep(0.5)

    def _delete_file_from_index(self, path_str: str) -> None:
        conn = get_connection(self.db_path)
        try:
            delete_file_by_path(conn, path_str)
            conn.commit()
        finally:
            conn.close()

    def _run_full_index(self) -> None:
        with self._lock:
            self._current_task = "indexing"

        conn = get_connection(self.db_path)
        try:
            init_db(self.db_path)
            folders = get_configured_folders(conn)
            excluded = get_excluded_folders(conn)
            image_folders = get_image_folders(conn)
            resolved_folders = [Path(f).resolve() for f in folders if Path(f).exists() and Path(f).is_dir()]

            # 1. Discover all candidate files
            stats = IndexStats()
            candidate_files: list[Path] = []
            for folder in resolved_folders:
                if self._stop_event.is_set():
                    break
                if is_path_excluded(folder, excluded):
                    continue
                for fp in walk_directory(folder, stats, excluded_folders=excluded, image_folders=image_folders):
                    candidate_files.append(fp)

            scanned_paths_set = {str(p.resolve()) for p in candidate_files}

            # 2. Cleanup files in DB that no longer exist or are removed from configured folders
            all_db_paths = get_all_file_paths(conn)
            for recorded_path in all_db_paths:
                if self._stop_event.is_set():
                    break
                rec_p = Path(recorded_path)
                if should_ignore_file(rec_p.name) or is_path_excluded(rec_p, excluded):
                    delete_file_by_path(conn, recorded_path)
                    continue

                if rec_p.suffix.lower() in IMAGE_EXTENSIONS and not is_path_in_image_folder(rec_p, image_folders):
                    delete_file_by_path(conn, recorded_path)
                    continue

                is_under = False
                for folder_root in resolved_folders:
                    try:
                        if rec_p.is_relative_to(folder_root):
                            is_under = True
                            break
                    except ValueError:
                        continue

                if is_under:
                    if not rec_p.exists() or str(rec_p.resolve()) not in scanned_paths_set:
                        delete_file_by_path(conn, recorded_path)

            conn.commit()

            # 3. Process candidate files one by one
            embedder = get_embedder()
            for fp in candidate_files:
                if self._stop_event.is_set():
                    break
                process_file_pipeline(conn, fp, embedder)

        finally:
            conn.close()
            with self._lock:
                self._current_task = None
            self._record_run_time()

    def _run_ocr_batch(self) -> None:
        with self._lock:
            self._current_task = "ocr"

        conn = get_connection(self.db_path)
        try:
            init_db(self.db_path)
            rows = conn.execute(
                "SELECT id, path, filename FROM files WHERE status = 'needs_ocr' ORDER BY id ASC"
            ).fetchall()
            embedder = get_embedder()

            for r in rows:
                if self._stop_event.is_set():
                    break
                process_ocr_for_file(
                    conn=conn,
                    file_id=r["id"],
                    path_str=r["path"],
                    filename=r["filename"],
                    embedder=embedder,
                )
        finally:
            conn.close()
            with self._lock:
                self._current_task = None
            self._record_run_time()

    def _run_gmail_sync(self) -> None:
        with self._lock:
            self._current_task = "gmail_sync"

        try:
            from app.connectors.gmail import sync_gmail
            sync_gmail(db_path=self.db_path)
        except Exception as exc:
            logger.error("Gmail sync background job failed: %s", exc, exc_info=True)
        finally:
            with self._lock:
                self._current_task = None
            self._record_run_time()

    def _record_run_time(self) -> None:
        now_str = datetime.now().isoformat()
        self._last_run_time = now_str
        conn = get_connection(self.db_path)
        try:
            set_setting(conn, "last_run_time", now_str)
        finally:
            conn.close()


# Global worker singleton
_worker_instance: AutoIndexWorker | None = None


def get_auto_index_worker(
    debounce_seconds: float = 10.0,
    db_path: Path | str | None = None,
) -> AutoIndexWorker:
    """Retrieve or create the global AutoIndexWorker singleton."""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = AutoIndexWorker(debounce_seconds=debounce_seconds, db_path=db_path)
    return _worker_instance


def set_auto_index_worker(worker: AutoIndexWorker | None) -> None:
    """Set or override global AutoIndexWorker instance (useful for tests)."""
    global _worker_instance
    _worker_instance = worker
