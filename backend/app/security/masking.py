"""Sensitive data masking module for Dyanphil.

Masks:
- 12-digit Aadhaar-like numbers (keeps last 4 digits)
- PAN numbers (keeps last 4 characters)
- Card-like 13-19 digit numbers (keeps last 4 digits)
- Anything after keywords: password, pwd, passcode, OTP
"""

from __future__ import annotations

import re
from typing import Any


def mask_cards(text: str) -> str:
    """Mask card numbers (13-19 digits, with optional spaces or dashes), keeping last 4 digits."""
    def _mask_card(match: re.Match) -> str:
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if 13 <= len(digits) <= 19:
            return f"****-****-****-{digits[-4:]}"
        return raw

    pattern = re.compile(r"\b(?:\d{4}[ -]){3}\d{1,4}\b|\b(?:\d{4}[ -]){4}\d{1,4}\b|\b\d{13,19}\b")
    return pattern.sub(_mask_card, text)


def mask_aadhaar(text: str) -> str:
    """Mask 12-digit Aadhaar-like numbers, keeping last 4 digits (e.g. XXXX-XXXX-1234)."""
    def _mask_aadhaar(match: re.Match) -> str:
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 12:
            return f"XXXX-XXXX-{digits[-4:]}"
        return raw

    return re.sub(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", _mask_aadhaar, text)


def mask_pan(text: str) -> str:
    """Mask 10-character PAN (5 letters, 4 digits, 1 letter), keeping last 4 characters."""
    def _mask_pan(match: re.Match) -> str:
        pan = match.group(0)
        return f"XXXXXX{pan[-4:]}"

    return re.sub(r"\b[A-Za-z]{5}[0-9]{4}[A-Za-z]\b", _mask_pan, text)


def mask_passwords_and_otps(text: str) -> str:
    """
    Mask anything after the words password, pwd, passcode, OTP.
    Example:
    'password: secret123' -> 'password: [REDACTED]'
    'pwd = 1234' -> 'pwd = [REDACTED]'
    'passcode: 9876' -> 'passcode: [REDACTED]'
    'OTP is 456789. Do not share.' -> 'OTP is [REDACTED]. Do not share.'
    """
    pattern = re.compile(
        r"(?i)\b(password|pwd|passcode|otp)\b(\s*(?:[:=–—\-]\s*|is\s+|\s))([^\s,;\r\n\.]+)([\.]?)",
    )
    return pattern.sub(r"\g<1>\g<2>[REDACTED]\g<4>", text)


def mask_all_sensitive(text: str) -> str:
    """
    Apply all sensitive data masking rules to the text in sequence:
    1. Cards (13-19 digits, checked first before Aadhaar)
    2. Aadhaar (12 digits)
    3. PAN (10 characters)
    4. Passwords / PWD / Passcode / OTP
    """
    if not text:
        return ""
    s = str(text)
    s = mask_cards(s)
    s = mask_aadhaar(s)
    s = mask_pan(s)
    s = mask_passwords_and_otps(s)
    return s


def mask_obj(obj: Any) -> Any:
    """Recursively mask sensitive data in strings, dicts, and lists."""
    if isinstance(obj, str):
        return mask_all_sensitive(obj)
    elif isinstance(obj, list):
        return [mask_obj(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(mask_obj(v) for v in obj)
    elif isinstance(obj, dict):
        return {k: mask_obj(v) for k, v in obj.items()}
    return obj
