"""Rule-based query understanding without LLM.

Extracts cleaned search keywords, target file type extensions, and relative date boundaries
from user queries in English and Hinglish.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Multi-word filler phrases stripped first
FILLER_PHRASES = [
    r"\bshow\s+me\s+where\s+is\b",
    r"\bshow\s+me\s+where\b",
    r"\bshow\s+me\b",
    r"\bwhere\s+can\s+i\s+find\b",
    r"\bwhere\s+is\b",
    r"\bwhere\s+are\b",
    r"\bwhere\'s\b",
    r"\bcould\s+you\s+find\b",
    r"\bcould\s+you\s+show\b",
    r"\bcould\s+you\s+get\b",
    r"\bcould\s+you\b",
    r"\bcan\s+you\s+find\b",
    r"\bcan\s+you\s+show\b",
    r"\bcan\s+you\s+get\b",
    r"\bcan\s+you\b",
    r"\bcan\'?t\s+find\s+my\b",
    r"\bcan\'?t\s+find\b",
    r"\bcannot\s+find\s+my\b",
    r"\bcannot\s+find\b",
    r"\bso\s+annoying\b",
    r"\bannoying\b",
    r"\bfind\s+me\b",
    r"\bfind\s+my\b",
    r"\bsearch\s+for\b",
    r"\blook\s+for\b",
    r"\blooking\s+for\b",
    r"\bi\s+need\b",
    r"\bi\s+want\b",
    r"\bneed\s+my\b",
    r"\bget\s+me\b",
    r"\bgive\s+me\b",
    r"\bbring\s+me\b",
    r"\blist\s+all\b",
    r"\btell\s+me\b",
    r"\bkaha\s+pe\s+hai\b",
    r"\bkahan\s+pe\s+hai\b",
    r"\bkaha\s+hai\b",
    r"\bkahan\s+hai\b",
    r"\bkidhar\s+hai\b",
    r"\bdhund\s+ke\s+do\b",
    r"\bdhund\s+kar\s+do\b",
    r"\bdikha\s+do\b",
    r"\bbata\s+do\b",
    r"\bmujhe\s+chahiye\b",
]

# Single-word filler tokens stripped next
FILLER_WORDS = {
    "find",
    "search",
    "please",
    "kindly",
    "my",
    "me",
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "for",
    "from",
    "about",
    "in",
    "on",
    "at",
    "with",
    "by",
    "to",
    "of",
    "need",
    "want",
    "could",
    "would",
    "can",
    "will",
    "you",
    "your",
    "so",
    "annoying",
    "now",
    "urgent",
    "asap",
    "fast",
    "mera",
    "meri",
    "mere",
    "mujhe",
    "dikhao",
    "dhundo",
    "dhundho",
    "chahiye",
    "lao",
    "khojo",
    "batao",
    "kaha",
    "kahan",
    "kidhar",
    "hai",
    "hain",
    "tha",
    "thi",
    "the",
    "pe",
    "par",
    "se",
    "ko",
    "ka",
    "ki",
    "ke",
    "do",
    "de",
    "dena",
    "lo",
    "le",
    "lena",
    "wala",
    "wali",
    "wale",
    "jaldi",
    "turant",
    "fatafat",
    "yaar",
    "bhai",
    "bata",
    "aur",
    "bhi",
    "ek",
}

# File type keywords mapped to file extensions
FILE_TYPE_MAP: dict[str, list[str]] = {
    "pdf": [".pdf"],
    "word": [".docx", ".doc"],
    "doc": [".docx", ".doc"],
    "docx": [".docx", ".doc"],
    "excel": [".xlsx", ".csv"],
    "sheet": [".xlsx", ".csv"],
    "sheets": [".xlsx", ".csv"],
    "xlsx": [".xlsx"],
    "csv": [".csv"],
    "notes": [".txt", ".md"],
    "note": [".txt", ".md"],
    "image": [".png", ".jpg", ".jpeg"],
    "images": [".png", ".jpg", ".jpeg"],
    "photo": [".png", ".jpg", ".jpeg"],
    "photos": [".png", ".jpg", ".jpeg"],
    "picture": [".png", ".jpg", ".jpeg"],
    "pictures": [".png", ".jpg", ".jpeg"],
}

# Document type keywords mapped to standard doc_type categories
DOC_TYPE_MAP: dict[str, str] = {
    "certificate": "certificate",
    "certificates": "certificate",
    "certification": "certificate",
    "certif": "certificate",
    "diploma": "certificate",
    "degree": "certificate",
    "insurance": "insurance",
    "policy": "insurance",
    "bima": "insurance",
    "mediclaim": "insurance",
    "passport": "id_document",
    "passports": "id_document",
    "aadhaar": "id_document",
    "aadhar": "id_document",
    "pan": "id_document",
    "pancard": "id_document",
    "license": "id_document",
    "licence": "id_document",
    "voter": "id_document",
    "ticket": "ticket",
    "tickets": "ticket",
    "boarding": "ticket",
    "pnr": "ticket",
    "flight": "ticket",
    "train": "ticket",
    "bill": "financial",
    "bills": "financial",
    "invoice": "financial",
    "invoices": "financial",
    "receipt": "financial",
    "salary": "financial",
    "payslip": "financial",
    "tax": "financial",
    "itr": "financial",
    "warranty": "warranty",
    "guarantee": "warranty",
    "contract": "contract",
    "agreement": "contract",
    "nda": "contract",
    "lease": "contract",
    "resume": "resume",
    "cv": "resume",
    "biodata": "resume",
    "prescription": "medical",
    "doctor": "medical",
    "hospital": "medical",
    "marksheet": "education",
}

# Date phrases mapped to a callable returning a threshold datetime
DATE_PATTERNS = [
    (r"\btoday\b", "today"),
    (r"\baaj\b", "today"),
    (r"\byesterday\b", "yesterday"),
    (r"\bkal\b", "yesterday"),
    (r"\blast\s+week\b", "last_week"),
    (r"\blast\s+month\b", "last_month"),
    (r"\blast\s+year\b", "last_year"),
]


@dataclass
class ParsedQuery:
    original: str
    cleaned_query: str
    file_types: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)
    min_modified: float | None = None  # Unix epoch timestamp threshold
    source: str | None = None  # e.g. "gmail"
    sender: str | None = None  # e.g. "Alice"


def compute_date_threshold(date_type: str, now: datetime | None = None) -> float:
    """Return UNIX timestamp for date filter boundaries."""
    now = now or datetime.now()
    if date_type == "today":
        dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif date_type == "yesterday":
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        dt = today_start - timedelta(days=1)
    elif date_type == "last_week":
        dt = now - timedelta(days=7)
    elif date_type == "last_month":
        dt = now - timedelta(days=30)
    elif date_type == "last_year":
        dt = now - timedelta(days=365)
    else:
        dt = now
    return dt.timestamp()


def parse_query(raw_query: str, now: datetime | None = None) -> ParsedQuery:
    """
    Parse a user message:
    - Identifies and extracts relative date filters.
    - Identifies and extracts file type filters.
    - Strips filler words (English & Hinglish).
    - Returns a ParsedQuery with the cleaned search query and filters.
    """
    text = raw_query.strip()
    if not text:
        return ParsedQuery(original=raw_query, cleaned_query="")

    lower_text = text.lower()

    # 1. Detect Gmail source filter ("gmail", "email", "emails", "mail", "mails", "inbox")
    source: str | None = None
    if re.search(r"\b(gmail|emails?|mails?|inbox)\b", lower_text):
        source = "gmail"
        lower_text = re.sub(r"\b(gmail|emails?|mails?|inbox)\b", " ", lower_text)

    # 2. Detect and extract date filters
    min_modified: float | None = None
    for pattern, date_key in DATE_PATTERNS:
        if re.search(pattern, lower_text):
            min_modified = compute_date_threshold(date_key, now=now)
            lower_text = re.sub(pattern, " ", lower_text)

    # 3. Detect sender filter ("from <name>" or "from:<name>")
    sender: str | None = None
    sender_match = re.search(r"\bfrom[:\s]+([a-zA-Z0-9_\.\@\-]+)", lower_text)
    if sender_match:
        cand = sender_match.group(1).strip()
        if cand not in {"yesterday", "today", "last", "the", "my", "our", "me", "a", "an", "now"}:
            sender = cand
            lower_text = re.sub(rf"\bfrom[:\s]+{re.escape(cand)}\b", " ", lower_text)

    # 4. Detect and extract file type filters
    matched_types: list[str] = []
    for type_word, extensions in FILE_TYPE_MAP.items():
        type_pattern = rf"\b{type_word}\b"
        if re.search(type_pattern, lower_text):
            for ext in extensions:
                if ext not in matched_types:
                    matched_types.append(ext)
            lower_text = re.sub(type_pattern, " ", lower_text)

    # 5. Detect doc_types from query
    matched_doc_types: list[str] = []
    for word, d_type in DOC_TYPE_MAP.items():
        if re.search(rf"\b{word}\b", lower_text):
            if d_type not in matched_doc_types:
                matched_doc_types.append(d_type)

    # 6. Strip multi-word filler phrases
    for phrase_pattern in FILLER_PHRASES:
        lower_text = re.sub(phrase_pattern, " ", lower_text)

    # 7. Strip single-word filler tokens
    tokens = re.findall(r"\b[\w\-]+\b", lower_text)
    cleaned_tokens = [tok for tok in tokens if tok not in FILLER_WORDS]

    cleaned_query = " ".join(cleaned_tokens).strip()

    # Fallback: if everything was stripped, fall back to sender, source, non-filler tokens or original
    if not cleaned_query:
        if sender:
            cleaned_query = sender
        elif source == "gmail":
            cleaned_query = "gmail"
        else:
            cleaned_query = text

    return ParsedQuery(
        original=raw_query,
        cleaned_query=cleaned_query,
        file_types=matched_types,
        doc_types=matched_doc_types,
        min_modified=min_modified,
        source=source,
        sender=sender,
    )
