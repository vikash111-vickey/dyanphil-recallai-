"""Fact-based question answering for /ask endpoint.

Identifies fact questions such as:
- "when does X expire" -> looks up expiry/due date facts
- "what is my X number" -> looks up ID / policy / PNR / account facts
- "how much is X" -> looks up amount facts

Returns a tone-adapted direct answer plus the matching file result.
If no matching fact is found, returns None to allow seamless fallback to standard search.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from app.db import get_facts_by_file_id
from app.search.hybrid import hybrid_search
from app.search.query import parse_query
from app.search.verify import verify_faithfulness


# Question intent regex patterns
EXPIRY_PATTERNS = [
    re.compile(r"(?i)\bwhen\s+(?:does|will|is)\s+(?:my\s+)?(?P<subj>.+?)\s+(?:expire|due|valid\s+till|valid\s+until)\b"),
    re.compile(r"(?i)\bwhen\s+is\s+(?:my\s+)?(?P<subj>.+?)\s+(?:due|expiring|renewal)\b"),
    re.compile(r"(?i)\b(?:expiry|due|renewal)\s+date\s+(?:of|for)\s+(?:my\s+)?(?P<subj>.+)\b"),
    re.compile(r"(?i)\bvalidity\s+(?:of|for)\s+(?:my\s+)?(?P<subj>.+)\b"),
    re.compile(r"(?i)\b(?:my\s+)?(?P<subj>.+?)\s+(?:expiry|validity|due\s+date)\b"),
    re.compile(r"(?i)\b(?:mera\s+|meri\s+)?(?P<subj>.+?)\s+kab\s+(?:expire|tak\s+valid)\b"),
]

ID_PATTERNS = [
    re.compile(r"(?i)\bwhat\s+is\s+(?:my\s+|the\s+)?(?P<subj>.+?)\s+(?:number|no|id|pnr|code)\b"),
    re.compile(r"(?i)\b(?:my\s+)?(?P<subj>.+?)\s+(?:number|no|id|pnr)\b"),
    re.compile(r"(?i)\b(?:mera\s+|meri\s+)?(?P<subj>.+?)\s+(?:ka\s+)?(?:number|no|id|pnr)\b"),
]

AMOUNT_PATTERNS = [
    re.compile(r"(?i)\bhow\s+much\s+(?:is|was|did)\s+(?:my\s+)?(?P<subj>.+?)(?:\s+cost)?$"),
    re.compile(r"(?i)\bwhat\s+is\s+(?:the\s+)?(?:cost|price|amount|total)\s+(?:of|for)\s+(?:my\s+)?(?P<subj>.+)$"),
    re.compile(r"(?i)\b(?:my\s+)?(?P<subj>.+?)\s+(?:cost|price|amount|bill|kharcha)$"),
]

CLEAN_FILLER = re.compile(
    r"(?i)\b(?:please|kindly|tell\s+me|show\s+me|can\s+you|find|mera|meri|mujhe|batao|kya\s+hai|the|my|a|an)\b",
)


def _clean_subject(raw: str) -> str:
    """Clean the extracted subject noun phrase."""
    s = CLEAN_FILLER.sub(" ", raw)
    s = re.sub(r"[?!.,'\"]+", " ", s)
    return " ".join(s.split()).strip()


def detect_fact_intent(query_text: str) -> tuple[str, str] | None:
    """
    Detect whether a query is asking for a specific fact.
    Returns (intent_type, subject) or None.
    intent_type: "expiry", "id_number", "amount"
    """
    # 1. Check Expiry
    for pat in EXPIRY_PATTERNS:
        m = pat.search(query_text)
        if m:
            subj = _clean_subject(m.group("subj"))
            if subj:
                return ("expiry", subj)

    # 2. Check ID Number
    for pat in ID_PATTERNS:
        m = pat.search(query_text)
        if m:
            subj = _clean_subject(m.group("subj"))
            if subj:
                return ("id_number", subj)

    # 3. Check Amount
    for pat in AMOUNT_PATTERNS:
        m = pat.search(query_text)
        if m:
            subj = _clean_subject(m.group("subj"))
            if subj:
                return ("amount", subj)

    return None


def format_fact_answer(
    intent: str,
    subject: str,
    fact: sqlite3.Row | dict[str, Any],
    tone: str,
    filename: str = "",
    path: str = "",
) -> str:
    """Compose a concise answer in the composer's tone including source filename and path."""
    val = fact["value"]
    label = fact["label"].lower()
    if filename and path:
        source_cite = f" (from {filename}, {path})"
    elif filename:
        source_cite = f" (from {filename})"
    else:
        source_cite = ""

    if intent == "expiry":
        action = "is due on" if "due" in label else "expires on"
        core = f"Your {subject} {action} {val}{source_cite}."
    elif intent == "id_number":
        core = f"Your {subject} number is {val}{source_cite}."
    elif intent == "amount":
        core = f"Your {subject} is {val}{source_cite}."
    else:
        core = f"Your {subject} {label} is {val}{source_cite}."

    if tone in ("urgent", "stressed"):
        return core
    elif tone == "frustrated":
        return f"Here is what you need: {core[0].lower() + core[1:]}"
    else:  # casual / neutral
        return core


def find_fact_answer(
    conn: sqlite3.Connection,
    raw_query: str,
    tone: str = "neutral",
) -> tuple[str, list[dict[str, Any]]] | None:
    """
    Look up the facts table for the best matching file answering the fact question.
    Returns (answer_sentence, matching_search_results).
    If a fact intent is recognized but no fact is found, returns a safe "not found"
    answer rather than guessing or hallucinating.
    Returns None if the query is not asking for a fact.
    """
    intent_data = detect_fact_intent(raw_query)
    if not intent_data:
        return None

    intent, subject = intent_data
    parsed = parse_query(subject)
    search_terms = parsed.cleaned_query if parsed.cleaned_query else subject

    # Find the best candidate file for this subject
    candidates = hybrid_search(
        conn=conn,
        query=search_terms,
        mode="hybrid",
        limit=5,
        doc_types=parsed.doc_types,
    )

    if candidates:
        for cand in candidates:
            # Fetch file_id from DB
            cur = conn.execute("SELECT id, doc_type FROM files WHERE path = ?", (cand["path"],))
            file_row = cur.fetchone()
            if not file_row:
                continue
            fid = file_row["id"]
            doc_type = file_row["doc_type"] or "other"

            facts = get_facts_by_file_id(conn, fid)
            if not facts:
                continue

            for fact in facts:
                f_kind = fact["kind"]
                f_label = fact["label"].lower()

                matched = False
                if intent == "expiry":
                    if f_kind in ("expiry", "due_date") or any(k in f_label for k in ("expir", "valid", "due", "renew")):
                        matched = True
                elif intent == "id_number":
                    if f_kind == "id_number" or bool(re.search(r"\b(?:id|no|number|pnr|policy|passport|licen|card|pan|aadhaar)\b", f_label)):
                        if f_kind not in ("expiry", "due_date", "date", "amount"):
                            matched = True
                elif intent == "amount":
                    if f_kind == "amount" or bool(re.search(r"\b(?:amount|total|premium|bill|rent|fee|cost|price|subtotal|grand\s+total)\b", f_label)):
                        if f_kind not in ("expiry", "due_date", "date"):
                            matched = True

                if matched:
                    fname = cand["filename"]
                    fpath = cand["path"]
                    raw_answer = format_fact_answer(
                        intent,
                        subject,
                        fact,
                        tone,
                        filename=fname,
                        path=fpath,
                    )
                    cand_copy = dict(cand)
                    cand_copy["doc_type"] = doc_type

                    # Faithfulness verification against DB facts and contents
                    verified_answer, _ = verify_faithfulness(
                        conn,
                        raw_answer,
                        [cand_copy],
                    )
                    return (verified_answer, [cand_copy])

    # Safeguard: Fact intent was detected, but no matching fact found in indexed documents
    if candidates:
        top_cand = candidates[0]
        fname = top_cand["filename"]
        fpath = top_cand["path"]
        reply_msg = f"I couldn't confirm this from your files (matching: {fname}, {fpath})."
        return (reply_msg, candidates[:5])

    if intent == "expiry":
        no_fact_msg = f"I couldn't find an expiry or due date for {subject} in your indexed documents."
    elif intent == "id_number":
        no_fact_msg = f"I couldn't find an ID or document number for {subject} in your indexed documents."
    elif intent == "amount":
        no_fact_msg = f"I couldn't find an amount or cost for {subject} in your indexed documents."
    else:
        no_fact_msg = f"I couldn't find the requested information for {subject} in your indexed documents."

    if tone in ("urgent", "stressed"):
        reply_msg = no_fact_msg
    elif tone == "frustrated":
        reply_msg = f"I looked through your documents, but {no_fact_msg[0].lower() + no_fact_msg[1:]}"
    else:
        reply_msg = f"{no_fact_msg} You might want to check if the file is indexed."

    return (reply_msg, [])
