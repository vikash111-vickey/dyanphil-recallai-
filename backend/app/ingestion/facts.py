"""Fact extraction using regex and rules without LLM.

Extracts key structured facts from document text:
- Dates tied to labels (expiry, expires, valid until, valid till, renewal, due date, issued on, date of issue, date of birth)
- Amounts (Rs, INR, ₹, $) with their labels
- ID numbers with labels (policy no, booking id, PNR, passport no, licence no, certificate id, etc.)
- Email addresses and phone numbers

Privacy rules:
- Mask Aadhaar-like 12-digit numbers (keep only last 4 digits)
- Mask PAN numbers (keep only last 4 characters/digits)
- Mask card-like 13-19 digit numbers (keep only last 4 digits)
- Never store passwords or OTPs
- Cap at 30 facts per file
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.security.masking import mask_all_sensitive as mask_sensitive_data


@dataclass
class ExtractedFact:
    kind: str
    label: str
    value: str
    value_date: str | None = None
    snippet: str = ""


# Month name mapping
MONTHS_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Forbidden secret patterns (passwords, OTPs, PINs)
FORBIDDEN_SECRET_PATTERN = re.compile(
    r"\b(?:password|passwd|pwd|otp|one\s*time\s*password|secret\s*key|pin\s*code|cvv|cvc)\b",
    re.IGNORECASE,
)


def parse_and_normalize_date(date_str: str) -> str | None:
    """
    Parse date from common formats and return ISO YYYY-MM-DD.
    Supported formats:
    - 14 Aug 2026, 14 August 2026, 14th Aug 2026, 14-Aug-2026
    - August 14 2026, August 14, 2026, Aug 14, 2026
    - 14/08/2026, 14-08-2026, 14.08.2026
    - 2026-08-14, 2026/08/14
    """
    clean = date_str.strip().strip(",").strip(".")
    if not clean:
        return None

    # 1. ISO format: YYYY-MM-DD or YYYY/MM/DD
    m = re.match(r"^(19\d\d|20\d\d)[-/.]([01]?\d)[-/.]([0-3]?\d)$", clean)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return date(y, mo, d).isoformat()
        except ValueError:
            pass

    # 2. DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    m = re.match(r"^([0-3]?\d)[-/.]([01]?\d)[-/.](19\d\d|20\d\d)$", clean)
    if m:
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return date(y, mo, d).isoformat()
        except ValueError:
            pass

    # 3. DD Month YYYY (e.g. 14 Aug 2026, 14th August 2026, 14-Aug-2026)
    m = re.match(
        r"^([0-3]?\d)(?:st|nd|rd|th)?[\s\-_/.]([a-zA-Z]{3,9})[\s\-_/.](19\d\d|20\d\d|\d\d)$",
        clean,
    )
    if m:
        day_val = int(m.group(1))
        month_name = m.group(2).lower()
        yr_val = int(m.group(3))
        if yr_val < 100:
            yr_val += 2000
        month_val = MONTHS_MAP.get(month_name)
        if month_val:
            try:
                return date(yr_val, month_val, day_val).isoformat()
            except ValueError:
                pass

    # 4. Month DD, YYYY (e.g. August 14, 2026 or Aug 14 2026)
    m = re.match(
        r"^([a-zA-Z]{3,9})[\s\-_/.]([0-3]?\d)(?:st|nd|rd|th)?[\s\-_/.,]+(19\d\d|20\d\d|\d\d)$",
        clean,
    )
    if m:
        month_name = m.group(1).lower()
        day_val = int(m.group(2))
        yr_val = int(m.group(3))
        if yr_val < 100:
            yr_val += 2000
        month_val = MONTHS_MAP.get(month_name)
        if month_val:
            try:
                return date(yr_val, month_val, day_val).isoformat()
            except ValueError:
                pass

    return None


def _make_snippet(text: str, start: int, end: int, window: int = 50) -> str:
    """Extract snippet surrounding a matched span and mask private details."""
    left = max(0, start - window)
    right = min(len(text), end + window)
    raw = text[left:right].replace("\n", " ").strip()
    return mask_sensitive_data(raw)


def extract_facts(
    text: str,
    filename: str = "",
    path: str = "",
    max_facts: int = 30,
) -> list[ExtractedFact]:
    """
    Extract structured facts from text using regex rules.
    Enforces privacy rules (masking Aadhaar, PAN, card numbers; never storing passwords/OTPs).
    Capped at max_facts (default 30).
    """
    if not text:
        return []

    facts: list[ExtractedFact] = []
    seen: set[tuple[str, str, str]] = set()

    def add_fact(kind: str, label: str, value: str, value_date: str | None, snippet: str) -> None:
        if len(facts) >= max_facts:
            return

        # Check privacy rule: never store passwords or OTPs
        if FORBIDDEN_SECRET_PATTERN.search(label) or FORBIDDEN_SECRET_PATTERN.search(value):
            return

        masked_val = mask_sensitive_data(value.strip())
        masked_snip = mask_sensitive_data(snippet.strip())
        norm_key = (kind, label.lower().strip(), masked_val.lower())
        if norm_key in seen:
            return
        seen.add(norm_key)

        facts.append(
            ExtractedFact(
                kind=kind,
                label=label.strip(),
                value=masked_val,
                value_date=value_date,
                snippet=masked_snip,
            )
        )

    # -------------------------------------------------------------
    # 1. Dates tied to labels
    # -------------------------------------------------------------
    DATE_LABEL_PATTERNS = [
        # Expiry / Due / Renewal / Validity
        (
            r"(?i)\b(valid\s+until|valid\s+till|valid\s+upto|valid\s+to|validity|expiry\s+date|expires\s+on|expiry|expires|renewal\s+date|renewal|due\s+date|pay\s+by)[\s:\-–—=]+([0-3]?\d(?:st|nd|rd|th)?[\s\-_/.][a-zA-Z]{3,9}[\s\-_/.](?:19\d\d|20\d\d|\d\d)|[a-zA-Z]{3,9}[\s\-_/.][0-3]?\d(?:st|nd|rd|th)?[\s\-_/.,]+(?:19\d\d|20\d\d|\d\d)|(?:19\d\d|20\d\d)[-/.][01]?\d[-/.][0-3]?\d|[0-3]?\d[-/.][01]?\d[-/.](?:19\d\d|20\d\d))",
            "expiry",
        ),
        # Issue / Start
        (
            r"(?i)\b(date\s+of\s+issue|issued\s+on|issued\s+date|issue\s+date)[\s:\-–—=]+([0-3]?\d(?:st|nd|rd|th)?[\s\-_/.][a-zA-Z]{3,9}[\s\-_/.](?:19\d\d|20\d\d|\d\d)|[a-zA-Z]{3,9}[\s\-_/.][0-3]?\d(?:st|nd|rd|th)?[\s\-_/.,]+(?:19\d\d|20\d\d|\d\d)|(?:19\d\d|20\d\d)[-/.][01]?\d[-/.][0-3]?\d|[0-3]?\d[-/.][01]?\d[-/.](?:19\d\d|20\d\d))",
            "date",
        ),
        # Date of Birth
        (
            r"(?i)\b(date\s+of\s+birth|dob|birth\s+date)[\s:\-–—=]+([0-3]?\d(?:st|nd|rd|th)?[\s\-_/.][a-zA-Z]{3,9}[\s\-_/.](?:19\d\d|20\d\d|\d\d)|[a-zA-Z]{3,9}[\s\-_/.][0-3]?\d(?:st|nd|rd|th)?[\s\-_/.,]+(?:19\d\d|20\d\d|\d\d)|(?:19\d\d|20\d\d)[-/.][01]?\d[-/.][0-3]?\d|[0-3]?\d[-/.][01]?\d[-/.](?:19\d\d|20\d\d))",
            "date",
        ),
    ]

    for pat, kind_category in DATE_LABEL_PATTERNS:
        for match in re.finditer(pat, text):
            raw_label = match.group(1).title()
            raw_date = match.group(2)
            iso_date = parse_and_normalize_date(raw_date)
            snip = _make_snippet(text, match.start(), match.end())
            kind = "expiry" if any(w in raw_label.lower() for w in ("expir", "valid", "due", "renew")) else kind_category
            add_fact(
                kind=kind,
                label=raw_label,
                value=raw_date,
                value_date=iso_date,
                snippet=snip,
            )

    # -------------------------------------------------------------
    # 2. Amounts with labels
    # -------------------------------------------------------------
    # Matches: Total Amount: ₹12,500 | Grand Total: $150.00 | Premium: Rs. 12500
    AMOUNT_PATTERN = re.compile(
        r"(?i)\b(total\s+amount|total\s+payable|grand\s+total|subtotal|amount\s+due|net\s+pay|premium\s+amount|premium|balance\s+due|bill\s+amount|fee|rent|fare|cost|price|amount)[\s:\-–—=]+(₹|rs\.?|inr|\$|usd)?\s*((?:[0-9]{1,3}(?:,[0-9]{2,3})+|[0-9]+)(?:\.[0-9]{1,2})?)",
    )
    for match in AMOUNT_PATTERN.finditer(text):
        label = match.group(1).title()
        curr = match.group(2) or "₹"
        num = match.group(3)
        formatted_val = f"{curr}{num}" if not curr.endswith(".") else f"{curr} {num}"
        snip = _make_snippet(text, match.start(), match.end())
        add_fact(
            kind="amount",
            label=label,
            value=formatted_val,
            value_date=None,
            snippet=snip,
        )

    # Standalone amounts with currency symbols if not matched above
    STANDALONE_CURRENCY_PATTERN = re.compile(
        r"(₹|rs\.?|inr|\$)\s*((?:[0-9]{1,3}(?:,[0-9]{2,3})+|[0-9]{3,})(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    )
    for match in STANDALONE_CURRENCY_PATTERN.finditer(text):
        curr = match.group(1)
        num = match.group(2)
        val = f"{curr}{num}" if not curr.endswith(".") else f"{curr} {num}"
        snip = _make_snippet(text, match.start(), match.end())
        add_fact(
            kind="amount",
            label="Amount",
            value=val,
            value_date=None,
            snippet=snip,
        )

    # -------------------------------------------------------------
    # 3. ID numbers with labels
    # -------------------------------------------------------------
    ID_PATTERN = re.compile(
        r"(?i)\b(policy\s+no(?:umber)?|booking\s+id|booking\s+ref(?:erence)?|pnr(?:\s+no)?|passport\s+no(?:umber)?|licen[sc]e\s+no(?:umber)?|driving\s+licen[sc]e(?:\s+no)?|certificate\s+id|certificate\s+no(?:umber)?|account\s+no(?:umber)?|invoice\s+no(?:umber)?|bill\s+no(?:umber)?|ticket\s+no(?:umber)?|order\s+id|roll\s+no(?:umber)?|registration\s+no(?:umber)?|voter\s+id|epic\s+no|pan(?:\s+no(?:umber)?)?|aadhaar(?:\s+no(?:umber)?)?|aadhar(?:\s+no(?:umber)?)?)[\s:\-–—=#]+([a-zA-Z0-9\-\/ ]{3,35})\b",
    )
    for match in ID_PATTERN.finditer(text):
        label = match.group(1).title()
        raw_val = match.group(2).strip()

        # If it contains multiple words that aren't spaced digits, take first token
        if " " in raw_val and not re.match(r"^\d{4}\s\d{4}\s\d{4}$", raw_val):
            # Take just the first alphanumeric token
            parts = raw_val.split()
            if parts:
                raw_val = parts[0]

        # Check for forbidden secrets
        if FORBIDDEN_SECRET_PATTERN.search(label) or FORBIDDEN_SECRET_PATTERN.search(raw_val):
            continue

        snip = _make_snippet(text, match.start(), match.end())
        add_fact(
            kind="id_number",
            label=label,
            value=raw_val,
            value_date=None,
            snippet=snip,
        )

    # Standalone PAN patterns in text: e.g. ABCDE1234F
    PAN_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{5}[0-9]{4}[A-Za-z](?![A-Za-z0-9])")
    for match in PAN_PATTERN.finditer(text):
        pan = match.group(0)
        snip = _make_snippet(text, match.start(), match.end())
        add_fact(
            kind="id_number",
            label="PAN Number",
            value=pan,
            value_date=None,
            snippet=snip,
        )

    # Standalone Card numbers (13-19 digits, e.g. 4111 2222 3333 4444)
    CARD_PATTERN = re.compile(r"(?<!\d)(?:\d{4}[\s-]){3}\d{1,7}(?!\d)")
    for match in CARD_PATTERN.finditer(text):
        card_val = match.group(0)
        snip = _make_snippet(text, match.start(), match.end())
        add_fact(
            kind="id_number",
            label="Card Number",
            value=card_val,
            value_date=None,
            snippet=snip,
        )

    # Standalone Aadhaar-like 12-digit numbers
    AADHAAR_PATTERN = re.compile(r"(?<!\d)(?<!\d{4}[\s-])\d{4}[\s-]\d{4}[\s-]\d{4}(?!\d)(?![\s-]\d{4})")
    for match in AADHAAR_PATTERN.finditer(text):
        raw_val = match.group(0)
        digits = re.sub(r"\D", "", raw_val)
        if len(digits) == 12:
            snip = _make_snippet(text, match.start(), match.end())
            add_fact(
                kind="id_number",
                label="Aadhaar Number",
                value=raw_val,
                value_date=None,
                snippet=snip,
            )

    # -------------------------------------------------------------
    # 4. Email addresses and Phone numbers
    # -------------------------------------------------------------
    EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
    for match in EMAIL_PATTERN.finditer(text):
        email_str = match.group(0)
        snip = _make_snippet(text, match.start(), match.end())
        add_fact(
            kind="email",
            label="Email",
            value=email_str,
            value_date=None,
            snippet=snip,
        )

    # Indian and general phone patterns (10 digits starting with 6-9, or prefixed by +91 / 91)
    PHONE_PATTERN = re.compile(
        r"(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b",
    )
    for match in PHONE_PATTERN.finditer(text):
        phone_str = match.group(0)
        snip = _make_snippet(text, match.start(), match.end())
        add_fact(
            kind="phone",
            label="Phone",
            value=phone_str,
            value_date=None,
            snippet=snip,
        )

    return facts
