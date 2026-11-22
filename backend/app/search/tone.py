"""Rule-based tone and urgency detection for English and Hinglish messages."""

from __future__ import annotations

import re
from typing import TypedDict


class ToneResult(TypedDict):
    tone: str  # "urgent" | "stressed" | "frustrated" | "casual" | "neutral"
    urgency: str  # "low" | "medium" | "high"


URGENT_PATTERNS = [
    r"\burgent\b",
    r"\basap\b",
    r"\bemergency\b",
    r"\bturant\b",
    r"\bjaldi\b",
    r"\bfatafat\b",
    r"\bright\s+now\b",
    r"\bimmediately\b",
    r"\bat\s+once\b",
    r"\bfast\b",
    r"\bekdum\s+jaldi\b",
    r"\bnow\b",
]

FRUSTRATED_PATTERNS = [
    r"\bcan\'?t\s+find\b",
    r"\bcannot\s+find\b",
    r"\bnot\s+working\b",
    r"\bwhere\s+the\s+hell\b",
    r"\bkaha\s+chala\s+gaya\b",
    r"\bnahi\s+mil\s+raha\b",
    r"\bnahi\s+mil\s+rha\b",
    r"\birritating\b",
    r"\bannoying\b",
    r"\bso\s+annoying\b",
    r"\bpissed\b",
    r"\bhate\b",
    r"\bstuck\b",
    r"\bbekaar\b",
    r"\bbakwaas\b",
    r"\bfed\s+up\b",
    r"\buseless\b",
    r"\bdamn\b",
    r"\bdammit\b",
]

STRESSED_PATTERNS = [
    r"\bhelp\b",
    r"\bpanic\b",
    r"\bstressed\b",
    r"\bworried\b",
    r"\blost\b",
    r"\bimportant\b",
    r"\bbachao\b",
    r"\bmadad\b",
    r"\bscared\b",
    r"\btension\b",
]

CASUAL_PATTERNS = [
    r"\bhey\b",
    r"\bhi\b",
    r"\bhello\b",
    r"\bcould\s+you\b",
    r"\bcan\s+you\b",
    r"\bbro\b",
    r"\byaar\b",
    r"\bkya\s+haal\b",
    r"\bjust\s+checking\b",
    r"\bwondering\b",
    r"\bany\s+chance\b",
    r"\bbhai\b",
    r"\bcool\b",
    r"\bsup\b",
    r"\byo\b",
]


def detect_tone(message: str) -> ToneResult:
    """
    Detect tone (urgent, stressed, frustrated, casual, neutral)
    and urgency (low, medium, high) from user input using rule-based signals.
    """
    raw = message.strip()
    if not raw:
        return {"tone": "neutral", "urgency": "low"}

    lower = raw.lower()

    # 1. Evaluate urgency signals
    is_all_caps = len(raw) > 4 and any(c.isalpha() for c in raw) and raw.isupper()
    has_triple_exclamation = "!!!" in raw
    has_single_exclamation = "!" in raw

    has_urgent_keyword = any(re.search(pat, lower) for pat in URGENT_PATTERNS)
    has_frustrated_keyword = any(re.search(pat, lower) for pat in FRUSTRATED_PATTERNS)
    has_stressed_keyword = any(re.search(pat, lower) for pat in STRESSED_PATTERNS)
    has_casual_keyword = any(re.search(pat, lower) for pat in CASUAL_PATTERNS)

    # 2. Determine Tone
    if has_urgent_keyword:
        tone = "urgent"
    elif has_stressed_keyword:
        tone = "stressed"
    elif has_frustrated_keyword:
        tone = "frustrated"
    elif has_casual_keyword:
        tone = "casual"
    else:
        tone = "neutral"

    # 3. Determine Urgency
    if has_urgent_keyword or has_triple_exclamation or (is_all_caps and len(raw.split()) > 1):
        urgency = "high"
    elif tone in ("stressed", "frustrated") or has_single_exclamation or "please" in lower:
        urgency = "medium"
    else:
        urgency = "low"

    return {"tone": tone, "urgency": urgency}
