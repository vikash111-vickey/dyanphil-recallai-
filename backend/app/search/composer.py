"""Reply composer with tone-specific response templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def get_folder_name(path_str: str) -> str:
    """Extract immediate parent folder name or fallback to parent string."""
    p = Path(path_str)
    return p.parent.name or str(p.parent)


def compose_reply(tone: str, results: list[dict[str, Any]]) -> str:
    """
    Compose an empathetic, factual message tailored to the detected tone:
    - urgent / stressed: one short calm sentence, result first
    - frustrated: one short empathy line, then the result
    - casual / neutral: friendly, mention a second match if there is one
    - not found: gentle message offering to try similar words
    Never invent facts; only use the filename and folder from the result.
    """
    if not results:
        return "I couldn't find any matching files. You could try searching with different keywords or file names."

    first = results[0]
    f1 = first["filename"]
    folder1 = get_folder_name(first["path"])

    if tone in ("urgent", "stressed"):
        return f"Found {f1} in {folder1}."

    if tone == "frustrated":
        return f"I understand this is frustrating. Found {f1} in {folder1}."

    # casual / neutral
    if len(results) >= 2:
        second = results[1]
        f2 = second["filename"]
        folder2 = get_folder_name(second["path"])
        return f"Here is {f1} from {folder1}. I also found {f2} in {folder2} if that helps."

    return f"Here is {f1} from {folder1}."
