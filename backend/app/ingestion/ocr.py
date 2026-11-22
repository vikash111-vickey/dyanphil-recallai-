"""OCR module for scanned documents and images using rapidocr-onnxruntime and pypdfium2."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Global singleton OCR engine instance loaded once lazily
_ocr_engine: Any = None


def get_ocr_engine() -> Any:
    """Retrieve or create the global RapidOCR engine instance lazily."""
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine = RapidOCR()
    return _ocr_engine


def set_ocr_engine(engine: Any) -> None:
    """Set or override the global OCR engine (useful for tests)."""
    global _ocr_engine
    _ocr_engine = engine


def _run_ocr_on_image(engine: Any, image_input: Any) -> str:
    """Run RapidOCR on image input (PIL Image, numpy array, or file path) and return joined lines."""
    try:
        result, _ = engine(image_input)
        if not result:
            return ""
        lines: list[str] = []
        for item in result:
            if len(item) > 1 and item[1]:
                lines.append(str(item[1]).strip())
        return "\n".join(lines).strip()
    except Exception as exc:
        logger.warning("OCR processing error: %s", exc)
        return ""


def ocr_pdf(
    path: Path | str,
    max_pages: int = 10,
    dpi: int = 150,
) -> str:
    """
    Render PDF pages at ~150 DPI, one page at a time (freeing memory after each page),
    up to the first 10 pages, run OCR, and join the text.
    Never crashes on bad files.
    """
    import pypdfium2 as pdfium

    pdf = None
    page_texts: list[str] = []
    engine = get_ocr_engine()
    scale = dpi / 72.0

    try:
        pdf = pdfium.PdfDocument(str(path))
        num_pages = min(max_pages, len(pdf))
        for page_idx in range(num_pages):
            page = None
            pil_image = None
            try:
                page = pdf[page_idx]
                pil_image = page.render(scale=scale).to_pil()
                text = _run_ocr_on_image(engine, pil_image)
                if text:
                    page_texts.append(text)
            except Exception as page_exc:
                logger.warning("Failed to render/OCR PDF page %d of %s: %s", page_idx, path, page_exc)
            finally:
                if pil_image is not None:
                    try:
                        pil_image.close()
                    except Exception:
                        pass
                    del pil_image
                if page is not None:
                    try:
                        page.close()
                    except Exception:
                        pass
                    del page
    except Exception as exc:
        logger.warning("Could not read PDF for OCR %s: %s", path, exc)
    finally:
        if pdf is not None:
            try:
                pdf.close()
            except Exception:
                pass

    return "\n\n".join(page_texts).strip()


def ocr_image_file(
    path: Path | str,
    max_side: int = 2500,
) -> str:
    """
    Run OCR on image (.png, .jpg, .jpeg), resizing if longest side > 2500 px.
    Never crashes on bad files.
    """
    from PIL import Image

    engine = get_ocr_engine()
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            w, h = img.size
            longest_side = max(w, h)
            if longest_side > max_side:
                scale = float(max_side) / float(longest_side)
                new_w = max(1, int(w * scale))
                new_h = max(1, int(h * scale))
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            return _run_ocr_on_image(engine, img)
    except Exception as exc:
        logger.warning("Could not read/OCR image file %s: %s", path, exc)
        return ""


def extract_ocr_text(path: Path | str) -> str:
    """
    Extract text using OCR for a supported file (.pdf, .png, .jpg, .jpeg).
    Returns extracted text string, or empty string on failure or no text detected.
    Never crashes.
    """
    target = Path(path)
    if not target.exists():
        return ""

    ext = target.suffix.lower()
    if ext == ".pdf":
        return ocr_pdf(target)
    elif ext in (".png", ".jpg", ".jpeg"):
        return ocr_image_file(target)
    return ""
