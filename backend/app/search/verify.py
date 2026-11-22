"""Faithfulness verification module for search answers.

Ensures that any factual claim (dates, numbers, amounts, IDs, names) stated in an answer
is strictly grounded in the database facts table or the source file's stored text.
If a claim cannot be confirmed, it is dropped with the message:
"I couldn't confirm this from your files", while still preserving the matching files.
Always includes the source filename and path.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any


FACT_SENTENCE_PATTERN = re.compile(
    r"(?i)\byour\s+(?P<subject>[^.]+?)\s+(?:expires\s+on|is\s+due\s+on|number\s+is|is)\s+(?P<value>[^()]+?)(?:\s*\(from\s+[^)]+\))?\.",
)


def extract_factual_claims(text: str) -> list[str]:
    """
    Extract factual values claimed in the text.
    Handles both structured fact templates ("Your passport number is A1234567")
    and explicit dates, amounts, or ID numbers.
    """
    claims: list[str] = []

    # 1. Check template match
    for m in FACT_SENTENCE_PATTERN.finditer(text):
        val = m.group("value").strip().strip(".,;")
        if val:
            claims.append(val)

    # 2. Check standalone dates
    date_matches = re.findall(
        r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b",
        text,
        re.IGNORECASE,
    )
    for d in date_matches:
        if d not in claims:
            claims.append(d)

    # 3. Check currency/amounts
    amount_matches = re.findall(
        r"(?:₹|Rs\.?|INR|\$)\s*[\d,]+(?:\.\d+)?|\b\d+(?:\.\d+)?\s*(?:inr|rs|rupees|dollars)\b",
        text,
        re.IGNORECASE,
    )
    for a in amount_matches:
        if a not in claims:
            claims.append(a)

    return claims


def verify_fact_against_file(
    conn: sqlite3.Connection,
    file_id: int,
    claimed_value: str,
) -> bool:
    """
    Check that the claimed value exists in:
    1. The facts table for this file (value, value_date, or snippet)
    2. OR in the source file's stored text in the contents table.
    """
    clean_val = claimed_value.strip().lower()
    if not clean_val:
        return False

    # Check facts table
    cur = conn.execute(
        "SELECT value, value_date, snippet FROM facts WHERE file_id = ?",
        (file_id,),
    )
    fact_rows = cur.fetchall()
    for fr in fact_rows:
        val_str = (fr["value"] or "").lower()
        date_str = (fr["value_date"] or "").lower()
        snip_str = (fr["snippet"] or "").lower()
        if (
            clean_val == val_str
            or clean_val == date_str
            or clean_val in val_str
            or clean_val in snip_str
            or val_str in clean_val
        ):
            return True

    # Check stored text in contents table
    cur_content = conn.execute(
        "SELECT text FROM contents WHERE file_id = ?",
        (file_id,),
    )
    content_row = cur_content.fetchone()
    if content_row and content_row["text"]:
        stored_text = content_row["text"].lower()
        if clean_val in stored_text:
            return True

    return False


def verify_faithfulness(
    conn: sqlite3.Connection,
    message: str,
    results: list[dict[str, Any]],
) -> tuple[str, bool]:
    """
    Verify factual claims in `message` against the top source file in `results`.
    If no fact is claimed, returns (message, True).
    If a fact is claimed and confirmed, returns (message_with_citation, True).
    If a fact cannot be confirmed, drops the claim and returns:
    ("I couldn't confirm this from your files. Found matching document: {filename} ({path}).", False).
    Always includes the source filename and path when matching results exist.
    """
    claims = extract_factual_claims(message)
    if not claims or not results:
        return (message, True)

    top_result = results[0]
    file_id = top_result.get("id") or top_result.get("file_id")
    file_path = top_result.get("path", "")
    filename = top_result.get("filename", "")

    # Resolve file_id if missing
    if not file_id and file_path:
        cur = conn.execute("SELECT id FROM files WHERE path = ?", (file_path,))
        row = cur.fetchone()
        if row:
            file_id = row["id"]

    if not file_id:
        return (message, True)

    # Check every claimed value
    for claim in claims:
        is_verified = verify_fact_against_file(conn, file_id, claim)
        if not is_verified:
            # Drop claim and return safe unconfirmed message with source filename and path
            safe_msg = (
                f"I couldn't confirm this from your files (matching: {filename}, {file_path})."
                if filename and file_path
                else "I couldn't confirm this from your files."
            )
            return (safe_msg, False)

    # All claims confirmed. Ensure source filename and path are present in message.
    verified_msg = message
    if filename and file_path:
        if filename not in verified_msg or file_path not in verified_msg:
            # If citation is missing or only has filename, append full citation
            if f"(from {filename})" in verified_msg:
                verified_msg = verified_msg.replace(
                    f"(from {filename})",
                    f"(from {filename}, {file_path})",
                )
            elif f"({filename})" in verified_msg:
                verified_msg = verified_msg.replace(
                    f"({filename})",
                    f"({filename}, {file_path})",
                )
            elif not verified_msg.endswith("."):
                verified_msg = f"{verified_msg} (from {filename}, {file_path})."
            else:
                # Insert before trailing period
                verified_msg = f"{verified_msg[:-1]} (from {filename}, {file_path})."

    return (verified_msg, True)
