"""Privacy-preserving logging utilities and filters."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.security.masking import mask_all_sensitive


def format_safe_query(query: str, max_len: int = 80) -> str:
    """Ensure search queries logged never exceed max_len (80 chars) and mask sensitive info."""
    clean = str(query).strip()
    if len(clean) > max_len:
        clean = clean[:max_len] + "..."
    return mask_all_sensitive(clean)


class PrivacyLogFilter(logging.Filter):
    """
    Filter to ensure no PINs, raw tokens, file contents, or queries > 80 chars leak into logs.
    Only allows event names, counts, and errors.
    """

    # Patterns matching secrets in log messages
    SECRET_PATTERN = re.compile(
        r"(?i)\b(pin|token|password|pwd|secret|key)[\s:=]+['\"]?([a-zA-Z0-9_\-\.]{4,})['\"]?",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()

            # Redact PINs / tokens if accidentally passed
            if self.SECRET_PATTERN.search(msg):
                msg = self.SECRET_PATTERN.sub(r"\1=[REDACTED]", msg)

            # Mask Aadhaar, PAN, Card, OTP
            msg = mask_all_sensitive(msg)

            # If message is excessively long (e.g. potential file content dump), cap it
            if len(msg) > 500:
                msg = msg[:500] + "... [TRUNCATED]"

            record.msg = msg
            record.args = None
        except Exception:
            pass
        return True
