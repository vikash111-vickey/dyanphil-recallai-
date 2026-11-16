"""Tests for document extraction, indexing, incremental updates, and FTS search."""

from __future__ import annotations

import io
import time
from pathlib import Path

import docx
import openpyxl
import pypdf
import pytest

from app.db import (
    get_connection,
    get_file_by_path,
    get_stats,
    init_db,
    search_fts,
)
from app.ingestion.extractors import extract_file
from app.ingestion.scanner import index_folders

MINIMAL_PDF_BYTES = b"""%PDF-1.4
1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj
2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj
3 0 obj <</Type /Page /Parent 2 0 R /Resources <</Font <</F1 4 0 R>>>> /MediaBox [0 0 612 792] /Contents 5 0 R>> endobj
4 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj
5 0 obj <</Length 44>> stream
BT
/F1 24 Tf
100 700 Td
(Hello PDF World) Tj
ET
endstream
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000229 00000 n 
0000000298 00000 n 
trailer <</Size 6 /Root 1 0 R>>
startxref
393
%%EOF"""


def test_txt_md_csv_extraction(tmp_path: Path):
    """Test text, markdown, and csv extraction, including latin-1 encoding fallback."""
    # UTF-8 text
    utf8_file = tmp_path / "sample.txt"
    utf8_file.write_text("Hello utf-8 world", encoding="utf-8")
    res1 = extract_file(utf8_file)
    assert res1.status == "indexed"
    assert "Hello utf-8 world" in res1.text

    # Latin-1 fallback
    latin1_file = tmp_path / "latin1.txt"
    latin1_file.write_bytes(b"Caf\xe9 au lait")
    res2 = extract_file(latin1_file)
    assert res2.status == "indexed"
    assert "Café au lait" in res2.text

    # Markdown
    md_file = tmp_path / "notes.md"
    md_file.write_text("# Heading\nSome bullet points", encoding="utf-8")
    res3 = extract_file(md_file)
    assert res3.status == "indexed"
    assert "Heading" in res3.text

    # CSV
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("name,age\nAlice,30\nBob,25", encoding="utf-8")
    res4 = extract_file(csv_file)
    assert res4.status == "indexed"
    assert "Alice,30" in res4.text


def test_docx_extraction(tmp_path: Path):
    """Test extracting paragraphs and table text from DOCX."""
    docx_file = tmp_path / "document.docx"
    doc = docx.Document()
    doc.add_paragraph("First paragraph content")
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Header1"
    table.rows[0].cells[1].text = "Header2"
    table.rows[1].cells[0].text = "ValueA"
    table.rows[1].cells[1].text = "ValueB"
    doc.save(str(docx_file))

    res = extract_file(docx_file)
    assert res.status == "indexed"
    assert "First paragraph content" in res.text
    assert "Header1" in res.text
    assert "ValueA" in res.text


def test_pdf_extraction_and_needs_ocr(tmp_path: Path):
    """Test PDF with text and blank PDF triggering needs_ocr."""
    # PDF with extractable text
    text_pdf = tmp_path / "with_text.pdf"
    text_pdf.write_bytes(MINIMAL_PDF_BYTES)
    res_text = extract_file(text_pdf)
    assert res_text.status == "indexed"
    assert "Hello PDF World" in res_text.text

    # Blank PDF with no text -> needs_ocr
    blank_pdf = tmp_path / "blank.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with blank_pdf.open("wb") as f:
        writer.write(f)

    res_blank = extract_file(blank_pdf)
    assert res_blank.status == "needs_ocr"
    assert res_blank.text == ""


def test_xlsx_extraction(tmp_path: Path):
    """Test XLSX extraction in read-only mode joining cells with spaces."""
    xlsx_file = tmp_path / "sheet.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DataSheet"
    ws.append(["Product", "Price", "Quantity"])
    ws.append(["Widget", 19.99, 100])
    wb.save(str(xlsx_file))
    wb.close()

    res = extract_file(xlsx_file)
    assert res.status == "indexed"
    assert "Product Price Quantity" in res.text
    assert "Widget 19.99 100" in res.text


def test_incremental_reindexing(tmp_path: Path):
    """Test that unchanged files are skipped and modified files are re-indexed."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    test_file = docs_dir / "note.txt"
    test_file.write_text("Version one content", encoding="utf-8")

    # Initial index
    stats1 = index_folders([docs_dir], db_path=db_file)
    assert stats1.scanned == 1
    assert stats1.indexed == 1
    assert stats1.unchanged == 0

    # Second index without modifying file
    stats2 = index_folders([docs_dir], db_path=db_file)
    assert stats2.scanned == 1
    assert stats2.indexed == 0
    assert stats2.unchanged == 1

    # Modify file content and timestamp
    time.sleep(0.05)
    test_file.write_text("Version two updated content", encoding="utf-8")
    new_mtime = time.time() + 5.0
    import os
    os.utime(test_file, (new_mtime, new_mtime))

    stats3 = index_folders([docs_dir], db_path=db_file)
    assert stats3.scanned == 1
    assert stats3.indexed == 1
    assert stats3.unchanged == 0

    conn = get_connection(db_file)
    try:
        rec = get_file_by_path(conn, str(test_file.resolve()))
        assert rec is not None
        matches = search_fts(conn, "Version")
        assert len(matches) == 1
        assert "updated" in matches[0]["snippet"].lower()
    finally:
        conn.close()


def test_deleted_file_cleanup(tmp_path: Path):
    """Test that database entries are removed when files are deleted on disk."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    file_to_keep = docs_dir / "keep.txt"
    file_to_keep.write_text("Keep this file", encoding="utf-8")

    file_to_delete = docs_dir / "delete_me.txt"
    file_to_delete.write_text("Temporary confidential text", encoding="utf-8")

    index_folders([docs_dir], db_path=db_file)

    conn = get_connection(db_file)
    try:
        assert len(search_fts(conn, "confidential")) == 1
    finally:
        conn.close()

    # Delete the file
    file_to_delete.unlink()

    # Re-index
    stats = index_folders([docs_dir], db_path=db_file)
    assert stats.cleaned >= 1

    conn = get_connection(db_file)
    try:
        # Should no longer match
        assert len(search_fts(conn, "confidential")) == 0
        assert get_file_by_path(conn, str(file_to_delete.resolve())) is None
        # Kept file should remain
        assert get_file_by_path(conn, str(file_to_keep.resolve())) is not None
    finally:
        conn.close()


def test_skipped_folders_and_large_files(tmp_path: Path):
    """Test that ignored folder trees and files larger than 25MB are skipped."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    # Ignored directories
    skip_dirs = [
        ".venv",
        "node_modules",
        ".git",
        "__pycache__",
        "AppData",
        "Windows",
        "Program Files",
        "$Recycle.Bin",
        ".hidden_folder",
    ]
    for d in skip_dirs:
        sub = docs_dir / d
        sub.mkdir(parents=True)
        (sub / "ignored.txt").write_text(f"Secret inside {d}", encoding="utf-8")

    # Large file (> 25 MB) created via sparse seek
    large_file = docs_dir / "huge.txt"
    with large_file.open("wb") as f:
        f.seek(26 * 1024 * 1024)
        f.write(b"X")

    # One valid file
    valid_file = docs_dir / "valid.txt"
    valid_file.write_text("Only valid file to be indexed", encoding="utf-8")

    stats = index_folders([docs_dir], db_path=db_file)
    assert stats.indexed == 1
    assert stats.skipped >= 1

    conn = get_connection(db_file)
    try:
        results = search_fts(conn, "Secret")
        assert len(results) == 0
        valid_res = search_fts(conn, "indexed")
        assert len(valid_res) == 1
        assert valid_res[0]["filename"] == "valid.txt"
    finally:
        conn.close()


def test_corrupt_file_handling(tmp_path: Path):
    """Test that corrupt files never crash indexing and record status 'error'."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    bad_docx = docs_dir / "corrupted.docx"
    bad_docx.write_bytes(b"NOT A ZIP OR DOCX ARCHIVE GARBAGE DATA")

    bad_pdf = docs_dir / "corrupted.pdf"
    bad_pdf.write_bytes(b"%PDF-INVALID CONTENT NOT RECOGNIZED")

    good_txt = docs_dir / "ok.txt"
    good_txt.write_text("Good plain text", encoding="utf-8")

    stats = index_folders([docs_dir], db_path=db_file)
    assert stats.indexed == 1
    assert stats.failed == 2

    conn = get_connection(db_file)
    try:
        rec_docx = get_file_by_path(conn, str(bad_docx.resolve()))
        assert rec_docx is not None
        assert rec_docx["status"] == "error"
        assert rec_docx["error"] is not None

        rec_pdf = get_file_by_path(conn, str(bad_pdf.resolve()))
        assert rec_pdf is not None
        assert rec_pdf["status"] == "error"
        assert rec_pdf["error"] is not None
    finally:
        conn.close()


def test_search_returning_correct_path_and_stats(tmp_path: Path):
    """Test search ranking, correct path retrieval, snippet, and stats aggregation."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = tmp_path / "test.db"

    f1 = docs_dir / "file1.txt"
    f1.write_text("Quantum teleportation protocol analysis", encoding="utf-8")

    f2 = docs_dir / "file2.md"
    f2.write_text("Culinary gastronomy techniques for baking", encoding="utf-8")

    index_folders([docs_dir], db_path=db_file)

    conn = get_connection(db_file)
    try:
        # Search quantum
        matches = search_fts(conn, "quantum")
        assert len(matches) == 1
        assert matches[0]["path"] == str(f1.resolve())
        assert matches[0]["filename"] == "file1.txt"
        assert matches[0]["rank"] == 1
        assert ">>>" in matches[0]["snippet"]

        # Search gastronomy
        matches2 = search_fts(conn, "gastronomy")
        assert len(matches2) == 1
        assert matches2[0]["path"] == str(f2.resolve())

        # Stats
        stats = get_stats(conn)
        assert stats["total_files"] == 2
        assert stats["by_status"]["indexed"] == 2
        assert stats["by_extension"][".txt"] == 1
        assert stats["by_extension"][".md"] == 1
    finally:
        conn.close()
