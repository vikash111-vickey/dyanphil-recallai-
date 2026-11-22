"""Tests for excluded folders, image folders, CLI prune/folders, and search ranking image policies."""

import argparse
import io
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from app.db import (
    DEFAULT_EXCLUDED_FOLDER_NAMES,
    DOCUMENT_EXTENSIONS,
    IMAGE_EXTENSIONS,
    get_connection,
    get_default_excluded_folders,
    get_excluded_folders,
    get_image_folders,
    init_db,
    is_path_excluded,
    is_path_in_image_folder,
    save_excluded_folders,
    save_image_folders,
    upsert_file_record,
)
from app.ingestion.auto_index import (
    add_excluded_folder,
    add_image_folder,
    is_ignored_path,
    process_file_pipeline,
    remove_excluded_folder,
    remove_image_folder,
)
from app.ingestion.scanner import scan_and_index, walk_directory, IndexStats
from app.search.hybrid import (
    apply_image_search_policy,
    is_image_result,
    query_has_image_word,
)
from app.cli import handle_folders, handle_prune


@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_rules.db"
    init_db(db_file)
    return db_file


# ─────────────────────────────────────────────────────────────────────────────
# 1. Settings Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_default_excluded_folders(test_db: Path):
    conn = get_connection(test_db)
    try:
        defaults = get_excluded_folders(conn)
        assert isinstance(defaults, list)
        lower_defaults = [d.lower() for d in defaults]
        assert "pictures" in lower_defaults
        assert "photos" in lower_defaults
        assert "camera roll" in lower_defaults
        assert "screenshots" in lower_defaults
        assert "saved pictures" in lower_defaults
        assert any("pictures" in d.lower() for d in defaults)
    finally:
        conn.close()


def test_image_folders_default_empty(test_db: Path):
    conn = get_connection(test_db)
    try:
        image_folders = get_image_folders(conn)
        assert image_folders == []
    finally:
        conn.close()


def test_add_and_remove_excluded_folder(test_db: Path, tmp_path: Path):
    conn = get_connection(test_db)
    try:
        custom_folder = str(tmp_path / "MyPrivateArchive")
        updated = add_excluded_folder(conn, custom_folder)
        assert custom_folder in updated

        # Check persistence
        loaded = get_excluded_folders(conn)
        assert custom_folder in loaded

        # Remove
        after_remove = remove_excluded_folder(conn, custom_folder)
        assert custom_folder not in after_remove
    finally:
        conn.close()


def test_add_and_remove_image_folder(test_db: Path, tmp_path: Path):
    conn = get_connection(test_db)
    try:
        valid_dir = tmp_path / "ReceiptScans"
        valid_dir.mkdir(parents=True, exist_ok=True)

        updated = add_image_folder(conn, str(valid_dir))
        assert str(valid_dir.resolve()) in [str(Path(p).resolve()) for p in updated]

        # Check persistence
        loaded = get_image_folders(conn)
        assert len(loaded) == 1

        # Remove
        after_remove = remove_image_folder(conn, str(valid_dir))
        assert after_remove == []
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Path Matching Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_is_path_excluded():
    # Folder names in path
    assert is_path_excluded(r"C:\Users\test\OneDrive\Pictures\photo.jpg") is True
    assert is_path_excluded(r"D:\Data\Camera Roll\pic.png") is True
    assert is_path_excluded(r"C:\Users\test\Desktop\Screenshots\shot.png") is True
    assert is_path_excluded(r"D:\Photos\vacation.jpeg") is True
    assert is_path_excluded(r"D:\Documents\Saved Pictures\image.png") is True

    # Normal document paths not excluded
    assert is_path_excluded(r"D:\prompteng\testdocs\budget.csv") is False
    assert is_path_excluded(r"C:\Users\test\Documents\passport.pdf") is False

    # Custom excluded path
    custom_excluded = [r"D:\SecretVault"]
    assert is_path_excluded(r"D:\SecretVault\doc.pdf", custom_excluded) is True
    assert is_path_excluded(r"D:\Other\doc.pdf", custom_excluded) is False


def test_is_path_in_image_folder(tmp_path: Path):
    img_dir = tmp_path / "AllowedImages"
    img_dir.mkdir(parents=True, exist_ok=True)

    allowed = [str(img_dir)]
    test_img = img_dir / "invoice_scan.png"
    outside_img = tmp_path / "Other" / "photo.jpg"

    assert is_path_in_image_folder(test_img, allowed) is True
    assert is_path_in_image_folder(outside_img, allowed) is False
    assert is_path_in_image_folder(test_img, []) is False


# ─────────────────────────────────────────────────────────────────────────────
# 3. Scanner & Ingestion Rules Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_scanner_skips_excluded_and_non_whitelisted_images(test_db: Path, tmp_path: Path):
    scan_root = tmp_path / "ScanRoot"
    scan_root.mkdir()

    # 1. Valid document in scan root
    doc1 = scan_root / "contract.pdf"
    doc1.write_text("Contract agreement details", encoding="utf-8")

    # 2. Document inside an excluded folder (Pictures)
    pics_dir = scan_root / "Pictures"
    pics_dir.mkdir()
    doc_in_pics = pics_dir / "should_skip_doc.txt"
    doc_in_pics.write_text("Do not index", encoding="utf-8")
    img_in_pics = pics_dir / "skip_photo.jpg"
    img_in_pics.write_bytes(b"\xff\xd8\xff\xe0")

    # 3. Image in scan root, but NOT in image_folders
    orphan_img = scan_root / "screenshot.png"
    orphan_img.write_bytes(b"\x89PNG\r\n\x1a\n")

    # 4. Image inside an authorized image folder
    img_folder = scan_root / "Receipts"
    img_folder.mkdir()
    allowed_img = img_folder / "valid_receipt.png"
    allowed_img.write_bytes(b"\x89PNG\r\n\x1a\n")

    conn = get_connection(test_db)
    try:
        # Configure image_folders with img_folder
        save_image_folders(conn, [str(img_folder.resolve())])
        save_excluded_folders(conn, get_default_excluded_folders())
    finally:
        conn.close()

    # Run scanner
    stats = scan_and_index([scan_root], db_path=test_db)

    conn = get_connection(test_db)
    try:
        cur = conn.execute("SELECT filename, path FROM files")
        indexed_files = {row["filename"]: row["path"] for row in cur.fetchall()}

        # contract.pdf must be indexed
        assert "contract.pdf" in indexed_files

        # valid_receipt.png must be indexed because it is in image_folders
        assert "valid_receipt.png" in indexed_files

        # Everything in Pictures must NOT be indexed
        assert "should_skip_doc.txt" not in indexed_files
        assert "skip_photo.jpg" not in indexed_files

        # screenshot.png in root must NOT be indexed because it is not in image_folders
        assert "screenshot.png" not in indexed_files
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 4. CLI Prune & Folders Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_cli_prune(test_db: Path, tmp_path: Path):
    scan_root = tmp_path / "MyFiles"
    scan_root.mkdir()

    # Real files on disk
    doc_file = scan_root / "notes.txt"
    doc_file.write_text("Important research notes", encoding="utf-8")

    pic_file = scan_root / "Camera Roll" / "pic1.jpg"
    pic_file.parent.mkdir()
    pic_file.write_bytes(b"\xff\xd8\xff\xe0")

    orphan_img = scan_root / "random.png"
    orphan_img.write_bytes(b"\x89PNG\r\n\x1a\n")

    conn = get_connection(test_db)
    try:
        save_excluded_folders(conn, get_default_excluded_folders())
        save_image_folders(conn, [])

        # Manually insert DB rows simulating an old unpruned index
        now = 1000.0
        fid1 = upsert_file_record(conn, str(doc_file), "notes.txt", ".txt", 100, now, now, "hash1", now, "indexed")
        fid2 = upsert_file_record(conn, str(pic_file), "pic1.jpg", ".jpg", 200, now, now, "hash2", now, "indexed")
        fid3 = upsert_file_record(conn, str(orphan_img), "random.png", ".png", 300, now, now, "hash3", now, "indexed")
        conn.commit()

        assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 3
    finally:
        conn.close()

    # Run prune CLI handler
    args = argparse.Namespace()
    with patch("app.cli.get_connection", return_value=get_connection(test_db)):
        ret = handle_prune(args)
        assert ret == 0

    # Verify database state
    conn = get_connection(test_db)
    try:
        cur = conn.execute("SELECT filename FROM files")
        remaining = [row["filename"] for row in cur.fetchall()]
        assert remaining == ["notes.txt"]
        assert "pic1.jpg" not in remaining
        assert "random.png" not in remaining
    finally:
        conn.close()

    # CRITICAL: Verify real files on disk are completely untouched
    assert doc_file.exists()
    assert pic_file.exists()
    assert orphan_img.exists()


def test_cli_folders(test_db: Path, tmp_path: Path, capsys):
    conn = get_connection(test_db)
    try:
        now = 1000.0
        upsert_file_record(conn, r"D:\Docs\Work\report.pdf", "report.pdf", ".pdf", 500, now, now, "h1", now, "indexed")
        upsert_file_record(conn, r"D:\Docs\Work\sheet.xlsx", "sheet.xlsx", ".xlsx", 600, now, now, "h2", now, "indexed")
        conn.commit()
    finally:
        conn.close()

    args = argparse.Namespace()
    with patch("app.cli.get_connection", return_value=get_connection(test_db)):
        ret = handle_folders(args)
        assert ret == 0

    captured = capsys.readouterr().out
    assert "Indexed Files by Top Folder" in captured
    assert "Indexed Files by Extension" in captured
    assert ".pdf" in captured
    assert ".xlsx" in captured
    assert "Total indexed files: 2" in captured


# ─────────────────────────────────────────────────────────────────────────────
# 5. Search Ranking & Image Filtering Policy Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_query_has_image_word():
    assert query_has_image_word("photo of passport") is True
    assert query_has_image_word("show me my pictures") is True
    assert query_has_image_word("screenshot of bill") is True
    assert query_has_image_word("aadhaar pic") is True
    assert query_has_image_word("png file") is True
    assert query_has_image_word("mera tasveer") is True

    # Non-image queries
    assert query_has_image_word("passport") is False
    assert query_has_image_word("health insurance policy") is False
    assert query_has_image_word("electricity bill") is False
    assert query_has_image_word("tax return 2025") is False


def test_image_results_excluded_when_3_or_more_docs_and_no_image_word():
    # 3 document results and 2 image results
    results = [
        {"filename": "passport.pdf", "path": "D:\\Docs\\passport.pdf", "doc_type": "id_document", "score": 10.0},
        {"filename": "aadhaar.jpg", "path": "D:\\Docs\\aadhaar.jpg", "doc_type": "image", "score": 9.5},
        {"filename": "license.pdf", "path": "D:\\Docs\\license.pdf", "doc_type": "id_document", "score": 9.0},
        {"filename": "voter_id.docx", "path": "D:\\Docs\\voter_id.docx", "doc_type": "id_document", "score": 8.5},
        {"filename": "id_card.png", "path": "D:\\Docs\\id_card.png", "doc_type": "image", "score": 8.0},
    ]

    # Non-image query: images should be completely excluded because >= 3 documents exist
    filtered = apply_image_search_policy(results, query="passport", limit=5)
    filenames = [r["filename"] for r in filtered]

    assert filenames == ["passport.pdf", "license.pdf", "voter_id.docx"]
    assert "aadhaar.jpg" not in filenames
    assert "id_card.png" not in filenames


def test_image_results_allowed_when_less_than_3_docs():
    # Only 1 document result and 2 image results
    results = [
        {"filename": "aadhaar.jpg", "path": "D:\\Docs\\aadhaar.jpg", "doc_type": "image", "score": 10.0},
        {"filename": "passport.pdf", "path": "D:\\Docs\\passport.pdf", "doc_type": "id_document", "score": 8.0},
        {"filename": "photo.png", "path": "D:\\Docs\\photo.png", "doc_type": "image", "score": 7.0},
    ]

    # Non-image query: document must come first, image can fill remaining slots
    filtered = apply_image_search_policy(results, query="passport", limit=5)
    filenames = [r["filename"] for r in filtered]

    # passport.pdf must be first even though aadhaar.jpg had higher raw score!
    assert filenames[0] == "passport.pdf"
    assert "aadhaar.jpg" in filenames
    assert "photo.png" in filenames


def test_image_results_allowed_and_ranked_when_query_has_image_word():
    results = [
        {"filename": "aadhaar.jpg", "path": "D:\\Docs\\aadhaar.jpg", "doc_type": "image", "score": 10.0},
        {"filename": "passport.pdf", "path": "D:\\Docs\\passport.pdf", "doc_type": "id_document", "score": 8.0},
        {"filename": "photo.png", "path": "D:\\Docs\\photo.png", "doc_type": "image", "score": 7.0},
    ]

    # Image query: "photo of passport"
    filtered = apply_image_search_policy(results, query="photo of passport", limit=5)
    filenames = [r["filename"] for r in filtered]

    # Naturally ranked by score
    assert filenames == ["aadhaar.jpg", "passport.pdf", "photo.png"]
