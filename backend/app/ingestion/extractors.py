"""Text extraction module for supported document formats."""

from __future__ import annotations

import io
import logging
import warnings
from contextlib import redirect_stderr
from pathlib import Path

# Silence pypdf logger noise
logging.getLogger("pypdf").setLevel(logging.ERROR)

SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".pdf",
    ".docx",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
}


def _extract_plain(path: Path) -> str:
    """Extract plain text trying UTF-8 first, falling back to Latin-1."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _extract_pdf(path: Path) -> tuple[str, str, str | None]:
    """Extract text from PDF using pypdf. Suppresses warnings and stderr noise."""
    from pypdf import PdfReader

    stderr_sink = io.StringIO()
    with redirect_stderr(stderr_sink), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        logging.getLogger("pypdf").setLevel(logging.ERROR)

        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                parts.append(page_text)

    full_text = "\n".join(parts).strip()
    if not full_text:
        return ("needs_ocr", "", None)
    return ("indexed", full_text, None)


def _extract_docx(path: Path) -> str:
    """Extract text from DOCX paragraphs and tables using python-docx."""
    import docx

    doc = docx.Document(str(path))
    parts: list[str] = []

    for paragraph in doc.paragraphs:
        if paragraph.text and paragraph.text.strip():
            parts.append(paragraph.text.strip())

    for table in doc.tables:
        for row in table.rows:
            row_cells = [cell.text.strip() for cell in row.cells if cell.text and cell.text.strip()]
            if row_cells:
                parts.append(" ".join(row_cells))

    return "\n".join(parts).strip()


def _extract_xlsx(path: Path) -> str:
    """Extract cell values from XLSX in read-only mode joining with spaces."""
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    lines: list[str] = []
    try:
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                cells = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
                if cells:
                    lines.append(" ".join(cells))
    finally:
        wb.close()

    return "\n".join(lines).strip()


def extract_text(path: Path) -> tuple[str, str, str | None]:
    """
    Extract text from a file based on its extension.

    Returns:
        tuple[str, str, str | None]: (status, text, error)
        status values: "indexed", "empty", "needs_ocr", "unsupported", "error"
    """
    path = Path(path)
    ext = path.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        return ("unsupported", "", None)

    try:
        if ext in {".txt", ".md", ".csv"}:
            text = _extract_plain(path)
        elif ext == ".pdf":
            return _extract_pdf(path)
        elif ext in {".png", ".jpg", ".jpeg"}:
            return ("needs_ocr", "", None)
        elif ext == ".docx":
            text = _extract_docx(path)
        elif ext == ".xlsx":
            text = _extract_xlsx(path)
        else:
            return ("unsupported", "", None)

        cleaned = text.strip()
        if not cleaned:
            return ("empty", "", None)

        return ("indexed", cleaned, None)

    except Exception as exc:
        return ("error", "", f"{type(exc).__name__}: {str(exc)}")


def extract_text_from_bytes(data: bytes, filename: str) -> tuple[str, str, str | None]:
    """
    Extract text in-memory from bytes for attachments (pdf, docx, xlsx, txt).
    Never writes to disk.
    Returns: (status, text, error)
    """
    ext = Path(filename).suffix.lower()
    if ext not in {".txt", ".md", ".csv", ".pdf", ".docx", ".xlsx"}:
        return ("unsupported", "", None)

    try:
        if ext in {".txt", ".md", ".csv"}:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("latin-1")
            cleaned = text.strip()
            return ("indexed", cleaned, None) if cleaned else ("empty", "", None)

        elif ext == ".pdf":
            from pypdf import PdfReader

            stderr_sink = io.StringIO()
            with redirect_stderr(stderr_sink), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                logging.getLogger("pypdf").setLevel(logging.ERROR)

                reader = PdfReader(io.BytesIO(data))
                parts: list[str] = []
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        parts.append(page_text)

            full_text = "\n".join(parts).strip()
            if not full_text:
                return ("empty", "", None)
            return ("indexed", full_text, None)

        elif ext == ".docx":
            import docx

            doc = docx.Document(io.BytesIO(data))
            parts = []
            for paragraph in doc.paragraphs:
                if paragraph.text and paragraph.text.strip():
                    parts.append(paragraph.text.strip())
            for table in doc.tables:
                for row in table.rows:
                    row_cells = [cell.text.strip() for cell in row.cells if cell.text and cell.text.strip()]
                    if row_cells:
                        parts.append(" ".join(row_cells))
            full_text = "\n".join(parts).strip()
            return ("indexed", full_text, None) if full_text else ("empty", "", None)

        elif ext == ".xlsx":
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            lines: list[str] = []
            try:
                for sheet in wb.worksheets:
                    for row in sheet.iter_rows(values_only=True):
                        cells = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
                        if cells:
                            lines.append(" ".join(cells))
            finally:
                wb.close()
            full_text = "\n".join(lines).strip()
            return ("indexed", full_text, None) if full_text else ("empty", "", None)

        return ("unsupported", "", None)

    except Exception as exc:
        return ("error", "", f"{type(exc).__name__}: {str(exc)}")

