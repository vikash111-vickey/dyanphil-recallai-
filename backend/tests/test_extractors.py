"""Tests for document text extractors."""

from __future__ import annotations

from pathlib import Path

import docx
import openpyxl
import pypdf
import pytest

from app.ingestion.extractors import extract_text

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


def test_txt_extraction_utf8_and_latin1(tmp_path: Path):
    """Test .txt file extraction with UTF-8 and Latin-1 fallback."""
    # UTF-8 text
    utf8_file = tmp_path / "hello.txt"
    utf8_file.write_text("Hello UTF-8 world!", encoding="utf-8")
    status, text, err = extract_text(utf8_file)
    assert status == "indexed"
    assert "Hello UTF-8 world!" in text
    assert err is None

    # Latin-1 text
    latin1_file = tmp_path / "cafe.txt"
    latin1_file.write_bytes(b"Caf\xe9 au lait")
    status, text, err = extract_text(latin1_file)
    assert status == "indexed"
    assert "Café au lait" in text
    assert err is None


def test_md_extraction(tmp_path: Path):
    """Test .md markdown file extraction."""
    md_file = tmp_path / "readme.md"
    md_file.write_text("# Project Dyanphil\nLocal-first search engine.", encoding="utf-8")
    status, text, err = extract_text(md_file)
    assert status == "indexed"
    assert "Project Dyanphil" in text
    assert err is None


def test_csv_extraction(tmp_path: Path):
    """Test .csv file extraction."""
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("item,price\napple,2.5\norange,3.0", encoding="utf-8")
    status, text, err = extract_text(csv_file)
    assert status == "indexed"
    assert "apple,2.5" in text
    assert err is None


def test_pdf_extraction_and_needs_ocr(tmp_path: Path):
    """Test .pdf extraction with text and blank page triggering needs_ocr."""
    # Valid PDF with text
    pdf_file = tmp_path / "doc.pdf"
    pdf_file.write_bytes(MINIMAL_PDF_BYTES)
    status, text, err = extract_text(pdf_file)
    assert status == "indexed"
    assert "Hello PDF World" in text
    assert err is None

    # Blank PDF without text
    blank_pdf = tmp_path / "blank.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with blank_pdf.open("wb") as f:
        writer.write(f)

    status, text, err = extract_text(blank_pdf)
    assert status == "needs_ocr"
    assert text == ""
    assert err is None


def test_docx_extraction_with_tables(tmp_path: Path):
    """Test .docx extraction including paragraphs and table contents."""
    docx_file = tmp_path / "document.docx"
    doc = docx.Document()
    doc.add_paragraph("Introductory paragraph.")
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Header A"
    table.rows[0].cells[1].text = "Header B"
    table.rows[1].cells[0].text = "Value 1"
    table.rows[1].cells[1].text = "Value 2"
    doc.save(str(docx_file))

    status, text, err = extract_text(docx_file)
    assert status == "indexed"
    assert "Introductory paragraph." in text
    assert "Header A" in text
    assert "Value 1" in text
    assert err is None


def test_xlsx_extraction(tmp_path: Path):
    """Test .xlsx extraction in read-only mode joining cells with spaces."""
    xlsx_file = tmp_path / "sheet.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Widget", 100, "Active"])
    ws.append(["Gadget", 250, "Pending"])
    wb.save(str(xlsx_file))
    wb.close()

    status, text, err = extract_text(xlsx_file)
    assert status == "indexed"
    assert "Widget 100 Active" in text
    assert "Gadget 250 Pending" in text
    assert err is None


def test_corrupt_files_never_crash(tmp_path: Path):
    """Test that corrupt files return status 'error' with message and never crash."""
    corrupt_docx = tmp_path / "corrupt.docx"
    corrupt_docx.write_bytes(b"GARBAGE_NOT_A_ZIP")
    status, text, err = extract_text(corrupt_docx)
    assert status == "error"
    assert text == ""
    assert err is not None

    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"%PDF-INVALID_CORRUPT_BYTES")
    status, text, err = extract_text(corrupt_pdf)
    assert status == "error"
    assert text == ""
    assert err is not None


def test_pypdf_warnings_silenced(tmp_path: Path, capsys):
    """Test that pypdf warnings and stderr noise are silenced while recording error status."""
    bad_pdf = tmp_path / "bad_header.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4\n1 0 obj <</Type /Pages>> endobj\ntrailer <</Root 1 0 R>>\nstartxref\n9999\n%%EOF")
    status, text, err = extract_text(bad_pdf)
    captured = capsys.readouterr()
    assert captured.err == ""
    assert status == "error"
    assert err is not None


def test_unsupported_extension(tmp_path: Path):
    """Test that an unsupported file extension returns status 'unsupported'."""
    bin_file = tmp_path / "program.exe"
    bin_file.write_bytes(b"MZ\x90\x00")
    status, text, err = extract_text(bin_file)
    assert status == "unsupported"
    assert text == ""
    assert err is None


def test_empty_file(tmp_path: Path):
    """Test that empty or whitespace-only files return status 'empty'."""
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("   \n\t   ", encoding="utf-8")
    status, text, err = extract_text(empty_file)
    assert status == "empty"
    assert text == ""
    assert err is None
