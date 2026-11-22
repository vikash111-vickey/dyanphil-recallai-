"""Command-line interface for Dyanphil indexer and search assistant."""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.db import (
    delete_chunks_by_file_id,
    delete_facts_by_file_id,
    get_connection,
    get_expiring_facts,
    get_facts_by_file_id,
    get_file_by_path,
    get_files_by_status,
    get_stats,
    init_db,
    insert_chunks_batch,
    insert_facts_batch,
    search_fts,
    update_file_classification,
    IMAGE_EXTENSIONS,
    get_excluded_folders,
    get_image_folders,
    is_path_excluded,
    is_path_in_image_folder,
)
from app.ingestion.chunker import chunk_file
from app.ingestion.classifier import classify_file
from app.ingestion.facts import extract_facts
from app.ingestion.scanner import scan_and_index
from app.search.embedder import get_embedder
from app.search.hybrid import hybrid_search
from app.security.masking import mask_all_sensitive

LAST_SEARCH_FILE = settings.data_dir / "last_search.json"


def get_terminal_width() -> int:
    """Return terminal column width safely."""
    try:
        return shutil.get_terminal_size(fallback=(80, 20)).columns
    except Exception:
        return 80


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable units."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


def handle_index(args: argparse.Namespace) -> int:
    """Handle the 'index' command with clean live progress and Ctrl+C handling."""
    folders = [Path(f) for f in args.folders]

    def on_progress(processed_count: int, current_folder: str) -> None:
        cols = get_terminal_width()
        prefix = f"[Indexing] Processed: {processed_count} files | "
        avail = max(10, cols - len(prefix) - 2)
        if len(current_folder) > avail:
            folder_display = "..." + current_folder[-(avail - 3):]
        else:
            folder_display = current_folder
        line = f"{prefix}{folder_display}"
        padded_line = line.ljust(cols - 1)[:cols - 1]
        sys.stdout.write(f"\r{padded_line}")
        sys.stdout.flush()

    try:
        stats = scan_and_index(folders, progress_callback=on_progress)
        cols = get_terminal_width()
        sys.stdout.write("\r" + " " * (cols - 1) + "\r")
        sys.stdout.flush()

        print("--- Index Summary ---")
        print(f"Scanned:           {stats.scanned}")
        print(f"Indexed:           {stats.indexed}")
        print(f"Unchanged:         {stats.unchanged}")
        print(f"Skipped:           {stats.skipped}")
        print(f"Cloud-only:        {stats.cloud_only}")
        print(f"Needs OCR:         {stats.needs_ocr}")
        print(f"Errors:            {stats.errors}")
        print(f"Permission denied: {stats.permission_denied}")
        print(f"Time taken:        {stats.time_taken:.2f}s")
        return 0

    except KeyboardInterrupt:
        cols = get_terminal_width()
        sys.stdout.write("\r" + " " * (cols - 1) + "\r")
        sys.stdout.flush()
        print("\nIndexing stopped by user (Ctrl+C). All files processed up to this point were saved.")
        return 130


EMBEDDING_BATCH_SIZE = 16


def handle_embed(args: argparse.Namespace) -> int:
    """
    Handle the 'embed' command: incremental chunk embedding with streaming from SQLite.
    Optimized for low-RAM systems (8 GB RAM):
    - Embedding batch size of 16
    - Model loaded only once (singleton)
    - Never loads all file text into memory at once (streams file by file)
    """
    start_time = time.time()
    conn = get_connection()
    try:
        init_db()
        embedder = get_embedder()
        model_name = embedder.model_name

        # 1. Clean up orphan chunks for files deleted from the files table
        conn.execute("DELETE FROM chunks WHERE file_id NOT IN (SELECT id FROM files)")
        conn.commit()

        # 2. Get total candidate file count for progress reporting without loading contents
        total_cursor = conn.execute(
            "SELECT COUNT(*) AS total FROM files WHERE status IN ('indexed', 'needs_ocr', 'empty')"
        )
        total_files = total_cursor.fetchone()["total"]

        # 3. Stream candidate files one by one (metadata only)
        file_cursor = conn.execute(
            """
            SELECT id, path, filename, status
            FROM files
            WHERE status IN ('indexed', 'needs_ocr', 'empty')
            ORDER BY id ASC
            """
        )

        chunk_buffer: list[tuple[int, int, str, str]] = []
        files_embedded_set: set[int] = set()
        chunks_embedded = 0
        processed_files = 0

        def flush_batch() -> None:
            nonlocal chunks_embedded
            if not chunk_buffer:
                return

            batch_texts = [item[3] for item in chunk_buffer]
            vectors = embedder.embed_texts(batch_texts)

            insert_data = []
            for idx, item in enumerate(chunk_buffer):
                fid, chunk_idx, kind, text = item
                emb_bytes = vectors[idx].tobytes()
                insert_data.append((fid, chunk_idx, kind, text, emb_bytes, model_name))
                files_embedded_set.add(fid)

            insert_chunks_batch(conn, insert_data)
            conn.commit()
            chunks_embedded += len(chunk_buffer)
            chunk_buffer.clear()

        try:
            for file_row in file_cursor:
                processed_files += 1
                fid = file_row["id"]
                f_path = file_row["path"]
                f_status = file_row["status"]

                # Fetch existing chunks for this single file
                cur = conn.execute(
                    "SELECT chunk_index, text FROM chunks WHERE file_id = ? AND model = ? ORDER BY chunk_index ASC",
                    (fid, model_name),
                )
                existing_rows = cur.fetchall()

                # Stream content text ONLY for this single file
                text_row = conn.execute("SELECT text FROM contents WHERE file_id = ?", (fid,)).fetchone()
                file_text = text_row["text"] if text_row else None

                # Generate chunks for this single file
                file_chunks = chunk_file(f_path, f_status, file_text)
                del file_text  # Free memory immediately

                existing_texts = [r["text"] for r in existing_rows]
                new_texts = [c.text for c in file_chunks]

                # If existing chunks match exactly, file is up to date
                if existing_rows and existing_texts == new_texts:
                    continue

                # If previous chunks existed but changed, delete old chunks before embedding new ones
                if existing_rows:
                    delete_chunks_by_file_id(conn, fid)
                    conn.commit()

                # Append this file's chunks to streaming buffer
                for c in file_chunks:
                    chunk_buffer.append((fid, c.chunk_index, c.kind, c.text))
                    if len(chunk_buffer) >= EMBEDDING_BATCH_SIZE:
                        cols = get_terminal_width()
                        line = (
                            f"[Embedding] Files: {processed_files}/{total_files} | "
                            f"Chunks embedded: {chunks_embedded} (batch: {EMBEDDING_BATCH_SIZE})"
                        )
                        padded_line = line.ljust(cols - 1)[:cols - 1]
                        sys.stdout.write(f"\r{padded_line}")
                        sys.stdout.flush()

                        flush_batch()

            # Flush any remaining chunks (< EMBEDDING_BATCH_SIZE)
            if chunk_buffer:
                cols = get_terminal_width()
                line = (
                    f"[Embedding] Files: {processed_files}/{total_files} | "
                    f"Chunks embedded: {chunks_embedded} (batch: {EMBEDDING_BATCH_SIZE})"
                )
                padded_line = line.ljust(cols - 1)[:cols - 1]
                sys.stdout.write(f"\r{padded_line}")
                sys.stdout.flush()

                flush_batch()

            # Clear progress line
            cols = get_terminal_width()
            sys.stdout.write("\r" + " " * (cols - 1) + "\r")
            sys.stdout.flush()

            elapsed = time.time() - start_time
            stats = get_stats(conn)
            print("--- Embedding Summary ---")
            if not files_embedded_set:
                print("Files embedded:    0 (all up-to-date)")
            else:
                print(f"Files embedded:    {len(files_embedded_set)}")
            print(f"Chunks embedded:   {chunks_embedded}")
            print(f"Total chunks:      {stats['chunk_count']}")
            print(f"Embedding model:   {model_name}")
            print(f"Batch size:        {EMBEDDING_BATCH_SIZE}")
            print(f"Time taken:        {elapsed:.2f}s")
            return 0

        except KeyboardInterrupt:
            conn.commit()
            cols = get_terminal_width()
            sys.stdout.write("\r" + " " * (cols - 1) + "\r")
            sys.stdout.flush()
            print("\nEmbedding stopped by user (Ctrl+C). Completed batches were saved.")
            return 130

    finally:
        conn.close()


def handle_ocr(args: argparse.Namespace) -> int:
    """
    Handle the 'ocr' command:
    - Processes only files with status 'needs_ocr', one at a time
    - Live progress line: [OCR] Files: {processed}/{total} | {filename}
    - Stores text in contents, updates FTS, sets status to indexed (or empty if no text)
    - Deletes file's old chunks so next embed command re-chunks it
    - Commits after every file so Ctrl+C is safe
    - Prints summary: processed, got text, empty, failed, time taken
    - Privacy: never prints full text, only counts
    """
    start_time = time.time()
    conn = get_connection()
    try:
        init_db()

        # Query candidate files with status needs_ocr
        sql = "SELECT id, path, filename FROM files WHERE status = 'needs_ocr' ORDER BY id ASC"
        if getattr(args, "limit", None) is not None and args.limit > 0:
            sql += f" LIMIT {int(args.limit)}"

        cursor = conn.execute(sql)
        candidates = cursor.fetchall()
        total_candidates = len(candidates)

        if total_candidates == 0:
            print("--- OCR Summary ---")
            print("Processed:         0")
            print("Got text:          0")
            print("Empty:             0")
            print("Failed:            0")
            print("Time taken:        0.00s")
            return 0

        from app.ingestion.ocr import extract_ocr_text
        from app.db import (
            IMAGE_EXTENSIONS,
            get_excluded_folders,
            get_image_folders,
            is_path_excluded,
            is_path_in_image_folder,
        )

        excluded = get_excluded_folders(conn)
        image_folders = get_image_folders(conn)

        processed = 0
        got_text = 0
        empty = 0
        failed = 0

        try:
            for row in candidates:
                fid = row["id"]
                fpath = row["path"]
                fname = row["filename"]
                p = Path(fpath)
                ext = p.suffix.lower()

                if is_path_excluded(p, excluded):
                    continue
                if ext in IMAGE_EXTENSIONS and not is_path_in_image_folder(p, image_folders):
                    continue

                processed += 1

                cols = get_terminal_width()
                line = f"[OCR] Files: {processed}/{total_candidates} | {fname}"
                padded_line = line.ljust(cols - 1)[:cols - 1]
                sys.stdout.write(f"\r{padded_line}")
                sys.stdout.flush()

                try:
                    ocr_text = extract_ocr_text(fpath).strip()
                    now = time.time()
                    if ocr_text:
                        new_status = "indexed"
                        got_text += 1
                    else:
                        new_status = "empty"
                        empty += 1

                    # 1. Update status and timestamp in files
                    conn.execute(
                        "UPDATE files SET status = ?, indexed_at = ? WHERE id = ?",
                        (new_status, now, fid),
                    )

                    # 2. Store text in contents (FTS is updated automatically via trigger)
                    conn.execute("DELETE FROM contents WHERE file_id = ?", (fid,))
                    if new_status == "indexed" and ocr_text:
                        conn.execute(
                            "INSERT INTO contents (file_id, text) VALUES (?, ?)",
                            (fid, ocr_text),
                        )

                    # 3. Run classification and fact extraction
                    doc_type, score = classify_file(fpath, fname, ocr_text)
                    update_file_classification(conn, fid, doc_type, score)
                    delete_facts_by_file_id(conn, fid)
                    if ocr_text:
                        extracted = extract_facts(ocr_text, filename=fname, path=fpath)
                        if extracted:
                            insert_facts_batch(
                                conn,
                                [
                                    (fid, f.kind, f.label, f.value, f.value_date, f.snippet)
                                    for f in extracted
                                ],
                            )

                    # 4. Delete old chunks so next embed command re-chunks it
                    delete_chunks_by_file_id(conn, fid)

                    # 5. Commit after every file so Ctrl+C is safe
                    conn.commit()

                except Exception:
                    failed += 1
                    conn.rollback()

            # Clear live progress line
            cols = get_terminal_width()
            sys.stdout.write("\r" + " " * (cols - 1) + "\r")
            sys.stdout.flush()

            elapsed = time.time() - start_time
            print("--- OCR Summary ---")
            print(f"Processed:         {processed}")
            print(f"Got text:          {got_text}")
            print(f"Empty:             {empty}")
            print(f"Failed:            {failed}")
            print(f"Time taken:        {elapsed:.2f}s")
            return 0

        except KeyboardInterrupt:
            conn.commit()
            cols = get_terminal_width()
            sys.stdout.write("\r" + " " * (cols - 1) + "\r")
            sys.stdout.flush()
            print("\nOCR stopped by user (Ctrl+C). Completed files were saved.")
            elapsed = time.time() - start_time
            print("--- OCR Summary ---")
            print(f"Processed:         {processed}")
            print(f"Got text:          {got_text}")
            print(f"Empty:             {empty}")
            print(f"Failed:            {failed}")
            print(f"Time taken:        {elapsed:.2f}s")
            return 130

    finally:
        conn.close()


def handle_classify(args: argparse.Namespace) -> int:
    """
    Handle the 'classify' command:
    - Processes files with no doc_type or changed content
    - Runs classification and fact extraction
    - Commits in batches
    - Prints summary
    """
    start_time = time.time()
    conn = get_connection()
    try:
        init_db()

        # Select files needing classification (doc_type IS NULL or empty)
        sql = "SELECT f.id, f.path, f.filename FROM files f WHERE f.doc_type IS NULL OR f.doc_type = '' ORDER BY f.id ASC"
        if getattr(args, "limit", None) is not None and args.limit > 0:
            sql += f" LIMIT {int(args.limit)}"

        candidates = conn.execute(sql).fetchall()
        total = len(candidates)
        if total == 0:
            print("--- Classification Summary ---")
            print("Processed:         0 (all up-to-date)")
            print("Facts extracted:   0")
            print("Time taken:        0.00s")
            return 0

        processed = 0
        total_facts = 0
        BATCH_SIZE = 25

        try:
            for row in candidates:
                fid = row["id"]
                fpath = row["path"]
                fname = row["filename"]
                processed += 1

                cols = get_terminal_width()
                line = f"[Classifying] Files: {processed}/{total} | {fname}"
                padded_line = line.ljust(cols - 1)[:cols - 1]
                sys.stdout.write(f"\r{padded_line}")
                sys.stdout.flush()

                # Get text from contents
                text_row = conn.execute("SELECT text FROM contents WHERE file_id = ?", (fid,)).fetchone()
                file_text = text_row["text"] if text_row else ""

                # Classify
                doc_type, score = classify_file(fpath, fname, file_text)
                update_file_classification(conn, fid, doc_type, score)

                # Extract and store facts
                delete_facts_by_file_id(conn, fid)
                if file_text:
                    extracted = extract_facts(file_text, filename=fname, path=fpath)
                    if extracted:
                        insert_facts_batch(
                            conn,
                            [
                                (fid, f.kind, f.label, f.value, f.value_date, f.snippet)
                                for f in extracted
                            ],
                        )
                        total_facts += len(extracted)

                if processed % BATCH_SIZE == 0:
                    conn.commit()

            conn.commit()

            # Clear progress line
            cols = get_terminal_width()
            sys.stdout.write("\r" + " " * (cols - 1) + "\r")
            sys.stdout.flush()

            elapsed = time.time() - start_time
            print("--- Classification Summary ---")
            print(f"Processed:         {processed}")
            print(f"Facts extracted:   {total_facts}")
            print(f"Time taken:        {elapsed:.2f}s")
            return 0

        except KeyboardInterrupt:
            conn.commit()
            cols = get_terminal_width()
            sys.stdout.write("\r" + " " * (cols - 1) + "\r")
            sys.stdout.flush()
            print("\nClassification stopped by user (Ctrl+C). Completed batches were saved.")
            return 130
    finally:
        conn.close()


def handle_facts(args: argparse.Namespace) -> int:
    """
    Handle the 'facts' command:
    - Finds file by filename or query
    - Prints that file's doc_type, score, and extracted facts
    """
    query = args.query.strip()
    if not query:
        print("Please provide a filename or search query.")
        return 1

    conn = get_connection()
    try:
        init_db()

        # 1. Search for matching file
        file_row = get_file_by_path(conn, query)
        if not file_row:
            cur = conn.execute(
                "SELECT id, path, filename, doc_type, doc_type_score FROM files WHERE filename LIKE ? OR path LIKE ? ORDER BY id ASC LIMIT 1",
                (f"%{query}%", f"%{query}%"),
            )
            file_row = cur.fetchone()

        if not file_row:
            # Try FTS
            fts_rows = search_fts(conn, query, limit=1)
            if fts_rows:
                file_row = get_file_by_path(conn, fts_rows[0]["path"])

        if not file_row:
            print(f"No file matching '{query}' found.")
            return 1

        fid = file_row["id"]
        doc_type = file_row["doc_type"] or "other"
        score = file_row["doc_type_score"] or 0.0
        fname = file_row["filename"]
        fpath = file_row["path"]

        facts = get_facts_by_file_id(conn, fid)

        print(f"File:  {fname}")
        print(f"Path:  {fpath}")
        print(f"Type:  {doc_type} (score: {score:.2f})")
        print(f"Facts ({len(facts)}):")
        if not facts:
            print("  (no facts extracted)")
        else:
            for f in facts:
                date_part = f" (Date: {f['value_date']})" if f["value_date"] else ""
                print(f"  - [{f['kind']}] {f['label']}: {f['value']}{date_part}")
                if f["snippet"]:
                    print(f"    Snippet: \"{f['snippet']}\"")
        return 0
    finally:
        conn.close()


def handle_expiring(args: argparse.Namespace) -> int:
    """
    Handle the 'expiring' command:
    - Lists files with an expiry or due date in the next N days, and already expired ones, sorted by date.
    """
    days = getattr(args, "days", 60) or 60
    conn = get_connection()
    try:
        init_db()
        items = get_expiring_facts(conn, days=days)

        if not items:
            print(f"No files with expiry or due dates found within the next {days} days.")
            return 0

        print(f"--- Expiring / Due Documents (Next {days} days & Expired: {len(items)} found) ---")
        for it in items:
            rem = it["days_remaining"]
            if rem < 0:
                status_str = f"EXPIRED ({abs(rem)} days ago: {it['value_date']})"
            elif rem == 0:
                status_str = f"EXPIRING TODAY ({it['value_date']})"
            else:
                status_str = f"DUE in {rem} days ({it['value_date']})"

            print(f"[{status_str}] {it['filename']} ({it['doc_type']})")
            print(f"  {it['label']}: {it['value']}")
            print(f"  Path: {it['path']}")
        return 0
    finally:
        conn.close()


def handle_search(args: argparse.Namespace) -> int:
    """Handle the 'search' command using hybrid, semantic, or keyword search."""
    query = args.words.strip()
    if not query:
        print("Error: Search query cannot be empty.", file=sys.stderr)
        return 1

    conn = get_connection()
    try:
        init_db()
        mode = getattr(args, "mode", "hybrid") or "hybrid"
        results = hybrid_search(conn, query, mode=mode, limit=args.limit)

        if not results:
            print(f"No results found for '{query}' (mode: {mode}).")
            if LAST_SEARCH_FILE.exists():
                try:
                    LAST_SEARCH_FILE.unlink()
                except OSError:
                    pass
            return 0

        # Save results to last_search.json for the open command
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        cached_list = [
            {"number": idx, "path": item["path"], "filename": item["filename"]}
            for idx, item in enumerate(results, start=1)
        ]
        LAST_SEARCH_FILE.write_text(json.dumps(cached_list, indent=2), encoding="utf-8")

        print(f"Found {len(results)} match(es) for '{query}' (mode: {mode}):\n")
        for item in results:
            mtime_dt = datetime.fromtimestamp(item["modified_at"]).strftime("%Y-%m-%d %H:%M:%S")
            snippet = mask_all_sensitive(item["snippet"].replace("\n", " ").strip())
            match_type = item.get("match_type", "keyword")
            print(f"{item['rank']}. {item['filename']} [{match_type}]")
            print(f"   Path:     {item['path']}")
            print(f"   Modified: {mtime_dt}")
            print(f"   Snippet:  {snippet}")
            print()

        return 0
    finally:
        conn.close()


def handle_open(args: argparse.Namespace) -> int:
    """Handle the 'open' command using a search result number."""
    if not LAST_SEARCH_FILE.exists():
        print("Error: No search results found. Please run a search first.", file=sys.stderr)
        return 1

    try:
        data = json.loads(LAST_SEARCH_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Error reading last search results: {exc}", file=sys.stderr)
        return 1

    matched_entry = None
    for entry in data:
        if entry.get("number") == args.number:
            matched_entry = entry
            break

    if not matched_entry:
        print(
            f"Error: Number {args.number} not found in recent search (1 to {len(data)}).",
            file=sys.stderr,
        )
        return 1

    file_path_str = matched_entry["path"]

    # Verify path exists in database
    conn = get_connection()
    try:
        db_record = get_file_by_path(conn, file_path_str)
        if db_record is None:
            print(
                f"Error: Path '{file_path_str}' is not registered in the database.",
                file=sys.stderr,
            )
            return 1
    finally:
        conn.close()

    # Verify file exists on disk
    target_path = Path(file_path_str)
    if not target_path.exists():
        print(f"Error: File no longer exists on disk: {file_path_str}", file=sys.stderr)
        return 1

    if args.folder:
        try:
            subprocess.run(["explorer.exe", f"/select,{str(target_path)}"], check=False)
            print(f"Opened folder with file selected: {file_path_str}")
            return 0
        except Exception as exc:
            print(f"Error opening File Explorer: {exc}", file=sys.stderr)
            return 1
    else:
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(target_path))  # type: ignore[attr-defined]
            else:
                subprocess.run(["cmd", "/c", "start", "", str(target_path)], shell=True, check=False)
            print(f"Opened file: {file_path_str}")
            return 0
        except Exception as exc:
            print(f"Error opening file: {exc}", file=sys.stderr)
            return 1


def handle_list(args: argparse.Namespace) -> int:
    """Handle the 'list' command filtering files by status."""
    conn = get_connection()
    try:
        init_db()
        rows = get_files_by_status(conn, args.status, limit=args.limit)
        if not rows:
            print(f"No files found with status '{args.status}'.")
            return 0

        for row in rows:
            print(row["path"])
            if args.status == "error" and row["error"]:
                print(f"  Error: {row['error']}")
        return 0
    finally:
        conn.close()


def handle_stats(args: argparse.Namespace) -> int:
    """Handle the 'stats' command."""
    conn = get_connection()
    try:
        init_db()
        stats = get_stats(conn)

        print(f"Total files:      {stats['total_files']}")
        print(f"Database size:    {format_size(stats['db_size_bytes'])}")
        print(f"Total chunks:     {stats['chunk_count']}")
        print(f"Embedding model:  {stats['embedding_model']}")

        print("\nFiles by status:")
        if stats["by_status"]:
            for status, count in stats["by_status"].items():
                print(f"  {status}: {count}")
        else:
            print("  (none)")

        print("\nFiles by extension:")
        if stats["by_extension"]:
            for ext, count in stats["by_extension"].items():
                print(f"  {ext}: {count}")
        else:
            print("  (none)")

        return 0
    finally:
        conn.close()


def handle_prune(args: argparse.Namespace) -> int:
    """
    Handle the 'prune' command:
    - Deletes from the index (files, contents, chunks, facts, vault entries, and FTS rows)
      every file under excluded_folders and every image not inside an image folder.
    - Runs VACUUM.
    - Prints how many files were removed by extension.
    - Never touches the real files on disk.
    """
    conn = get_connection()
    try:
        init_db()
        excluded = get_excluded_folders(conn)
        image_folders = get_image_folders(conn)

        cur = conn.execute("SELECT id, path, ext FROM files")
        rows = cur.fetchall()

        to_delete_ids: list[int] = []
        removed_by_ext: collections.Counter[str] = collections.Counter()

        for row in rows:
            file_id = row["id"]
            p_str = row["path"]
            ext = (row["ext"] or Path(p_str).suffix).lower()
            p = Path(p_str)

            should_prune = False
            if is_path_excluded(p, excluded):
                should_prune = True
            elif ext in IMAGE_EXTENSIONS and not is_path_in_image_folder(p, image_folders):
                should_prune = True

            if should_prune:
                to_delete_ids.append(file_id)
                removed_by_ext[ext] += 1

        if not to_delete_ids:
            print("--- Prune Summary ---")
            print("No files to prune. Index is clean.")
            return 0

        # Delete from all related tables
        for fid in to_delete_ids:
            conn.execute("DELETE FROM vault WHERE file_id = ?", (fid,))
            conn.execute("DELETE FROM facts WHERE file_id = ?", (fid,))
            conn.execute("DELETE FROM chunks WHERE file_id = ?", (fid,))
            conn.execute("DELETE FROM contents WHERE file_id = ?", (fid,))
            conn.execute("DELETE FROM emails WHERE file_id = ?", (fid,))
            conn.execute("DELETE FROM file_fts WHERE rowid = ?", (fid,))
            conn.execute("DELETE FROM files WHERE id = ?", (fid,))

        conn.commit()

        # Invalidate vector cache if hybrid search module is loaded
        try:
            from app.search.hybrid import invalidate_vector_cache
            invalidate_vector_cache()
        except Exception:
            pass

        # Run VACUUM to reclaim storage
        conn.execute("VACUUM;")
        conn.commit()

        total_removed = len(to_delete_ids)
        print("--- Prune Summary ---")
        print(f"Total files removed: {total_removed}")
        print("Removed by extension:")
        for ext, count in removed_by_ext.most_common():
            print(f"  {ext}: {count}")
        print("Database vacuumed successfully. Disk files untouched.")
        return 0
    finally:
        conn.close()


def handle_folders(args: argparse.Namespace) -> int:
    """
    Handle the 'folders' command:
    - Prints the indexed file count per top folder and per extension.
    """
    conn = get_connection()
    try:
        init_db()
        cur = conn.execute("SELECT path, ext FROM files")
        rows = cur.fetchall()

        if not rows:
            print("No files currently indexed in the database.")
            return 0

        folder_counter: collections.Counter[str] = collections.Counter()
        ext_counter: collections.Counter[str] = collections.Counter()

        for row in rows:
            p_str = row["path"]
            ext = (row["ext"] or Path(p_str).suffix).lower()
            ext_counter[ext] += 1

            if p_str.startswith("gmail://"):
                folder_counter["Gmail"] += 1
            else:
                clean_p = p_str.replace("/", "\\")
                parts = clean_p.split("\\")
                if len(parts) > 5:
                    top = "\\".join(parts[:5])
                elif len(parts) > 1:
                    top = "\\".join(parts[:-1])
                else:
                    top = parts[0]
                folder_counter[top] += 1

        print("--- Indexed Files by Top Folder ---")
        for folder, count in folder_counter.most_common():
            print(f"  {count:>5}  {folder}")

        print("\n--- Indexed Files by Extension ---")
        for ext, count in ext_counter.most_common():
            print(f"  {count:>5}  {ext}")

        print(f"\nTotal indexed files: {len(rows)}")
        return 0
    finally:
        conn.close()


def handle_eval(args: argparse.Namespace) -> int:
    """
    Run automated retrieval evaluation:
    - Builds up to 40 test queries from indexed files without printing file contents.
    - Tests recall@5 and MRR (Mean Reciprocal Rank).
    - Lists failed queries (query and expected filename only).
    - Writes report to data/eval_report.txt.
    """
    conn = get_connection()
    try:
        init_db()
        cur = conn.execute(
            """
            SELECT id, path, filename, doc_type
            FROM files
            WHERE status = 'indexed'
            ORDER BY id ASC
            """
        )
        files = cur.fetchall()
        if not files:
            print("No indexed files found to evaluate. Please index files first.")
            return 0

        # Build up to 40 test queries
        test_cases: list[dict[str, Any]] = []
        for f in files:
            p = Path(f["path"])
            stem = p.stem.replace("_", " ").replace("-", " ")
            stem_words = [w for w in re.findall(r"\w+", stem) if len(w) > 1]
            parent_name = p.parent.name.replace("_", " ").replace("-", " ")
            parent_words = [w for w in re.findall(r"\w+", parent_name) if len(w) > 1]
            doc_type = (f["doc_type"] or "").replace("_", " ")

            # Variant 1: filename words + doc_type (e.g. "nasa certificate")
            if stem_words and doc_type and doc_type != "other":
                q1 = f"{' '.join(stem_words[:3])} {doc_type}".strip()
                test_cases.append({
                    "query": q1,
                    "file_id": f["id"],
                    "filename": f["filename"],
                    "path": f["path"],
                })

            # Variant 2: folder name + filename words (e.g. "my certif folder pdf")
            if parent_words and stem_words:
                q2 = f"{' '.join(parent_words[:2])} {' '.join(stem_words[:2])}".strip()
                test_cases.append({
                    "query": q2,
                    "file_id": f["id"],
                    "filename": f["filename"],
                    "path": f["path"],
                })
            elif stem_words:
                q3 = " ".join(stem_words[:3]).strip()
                test_cases.append({
                    "query": q3,
                    "file_id": f["id"],
                    "filename": f["filename"],
                    "path": f["path"],
                })

            if len(test_cases) >= 40:
                break

        test_cases = test_cases[:40]

        total_queries = len(test_cases)
        hits_at_5 = 0
        sum_reciprocal_rank = 0.0
        failed_queries: list[dict[str, str]] = []

        for case in test_cases:
            q = case["query"]
            expected_id = case["file_id"]
            expected_fn = case["filename"]
            results = hybrid_search(conn, q, mode="hybrid", limit=5)

            found_rank: int | None = None
            for idx, r in enumerate(results[:5], start=1):
                r_row = get_file_by_path(conn, r["path"])
                if r_row and r_row["id"] == expected_id:
                    found_rank = idx
                    break
                elif r["path"] == case["path"]:
                    found_rank = idx
                    break

            if found_rank is not None:
                hits_at_5 += 1
                sum_reciprocal_rank += 1.0 / found_rank
            else:
                failed_queries.append({
                    "query": q,
                    "expected_filename": expected_fn,
                })

        recall_5 = hits_at_5 / total_queries if total_queries > 0 else 0.0
        mrr = sum_reciprocal_rank / total_queries if total_queries > 0 else 0.0

        # Construct report without printing any file contents
        report_lines = [
            "=== Dyanphil Search Evaluation Report ===",
            f"Evaluated At:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Total Queries:    {total_queries}",
            f"Hits@5:           {hits_at_5}",
            f"Recall@5:         {recall_5:.4f} ({recall_5 * 100:.1f}%)",
            f"MRR:              {mrr:.4f}",
            f"Failed Queries:   {len(failed_queries)}",
        ]
        if failed_queries:
            report_lines.append("\nFailed Queries (Query -> Expected Filename):")
            for fq in failed_queries:
                report_lines.append(f"  - Query: \"{fq['query']}\" -> Expected: {fq['expected_filename']}")
        else:
            report_lines.append("\nAll test queries succeeded within top 5 results!")

        report_text = "\n".join(report_lines)
        print(report_text)

        # Save to data/eval_report.txt
        eval_file = settings.data_dir / "eval_report.txt"
        eval_file.parent.mkdir(parents=True, exist_ok=True)
        eval_file.write_text(report_text, encoding="utf-8")
        print(f"\nReport saved to: {eval_file}")

        return 0
    finally:
        conn.close()


def handle_gmail(args: argparse.Namespace) -> int:
    """Handle Gmail connector CLI operations (connect, sync, status, disconnect)."""
    action = args.action
    if action == "connect":
        from app.connectors.gmail_auth import start_auth_flow
        from googleapiclient.discovery import build
        try:
            creds = start_auth_flow(open_browser=True)
            service = build("gmail", "v1", credentials=creds)
            profile = service.users().getProfile(userId="me").execute()
            user_email = profile.get("emailAddress", "")
            conn = get_connection()
            try:
                if user_email:
                    set_setting(conn, "gmail_connected_email", user_email)
            finally:
                conn.close()
            print(f"Successfully connected to Gmail: {user_email}")
            return 0
        except Exception as exc:
            print(f"Failed to connect to Gmail: {exc}", file=sys.stderr)
            return 1

    elif action == "sync":
        from app.connectors.gmail import sync_gmail
        try:
            limit = getattr(args, "limit", None)
            res = sync_gmail(max_messages_override=limit)
            print(f"Gmail sync complete. Synced: {res['synced']}, Deleted: {res['deleted']}. Email: {res.get('email', '')}")
            return 0
        except Exception as exc:
            print(f"Gmail sync failed: {exc}", file=sys.stderr)
            return 1

    elif action == "status":
        from app.connectors.gmail import get_gmail_status
        status = get_gmail_status()
        conn_str = "Connected" if status["connected"] else "Not connected"
        last_sync = (
            datetime.fromtimestamp(status["last_sync"]).strftime("%Y-%m-%d %H:%M:%S")
            if status["last_sync"]
            else "Never"
        )
        print("=== Gmail Connector Status ===")
        print(f"Status:        {conn_str}")
        print(f"Email:         {status.get('email') or 'None'}")
        print(f"Last Sync:     {last_sync}")
        print(f"Total Emails:  {status.get('message_count', 0)}")
        return 0

    elif action == "disconnect":
        from app.connectors.gmail import disconnect_gmail
        res = disconnect_gmail()
        print(f"Gmail disconnected. Deleted {res.get('deleted_count', 0)} messages from database.")
        return 0

    return 0


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint with argparse subcommands."""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Dyanphil - Local personal search assistant CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: index
    index_parser = subparsers.add_parser("index", help="Index one or more directories")
    index_parser.add_argument("folders", nargs="+", help="Folders to index")
    index_parser.set_defaults(handler=handle_index)

    # Subcommand: embed
    embed_parser = subparsers.add_parser("embed", help="Generate semantic embeddings for indexed files")
    embed_parser.set_defaults(handler=handle_embed)

    # Subcommand: ocr
    ocr_parser = subparsers.add_parser("ocr", help="Run OCR on files with status needs_ocr")
    ocr_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of files to process",
    )
    ocr_parser.set_defaults(handler=handle_ocr)

    # Subcommand: classify
    classify_parser = subparsers.add_parser("classify", help="Classify files and extract facts")
    classify_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of files to classify",
    )
    classify_parser.set_defaults(handler=handle_classify)

    # Subcommand: facts
    facts_parser = subparsers.add_parser("facts", help="Display document classification and extracted facts")
    facts_parser.add_argument("query", type=str, help="Filename or search words for the file")
    facts_parser.set_defaults(handler=handle_facts)

    # Subcommand: expiring
    expiring_parser = subparsers.add_parser("expiring", help="List files with expiry or due dates in next N days and expired ones")
    expiring_parser.add_argument(
        "--days",
        type=int,
        default=60,
        help="Lookahead days for expiry/due dates (default: 60)",
    )
    expiring_parser.set_defaults(handler=handle_expiring)

    # Subcommand: search
    search_parser = subparsers.add_parser("search", help="Search the index using hybrid, semantic, or keyword search")
    search_parser.add_argument("words", type=str, help="Search keywords or phrase")
    search_parser.add_argument(
        "--mode",
        choices=["keyword", "semantic", "hybrid"],
        default="hybrid",
        help="Search mode: hybrid (default), semantic, or keyword",
    )
    search_parser.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    search_parser.set_defaults(handler=handle_search)

    # Subcommand: open
    open_parser = subparsers.add_parser("open", help="Open a file from the last search result")
    open_parser.add_argument("number", type=int, help="Result number from the last search")
    open_parser.add_argument(
        "--folder",
        action="store_true",
        help="Open File Explorer with the file selected",
    )
    open_parser.set_defaults(handler=handle_open)

    # Subcommand: list
    list_parser = subparsers.add_parser("list", help="List files by status")
    list_parser.add_argument(
        "--status",
        choices=["error", "needs_ocr", "indexed"],
        required=True,
        help="Filter by status (error, needs_ocr, indexed)",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of files to list (default: 50)",
    )
    list_parser.set_defaults(handler=handle_list)

    # Subcommand: stats
    stats_parser = subparsers.add_parser("stats", help="Display index and database statistics")
    stats_parser.set_defaults(handler=handle_stats)

    # Subcommand: prune
    prune_parser = subparsers.add_parser(
        "prune",
        help="Deletes from the index every file under excluded_folders and every image not inside an image folder",
    )
    prune_parser.set_defaults(handler=handle_prune)

    # Subcommand: folders
    folders_parser = subparsers.add_parser(
        "folders",
        help="Print the indexed file count per top folder and per extension",
    )
    folders_parser.set_defaults(handler=handle_folders)

    # Subcommand: eval
    eval_parser = subparsers.add_parser("eval", help="Run automated retrieval evaluation (recall@5 and MRR)")
    eval_parser.set_defaults(handler=handle_eval)

    # Subcommand: gmail
    gmail_parser = subparsers.add_parser("gmail", help="Gmail connector commands")
    gmail_actions = gmail_parser.add_subparsers(dest="action", required=True)

    gmail_connect_parser = gmail_actions.add_parser("connect", help="Connect Gmail via OAuth2")
    gmail_connect_parser.set_defaults(handler=handle_gmail)

    gmail_sync_parser = gmail_actions.add_parser("sync", help="Synchronize Gmail messages incrementally")
    gmail_sync_parser.add_argument("--limit", type=int, default=None, help="Maximum messages to sync")
    gmail_sync_parser.set_defaults(handler=handle_gmail)

    gmail_status_parser = gmail_actions.add_parser("status", help="Show Gmail connection and sync status")
    gmail_status_parser.set_defaults(handler=handle_gmail)

    gmail_disconnect_parser = gmail_actions.add_parser("disconnect", help="Disconnect Gmail and delete all email data")
    gmail_disconnect_parser.set_defaults(handler=handle_gmail)

    parsed_args = parser.parse_args(argv)
    return parsed_args.handler(parsed_args)


if __name__ == "__main__":
    sys.exit(main())
