"""Tests for OCR module and CLI ocr command."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.cli import handle_ocr
from app.config import settings
from app.db import (
    get_connection,
    init_db,
    save_image_folders,
    search_fts,
    upsert_file_record,
)
from app.ingestion.extractors import extract_text
from app.ingestion.ocr import (
    extract_ocr_text,
    get_ocr_engine,
    ocr_image_file,
    ocr_pdf,
    set_ocr_engine,
)
from app.ingestion.scanner import scan_and_index


class FakeOCREngine:
    """Mock OCR engine returning predetermined text for tests."""

    def __init__(self, mapping: dict[str, str] | None = None, default_text: str = "Sample OCR Text"):
        self.mapping = mapping or {}
        self.default_text = default_text
        self.calls: list[Any] = []

    def __call__(self, img_input: Any) -> tuple[list[Any] | None, float]:
        self.calls.append(img_input)
        # Return format matching RapidOCR: list of [box, text, score]
        text = self.default_text
        if isinstance(img_input, (str, Path)):
            text = self.mapping.get(Path(img_input).name, self.default_text)
        if not text:
            return (None, 0.01)
        return ([[None, text, 0.98]], 0.01)


@pytest.fixture(autouse=True)
def reset_ocr_engine():
    """Ensure clean OCR engine before and after every test."""
    yield
    set_ocr_engine(None)


def test_extractor_images_status_needs_ocr(tmp_path: Path):
    """Verify .png, .jpg, .jpeg files are identified with status needs_ocr and empty text."""
    for ext in [".png", ".jpg", ".jpeg"]:
        img_path = tmp_path / f"sample{ext}"
        # Create minimal 10x10 image
        img = Image.new("RGB", (10, 10), color="white")
        img.save(img_path)

        status, text, err = extract_text(img_path)
        assert status == "needs_ocr"
        assert text == ""
        assert err is None


def test_scanner_indexes_images_as_needs_ocr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify filesystem scanner indexes image files with needs_ocr status."""
    db_path = tmp_path / "recall.db"
    docs_dir = tmp_path / "images"
    docs_dir.mkdir(parents=True, exist_ok=True)

    img1 = docs_dir / "receipt.png"
    Image.new("RGB", (20, 20), color="red").save(img1)

    img2 = docs_dir / "photo.jpg"
    Image.new("RGB", (20, 20), color="blue").save(img2)

    conn = get_connection(db_path)
    try:
        init_db(db_path)
        save_image_folders(conn, [str(docs_dir.resolve())])
    finally:
        conn.close()

    stats = scan_and_index([docs_dir], db_path=db_path)
    assert stats.needs_ocr >= 2

    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT filename, status FROM files WHERE status = 'needs_ocr'").fetchall()
        filenames = {r["filename"] for r in rows}
        assert "receipt.png" in filenames
        assert "photo.jpg" in filenames
    finally:
        conn.close()


def test_ocr_image_file_with_mock(tmp_path: Path):
    """Verify ocr_image_file calls OCR engine and returns parsed text."""
    img_path = tmp_path / "invoice.png"
    Image.new("RGB", (100, 100), color="white").save(img_path)

    fake_engine = FakeOCREngine(default_text="INVOICE #98765 TOTAL $120.00")
    set_ocr_engine(fake_engine)

    text = ocr_image_file(img_path)
    assert text == "INVOICE #98765 TOTAL $120.00"
    assert len(fake_engine.calls) == 1


def test_ocr_image_resize_if_above_2500(tmp_path: Path):
    """Verify images with longest side > 2500 px are downscaled before passing to OCR."""
    img_path = tmp_path / "large_poster.jpg"
    # Create image of size 3000 x 1500 (longest side 3000)
    Image.new("RGB", (3000, 1500), color="green").save(img_path)

    passed_sizes: list[tuple[int, int]] = []

    def mock_ocr(img_input):
        if hasattr(img_input, "size"):
            passed_sizes.append(img_input.size)
        return ([[None, "Large poster headline", 0.99]], 0.01)

    set_ocr_engine(mock_ocr)

    text = ocr_image_file(img_path)
    assert text == "Large poster headline"
    assert len(passed_sizes) == 1
    width, height = passed_sizes[0]
    assert max(width, height) <= 2500
    assert width == 2500
    assert height == 1250


def test_ocr_corrupt_file_never_crashes(tmp_path: Path):
    """Verify OCR functions never crash on corrupt or non-existent files."""
    corrupt_file = tmp_path / "broken.png"
    corrupt_file.write_bytes(b"NOT_A_VALID_IMAGE_HEADER_RANDOM_GARBAGE")

    res1 = extract_ocr_text(corrupt_file)
    assert res1 == ""

    res2 = extract_ocr_text(tmp_path / "non_existent_file.pdf")
    assert res2 == ""


def test_ocr_pdf_mocked_pages(tmp_path: Path):
    """Verify ocr_pdf renders pages, limits to 10 pages, and frees memory."""
    dummy_pdf = tmp_path / "document.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy")

    fake_pages = []
    for i in range(12):  # 12 pages, should only process first 10
        mock_page = MagicMock()
        mock_pil = Image.new("RGB", (50, 50), color="white")
        mock_page.render.return_value.to_pil.return_value = mock_pil
        fake_pages.append(mock_page)

    mock_doc = MagicMock()
    mock_doc.__len__.return_value = len(fake_pages)
    mock_doc.__getitem__.side_effect = lambda idx: fake_pages[idx]

    mock_engine = MagicMock()
    mock_engine.return_value = ([[None, "Page OCR content line", 0.95]], 0.01)
    set_ocr_engine(mock_engine)

    with patch("pypdfium2.PdfDocument", return_value=mock_doc):
        text = ocr_pdf(dummy_pdf, max_pages=10)

    assert "Page OCR content line" in text
    assert mock_doc.__getitem__.call_count == 10  # Capped at 10 pages
    # Ensure page and image cleanup happened
    for p in fake_pages[:10]:
        p.close.assert_called_once()
    mock_doc.close.assert_called_once()


def test_cli_ocr_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Test 'python -m app.cli ocr':
    - Processes only files with status 'needs_ocr'
    - Updates files table with status 'indexed' (or 'empty')
    - Stores text in contents table and updates FTS
    - Deletes old chunks so next embed re-chunks it
    - Never prints full text, only counts
    """
    temp_data_dir = tmp_path / "data"
    temp_data_dir.mkdir(parents=True, exist_ok=True)
    temp_db = temp_data_dir / "recall.db"
    monkeypatch.setattr(settings, "data_dir", temp_data_dir)
    monkeypatch.setattr(settings, "db_path", temp_db)
    init_db(temp_db)

    conn = get_connection(temp_db)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    save_image_folders(conn, [str(docs_dir.resolve())])

    # File 1: Scanned PDF with status needs_ocr
    f_pdf = docs_dir / "nasa_scanned.pdf"
    f_pdf.write_bytes(b"%PDF-1.4 dummy")

    # File 2: Image with status needs_ocr
    f_img = docs_dir / "award_certificate.png"
    Image.new("RGB", (100, 100), color="white").save(f_img)

    # File 3: Image with no text found
    f_empty = docs_dir / "blank_paper.jpg"
    Image.new("RGB", (100, 100), color="white").save(f_empty)

    # File 4: Already indexed file (should NOT be processed by OCR)
    f_txt = docs_dir / "notes.txt"
    f_txt.write_text("Regular indexed notes.")

    try:
        upsert_file_record(conn, str(f_pdf.resolve()), "nasa_scanned.pdf", ".pdf", 500, 1.0, 1.0, "h1", 1.0, "needs_ocr")
        upsert_file_record(conn, str(f_img.resolve()), "award_certificate.png", ".png", 500, 1.0, 1.0, "h2", 1.0, "needs_ocr")
        upsert_file_record(conn, str(f_empty.resolve()), "blank_paper.jpg", ".jpg", 500, 1.0, 1.0, "h3", 1.0, "needs_ocr")
        upsert_file_record(conn, str(f_txt.resolve()), "notes.txt", ".txt", 500, 1.0, 1.0, "h4", 1.0, "indexed", text="Regular indexed notes.")

        # Insert dummy chunks for File 1 to verify they get deleted
        conn.execute("INSERT INTO chunks (file_id, chunk_index, kind, text, embedding, model) VALUES (1, 0, 'title', 'nasa', X'00', 'model1')")
        conn.commit()

        # Mock extract_ocr_text
        def mock_extract(path):
            p = Path(path).name
            if p == "nasa_scanned.pdf":
                return "NASA Apollo Mission Flight Certification"
            elif p == "award_certificate.png":
                return "Excellence in Deep Space Telemetry"
            elif p == "blank_paper.jpg":
                return ""  # Empty OCR
            return ""

        with patch("app.ingestion.ocr.extract_ocr_text", side_effect=mock_extract):
            args = argparse.Namespace(limit=None)
            ret = handle_ocr(args)
            assert ret == 0

        # Verify File 1 (nasa_scanned.pdf)
        r1 = conn.execute("SELECT status FROM files WHERE filename = 'nasa_scanned.pdf'").fetchone()
        assert r1["status"] == "indexed"
        c1 = conn.execute("SELECT text FROM contents WHERE file_id = 1").fetchone()
        assert c1 is not None
        assert "NASA Apollo Mission" in c1["text"]
        # Old chunks deleted
        chunks1 = conn.execute("SELECT count(*) as cnt FROM chunks WHERE file_id = 1").fetchone()["cnt"]
        assert chunks1 == 0

        # Verify File 2 (award_certificate.png)
        r2 = conn.execute("SELECT status FROM files WHERE filename = 'award_certificate.png'").fetchone()
        assert r2["status"] == "indexed"
        c2 = conn.execute("SELECT text FROM contents WHERE file_id = 2").fetchone()
        assert c2 is not None
        assert "Deep Space Telemetry" in c2["text"]

        # Verify File 3 (blank_paper.jpg) -> status empty
        r3 = conn.execute("SELECT status FROM files WHERE filename = 'blank_paper.jpg'").fetchone()
        assert r3["status"] == "empty"
        c3 = conn.execute("SELECT text FROM contents WHERE file_id = 3").fetchone()
        assert c3 is None

        # Verify File 4 was untouched
        r4 = conn.execute("SELECT status FROM files WHERE filename = 'notes.txt'").fetchone()
        assert r4["status"] == "indexed"

        # Verify FTS search finds the newly OCR-indexed content
        fts_res = search_fts(conn, "apollo telemetry")
        filenames = [r["filename"] for r in fts_res]
        assert "nasa_scanned.pdf" in filenames or "award_certificate.png" in filenames

    finally:
        conn.close()


def test_cli_ocr_limit_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify --limit N flag processes at most N files."""
    temp_data_dir = tmp_path / "data"
    temp_data_dir.mkdir(parents=True, exist_ok=True)
    temp_db = temp_data_dir / "recall.db"
    monkeypatch.setattr(settings, "data_dir", temp_data_dir)
    monkeypatch.setattr(settings, "db_path", temp_db)
    init_db(temp_db)

    conn = get_connection(temp_db)
    try:
        upsert_file_record(conn, "D:/docs/doc1.pdf", "doc1.pdf", ".pdf", 100, 1.0, 1.0, "h1", 1.0, "needs_ocr")
        upsert_file_record(conn, "D:/docs/doc2.pdf", "doc2.pdf", ".pdf", 100, 1.0, 1.0, "h2", 1.0, "needs_ocr")
        upsert_file_record(conn, "D:/docs/doc3.pdf", "doc3.pdf", ".pdf", 100, 1.0, 1.0, "h3", 1.0, "needs_ocr")
        conn.commit()

        with patch("app.ingestion.ocr.extract_ocr_text", return_value="Extracted text"):
            args = argparse.Namespace(limit=1)
            ret = handle_ocr(args)
            assert ret == 0

        # Exactly 1 file should now be indexed, 2 should still be needs_ocr
        indexed_count = conn.execute("SELECT count(*) as cnt FROM files WHERE status = 'indexed'").fetchone()["cnt"]
        assert indexed_count == 1
        needs_ocr_count = conn.execute("SELECT count(*) as cnt FROM files WHERE status = 'needs_ocr'").fetchone()["cnt"]
        assert needs_ocr_count == 2

    finally:
        conn.close()
