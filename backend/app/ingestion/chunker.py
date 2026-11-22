"""Document chunking module for title and text semantic segments."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_CHUNKS_PER_FILE = 200
WORDS_PER_CHUNK = 200
OVERLAP_WORDS = 40
STEP_WORDS = WORDS_PER_CHUNK - OVERLAP_WORDS  # 160 words


@dataclass
class Chunk:
    chunk_index: int
    kind: str  # 'title' or 'text'
    text: str


def make_title_chunk(path_str: str) -> str:
    """
    Build title chunk text from filename (without ext, underscores/dashes to spaces)
    and the containing folder names of its path.
    """
    p = Path(path_str)
    # Filename stem with underscores and dashes converted to spaces
    stem = p.stem
    clean_filename = re.sub(r"[_\-]+", " ", stem).strip()

    # Containing folders (excluding drive letters like 'D:\' or empty parts)
    parts = p.parts[:-1]
    clean_folders: list[str] = []
    for part in parts:
        clean_part = part.strip()
        if not clean_part or clean_part.endswith(":\\") or clean_part in ("/", "\\"):
            continue
        clean_part = re.sub(r"[_\-]+", " ", clean_part).strip()
        if clean_part:
            clean_folders.append(clean_part)

    folder_prefix = " ".join(clean_folders)
    if folder_prefix:
        return f"{folder_prefix} {clean_filename}".strip()
    return clean_filename


def chunk_file(
    path: str,
    status: str,
    text: str | None = None,
) -> list[Chunk]:
    """
    Chunk an indexed file:
    - 1 'title' chunk containing folder names and clean filename.
    - 'text' chunks of ~200 words with 40-word overlap from extracted text.
    - Files with status 'needs_ocr' or 'empty' only receive the title chunk.
    - Capped at 200 chunks per file.
    """
    chunks: list[Chunk] = []

    # 1. Always create the title chunk (index 0)
    title_text = make_title_chunk(path)
    chunks.append(Chunk(chunk_index=0, kind="title", text=title_text))

    # 2. Text chunks (only for files with content)
    if status not in ("needs_ocr", "empty") and text and text.strip():
        words = text.split()
        if words:
            chunk_idx = 1
            start = 0
            total_words = len(words)

            while start < total_words:
                chunk_words = words[start : start + WORDS_PER_CHUNK]
                chunk_str = " ".join(chunk_words).strip()
                if chunk_str:
                    chunks.append(Chunk(chunk_index=chunk_idx, kind="text", text=chunk_str))
                    chunk_idx += 1

                # If this chunk reached or exceeded the end of words, we are done
                if start + WORDS_PER_CHUNK >= total_words:
                    break
                start += STEP_WORDS

                if len(chunks) >= MAX_CHUNKS_PER_FILE:
                    break

    return chunks[:MAX_CHUNKS_PER_FILE]
