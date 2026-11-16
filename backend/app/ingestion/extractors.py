"""Text extraction module for supported document formats."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractionResult:
    text: str
    status: str  # "indexed", "empty", "needs_ocr", "unsupported", "error"
    error: str | None = None


SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".pdf", ".docx", ".xlsx"}


def extract_text_file(path: Path) -> str:
    """Extract plain text handling utf-8 and falling back to latin-1."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def extract_pdf(path: Path) -> str:
    """Extract text from PDF pages using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            parts.append(page_text)
    return "\n".join(parts)


def extract_docx(path: Path) -> str:
    """Extract paragraphs and table text from DOCX using python-docx."""
    import docx

    doc = docx.Document(str(path))
    parts: list[str] = []

    for paragraph in doc.paragraphs:
        if paragraph.text and paragraph.text.strip():
            parts.append(paragraph.text.strip())

    for table in doc.tables:
        for row in table.rows:
            cell_texts = [cell.text.strip() for cell in row.cells if cell.text and cell.text.strip()]
            if cell_texts:
                parts.append(" | ".join(cell_texts))

    return "\n".join(parts)


def extract_xlsx(path: Path) -> str:
    """Extract cell values from XLSX using openpyxl in read-only mode."""
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    lines: list[str] = []
    try:
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                cell_values = [str(val).strip() for val in row if val is not None and str(val).strip()]
                if cell_values:
                    lines.append(" ".join(cell_values))
    finally:
        wb.close()

    return "\n".join(lines)


def extract_file(path: Path) -> ExtractionResult:
    """
    Extract text from a file based on its extension.
    Never crashes on corrupt files; records status and error safely.
    """
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return ExtractionResult(
            text="",
            status="unsupported",
            error=f"Unsupported file extension: '{ext}'",
        )

    try:
        if ext in {".txt", ".md", ".csv"}:
            raw_text = extract_text_file(path)
        elif ext == ".pdf":
            raw_text = extract_pdf(path)
            cleaned = raw_text.strip()
            if not cleaned:
                return ExtractionResult(text="", status="needs_ocr")
            return ExtractionResult(text=cleaned, status="indexed")
        elif ext == ".docx":
            raw_text = extract_docx(path)
        elif ext == ".xlsx":
            raw_text = extract_xlsx(path)
        else:
            return ExtractionResult(
                text="",
                status="unsupported",
                error=f"Unsupported file extension: '{ext}'",
            )

        cleaned = raw_text.strip()
        if not cleaned:
            return ExtractionResult(text="", status="empty")

        return ExtractionResult(text=cleaned, status="indexed")

    except Exception as exc:
        return ExtractionResult(
            text="",
            status="error",
            error=f"{type(exc).__name__}: {str(exc)}",
        )
