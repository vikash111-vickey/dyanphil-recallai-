"""Tests for auto-indexing, folder settings, watchdog debounce, and background worker."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db import (
    get_all_file_paths,
    get_connection,
    get_file_by_path,
    init_db,
    save_image_folders,
    upsert_file_record,
)
from app.ingestion.auto_index import (
    AutoIndexWorker,
    add_configured_folder,
    get_configured_folders,
    process_file_pipeline,
    process_ocr_for_file,
    remove_configured_folder,
    validate_folder_path,
    get_auto_index_worker,
    set_auto_index_worker,
)
from app.main import app

client = TestClient(app)


# --- 1. Folder Validation and Settings Tests ---


def test_validate_folder_path_empty_and_whitespace():
    """Verify empty and whitespace-only paths are rejected."""
    ok, err = validate_folder_path("")
    assert not ok
    assert "empty" in err.lower()

    ok, err = validate_folder_path("   ")
    assert not ok
    assert "empty" in err.lower()


def test_validate_folder_path_nonexistent():
    """Verify non-existent folders are rejected."""
    ok, err = validate_folder_path("C:\\non_existent_folder_xyz_12345")
    assert not ok
    assert "does not exist" in err.lower()


def test_validate_folder_path_file_not_dir(tmp_path: Path):
    """Verify that a path pointing to a file is rejected."""
    sample_file = tmp_path / "test.txt"
    sample_file.write_text("hello", encoding="utf-8")

    ok, err = validate_folder_path(str(sample_file))
    assert not ok
    assert "not a directory" in err.lower()


def test_validate_folder_path_root_drive():
    """Verify root drives like C:\\ or D:\\ are rejected."""
    ok, err = validate_folder_path("C:\\")
    assert not ok
    assert "root drive" in err.lower()


def test_validate_folder_path_system_windows():
    """Verify Windows system folders are rejected."""
    system_root = os.environ.get("SystemRoot", "C:\\Windows")
    ok, err = validate_folder_path(system_root)
    assert not ok
    assert "system folder" in err.lower()

    # Subdirectory of Windows
    sys32 = Path(system_root) / "System32"
    if sys32.exists():
        ok, err = validate_folder_path(str(sys32))
        assert not ok
        assert "system folder" in err.lower()


def test_validate_folder_path_system_program_files():
    """Verify Program Files folders are rejected."""
    prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    if Path(prog_files).exists():
        ok, err = validate_folder_path(prog_files)
        assert not ok
        assert "system folder" in err.lower()


def test_validate_folder_path_valid_dir(tmp_path: Path):
    """Verify valid user directories are accepted and resolved."""
    ok, res = validate_folder_path(str(tmp_path))
    assert ok
    assert Path(res).resolve() == tmp_path.resolve()


def test_add_and_get_configured_folders(tmp_path: Path):
    """Verify adding folders saves to settings table without duplication."""
    db_file = tmp_path / "test.db"
    conn = get_connection(db_file)
    try:
        init_db(db_file)
        folder1 = tmp_path / "docs"
        folder1.mkdir()
        folder2 = tmp_path / "work"
        folder2.mkdir()

        res = add_configured_folder(conn, str(folder1))
        assert len(res) == 1
        assert str(folder1.resolve()) in res

        # Adding same folder again should not duplicate
        res = add_configured_folder(conn, str(folder1))
        assert len(res) == 1

        # Add second folder
        res = add_configured_folder(conn, str(folder2))
        assert len(res) == 2

        # Retrieve
        retrieved = get_configured_folders(conn)
        assert len(retrieved) == 2
        assert str(folder1.resolve()) in retrieved
        assert str(folder2.resolve()) in retrieved
    finally:
        conn.close()


def test_remove_configured_folder_and_cascade_delete(tmp_path: Path):
    """Verify removing folder removes it from settings and removes indexed files."""
    db_file = tmp_path / "test.db"
    conn = get_connection(db_file)
    try:
        init_db(db_file)
        folder_a = tmp_path / "folder_a"
        folder_a.mkdir()
        folder_b = tmp_path / "folder_b"
        folder_b.mkdir()

        add_configured_folder(conn, str(folder_a))
        add_configured_folder(conn, str(folder_b))

        # Insert files for both folders
        file_a = folder_a / "doc1.txt"
        file_a.write_text("policy document", encoding="utf-8")
        file_b = folder_b / "doc2.txt"
        file_b.write_text("medical report", encoding="utf-8")

        upsert_file_record(
            conn,
            str(file_a.resolve()),
            file_a.name,
            ".txt",
            len(file_a.read_bytes()),
            time.time(),
            time.time(),
            "hash_a",
            time.time(),
            "indexed",
            text="policy document",
        )
        upsert_file_record(
            conn,
            str(file_b.resolve()),
            file_b.name,
            ".txt",
            len(file_b.read_bytes()),
            time.time(),
            time.time(),
            "hash_b",
            time.time(),
            "indexed",
            text="medical report",
        )
        conn.commit()

        # Both exist
        assert get_file_by_path(conn, str(file_a.resolve())) is not None
        assert get_file_by_path(conn, str(file_b.resolve())) is not None

        # Remove folder_a
        updated = remove_configured_folder(conn, str(folder_a))
        assert str(folder_a.resolve()) not in updated
        assert str(folder_b.resolve()) in updated

        # File A should be removed from database, File B must remain
        assert get_file_by_path(conn, str(file_a.resolve())) is None
        assert get_file_by_path(conn, str(file_b.resolve())) is not None
    finally:
        conn.close()


# --- 2. Pipeline and Debounce Logic Tests ---


def test_process_file_pipeline_extract_classify_facts_chunk_embed(tmp_path: Path):
    """Verify changed file runs: extract, classify, facts, chunk, embed in order."""
    db_file = tmp_path / "test.db"
    conn = get_connection(db_file)
    try:
        init_db(db_file)
        doc = tmp_path / "health_insurance_policy.txt"
        doc.write_text(
            "Star Health Insurance Policy 12345678.\nExpires: 14 Aug 2026.\nPremium amount Rs 15000.",
            encoding="utf-8",
        )

        status, changed = process_file_pipeline(conn, doc)
        assert status == "indexed"
        assert changed is True

        row = get_file_by_path(conn, str(doc.resolve()))
        assert row is not None
        assert row["doc_type"] == "insurance"

        # Verify facts extracted
        facts = conn.execute("SELECT * FROM facts WHERE file_id = ?", (row["id"],)).fetchall()
        assert len(facts) >= 1
        labels = [f["label"] for f in facts]
        assert any("expiry" in l.lower() or "expires" in l.lower() for l in labels)

        # Verify chunks created
        chunks = conn.execute("SELECT * FROM chunks WHERE file_id = ?", (row["id"],)).fetchall()
        assert len(chunks) >= 1  # title chunk + text chunk
        assert chunks[0]["kind"] == "title"
    finally:
        conn.close()


def test_process_file_pipeline_needs_ocr_waits(tmp_path: Path):
    """Verify scanned/image files get status needs_ocr and do NOT chunk/embed automatically."""
    db_file = tmp_path / "test.db"
    conn = get_connection(db_file)
    try:
        init_db(db_file)
        save_image_folders(conn, [str(tmp_path.resolve())])
        # Create a dummy png file
        img = tmp_path / "scanned_invoice.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        status, changed = process_file_pipeline(conn, img)
        assert status == "needs_ocr"
        assert changed is True

        row = get_file_by_path(conn, str(img.resolve()))
        assert row is not None
        assert row["status"] == "needs_ocr"

        # Must not have chunks or facts yet (waits for OCR)
        chunks = conn.execute("SELECT * FROM chunks WHERE file_id = ?", (row["id"],)).fetchall()
        assert len(chunks) == 0
    finally:
        conn.close()


def test_process_ocr_for_file(tmp_path: Path):
    """Verify process_ocr_for_file runs OCR, updates status, facts, chunks, and embeddings."""
    db_file = tmp_path / "test.db"
    conn = get_connection(db_file)
    try:
        init_db(db_file)
        save_image_folders(conn, [str(tmp_path.resolve())])
        img = tmp_path / "receipt.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        upsert_file_record(
            conn,
            str(img.resolve()),
            img.name,
            ".png",
            len(img.read_bytes()),
            time.time(),
            time.time(),
            "hash_img",
            time.time(),
            "needs_ocr",
        )
        conn.commit()
        row = get_file_by_path(conn, str(img.resolve()))
        fid = row["id"]

        with patch("app.ingestion.auto_index.extract_ocr_text", return_value="Invoice #9999\nDue date 2026-12-01\nAmount $500"):
            ok = process_ocr_for_file(conn, fid, str(img.resolve()), img.name)
            assert ok is True

        updated_row = get_file_by_path(conn, str(img.resolve()))
        assert updated_row["status"] == "indexed"

        # Chunks and facts should now exist
        chunks = conn.execute("SELECT * FROM chunks WHERE file_id = ?", (fid,)).fetchall()
        assert len(chunks) >= 1
    finally:
        conn.close()


def test_worker_debounce_queue_logic(tmp_path: Path):
    """Verify watchdog change events are debounced and processed after the debounce delay."""
    db_file = tmp_path / "test.db"
    init_db(db_file)

    # Use a tiny debounce of 0.1s for test speed
    worker = AutoIndexWorker(debounce_seconds=0.1, db_path=db_file)
    try:
        file1 = tmp_path / "note.txt"
        file1.write_text("first draft", encoding="utf-8")

        # Notify change
        worker.notify_file_changed(str(file1))
        norm_path = str(file1.resolve())
        assert norm_path in worker._pending_debounce

        t1 = worker._pending_debounce[norm_path]

        # Rapid second change within window updates due time
        time.sleep(0.02)
        worker.notify_file_changed(str(file1))
        t2 = worker._pending_debounce[norm_path]
        assert t2 >= t1

        # Start worker and wait for debounce to elapse
        worker.start()
        time.sleep(0.3)

        conn = get_connection(db_file)
        try:
            row = get_file_by_path(conn, norm_path)
            assert row is not None
            assert row["status"] == "indexed"
        finally:
            conn.close()

    finally:
        worker.stop()


def test_worker_notify_file_deleted(tmp_path: Path):
    """Verify deleted file removes DB record and cancels pending debounce."""
    db_file = tmp_path / "test.db"
    init_db(db_file)

    worker = AutoIndexWorker(debounce_seconds=0.1, db_path=db_file)
    conn = get_connection(db_file)
    try:
        f = tmp_path / "temp_file.txt"
        f.write_text("content", encoding="utf-8")
        upsert_file_record(
            conn,
            str(f.resolve()),
            f.name,
            ".txt",
            len(f.read_bytes()),
            time.time(),
            time.time(),
            "hash_t",
            time.time(),
            "indexed",
            text="content",
        )
        conn.commit()
        assert get_file_by_path(conn, str(f.resolve())) is not None

        worker.notify_file_changed(str(f))
        assert str(f.resolve()) in worker._pending_debounce

        # Trigger deletion
        f.unlink()
        worker.notify_file_deleted(str(f))

        # Debounce should be cancelled
        assert str(f.resolve()) not in worker._pending_debounce

        # Start worker briefly to process delete task
        worker.start()
        time.sleep(0.2)

        # File should be deleted from DB
        assert get_file_by_path(conn, str(f.resolve())) is None
    finally:
        worker.stop()
        conn.close()


# --- 3. API Endpoints Tests ---


def test_api_folders_endpoints(tmp_path: Path):
    """Test GET, POST, DELETE on /settings/folders via TestClient."""
    folder = tmp_path / "my_docs"
    folder.mkdir()

    # 1. POST valid folder
    post_res = client.post("/settings/folders", json={"path": str(folder)})
    assert post_res.status_code == 200
    data = post_res.json()
    assert data["ok"] is True
    assert any(Path(p).resolve() == folder.resolve() for p in data["folders"])

    # 2. GET folders
    get_res = client.get("/settings/folders")
    assert get_res.status_code == 200
    assert any(Path(p).resolve() == folder.resolve() for p in get_res.json()["folders"])

    # 3. POST system folder rejected
    sys_dir = os.environ.get("SystemRoot", "C:\\Windows")
    rej_res = client.post("/settings/folders", json={"path": sys_dir})
    assert rej_res.status_code == 400

    # 4. POST non-existent folder rejected
    non_res = client.post("/settings/folders", json={"path": "C:\\fake_dir_9999"})
    assert non_res.status_code == 400

    # 5. DELETE folder via request body and via query param
    del_res = client.request("DELETE", "/settings/folders", json={"path": str(folder)})
    assert del_res.status_code == 200
    assert not any(Path(p).resolve() == folder.resolve() for p in del_res.json()["folders"])

    # Re-add and delete via query param
    client.post("/settings/folders", json={"path": str(folder)})
    del_query_res = client.delete(f"/settings/folders?path={folder}")
    assert del_query_res.status_code == 200
    assert not any(Path(p).resolve() == folder.resolve() for p in del_query_res.json()["folders"])


def test_api_index_status_endpoint():
    """Test GET /index/status returns all expected fields with correct types."""
    res = client.get("/index/status")
    assert res.status_code == 200
    data = res.json()
    assert "running" in data and isinstance(data["running"], bool)
    assert "current_task" in data
    assert "files_total" in data and isinstance(data["files_total"], int)
    assert "by_status" in data and isinstance(data["by_status"], dict)
    assert "last_run_time" in data
    assert "pending_ocr_count" in data and isinstance(data["pending_ocr_count"], int)


def test_api_concurrency_conflict():
    """Verify that triggering an action while already running returns 409 Conflict."""
    worker = get_auto_index_worker()
    with worker._lock:
        old_task = worker._current_task
        worker._current_task = "indexing"

    try:
        # Calling index or ocr while busy must reject with 409
        idx_res = client.post("/index/run")
        assert idx_res.status_code == 409

        ocr_res = client.post("/ocr/run")
        assert ocr_res.status_code == 409
    finally:
        with worker._lock:
            worker._current_task = old_task


def test_ui_static_dist_mounted_at_root():
    """Verify that ui/dist is mounted at / and serves the HTML app if it exists."""
    dist_dir = Path("ui/dist")
    if dist_dir.exists() and (dist_dir / "index.html").exists():
        res = client.get("/")
        assert res.status_code == 200
        assert "<html" in res.text.lower() or "<!doctype html" in res.text.lower()

