"""Tests for query cleaning and tone detection across 25 English and Hinglish messages."""

from __future__ import annotations

import pytest

from app.search.query import parse_query
from app.search.tone import detect_tone


MESSAGES = [
    # 1. User specified 5 mandatory cases
    {
        "text": "mera passport kaha hai jaldi",
        "expected_tone": "urgent",
        "expected_keyword": "passport",
        "expected_doc_type": "id_document",
    },
    {
        "text": "insurance wali pdf dikhao",
        "expected_file_type": ".pdf",
        "expected_keyword": "insurance",
        "expected_doc_type": "insurance",
    },
    {
        "text": "URGENT!!! need my ticket now",
        "expected_tone": "urgent",
        "expected_urgency": "high",
        "expected_keyword": "ticket",
        "expected_doc_type": "ticket",
    },
    {
        "text": "can't find my resume, so annoying",
        "expected_tone": "frustrated",
        "expected_keyword": "resume",
        "expected_doc_type": "resume",
    },
    {
        "text": "hey could you find the bill from last month",
        "expected_tone": "casual",
        "expected_keyword": "bill",
        "expected_doc_type": "financial",
        "has_date_filter": True,
    },
    # 2. Additional 20 cases covering Hinglish and English queries
    {
        "text": "bhai meri flight ticket kidhar hai",
        "expected_keyword": "ticket",
        "expected_doc_type": "ticket",
    },
    {
        "text": "EMERGENCY: need medical prescription right now",
        "expected_tone": "urgent",
        "expected_urgency": "high",
        "expected_keyword": "prescription",
        "expected_doc_type": "medical",
    },
    {
        "text": "where did I save my rental agreement docx",
        "expected_file_type": ".docx",
        "expected_keyword": "agreement",
        "expected_doc_type": "contract",
    },
    {
        "text": "kaha chala gaya mera pan card yaar",
        "expected_tone": "frustrated",
        "expected_keyword": "pan",
        "expected_doc_type": "id_document",
    },
    {
        "text": "hello, please show me the salary slip from last year",
        "expected_tone": "casual",
        "expected_keyword": "salary",
        "expected_doc_type": "financial",
        "has_date_filter": True,
    },
    {
        "text": "aaj ka invoice dhund ke do",
        "expected_keyword": "invoice",
        "expected_doc_type": "financial",
        "has_date_filter": True,
    },
    {
        "text": "can you get me the doctor prescription image",
        "expected_file_type": ".png",
        "expected_keyword": "prescription",
        "expected_doc_type": "medical",
    },
    {
        "text": "i'm so stressed about my lost passport",
        "expected_tone": "stressed",
        "expected_keyword": "passport",
        "expected_doc_type": "id_document",
    },
    {
        "text": "purana wala electricity bill dikha do",
        "expected_keyword": "bill",
        "expected_doc_type": "financial",
    },
    {
        "text": "ASAP send me the contract agreement",
        "expected_tone": "urgent",
        "expected_keyword": "contract",
        "expected_doc_type": "contract",
    },
    {
        "text": "not working at all, where is my graduation marksheet",
        "expected_tone": "frustrated",
        "expected_keyword": "marksheet",
        "expected_doc_type": "education",
    },
    {
        "text": "sup bro check my resume notes",
        "expected_tone": "casual",
        "expected_file_type": ".txt",
        "expected_keyword": "resume",
        "expected_doc_type": "resume",
    },
    {
        "text": "fatafat policy document open karo",
        "expected_tone": "urgent",
        "expected_keyword": "policy",
        "expected_doc_type": "insurance",
    },
    {
        "text": "help me panic lost my warranty card",
        "expected_tone": "stressed",
        "expected_keyword": "warranty",
        "expected_doc_type": "warranty",
    },
    {
        "text": "yesterday ka boarding pass dikhao",
        "expected_keyword": "boarding",
        "expected_doc_type": "ticket",
        "has_date_filter": True,
    },
    {
        "text": "please list all excel sheets",
        "expected_file_type": ".xlsx",
    },
    {
        "text": "bakwaas service, where is my tax return itr",
        "expected_tone": "frustrated",
        "expected_keyword": "itr",
        "expected_doc_type": "financial",
    },
    {
        "text": "hi just checking the lease agreement",
        "expected_tone": "casual",
        "expected_keyword": "lease",
        "expected_doc_type": "contract",
    },
    {
        "text": "madad karo mera aadhaar card nahi mil raha",
        "expected_tone": "stressed",
        "expected_keyword": "aadhaar",
        "expected_doc_type": "id_document",
    },
    {
        "text": "immediately find my car insurance policy",
        "expected_tone": "urgent",
        "expected_keyword": "insurance",
        "expected_doc_type": "insurance",
    },
]


@pytest.mark.parametrize("case", MESSAGES)
def test_language_query_cleaning_and_tone(case: dict):
    raw_text = case["text"]

    # 1. Test Tone Detection
    tone_res = detect_tone(raw_text)
    if "expected_tone" in case:
        assert tone_res["tone"] == case["expected_tone"], (
            f"Expected tone {case['expected_tone']} but got {tone_res['tone']} for '{raw_text}'"
        )
    if "expected_urgency" in case:
        assert tone_res["urgency"] == case["expected_urgency"], (
            f"Expected urgency {case['expected_urgency']} but got {tone_res['urgency']} for '{raw_text}'"
        )

    # 2. Test Query Cleaning & Understanding
    parsed = parse_query(raw_text)

    if "expected_keyword" in case:
        assert case["expected_keyword"] in parsed.cleaned_query.lower(), (
            f"Expected keyword '{case['expected_keyword']}' in cleaned query '{parsed.cleaned_query}' for '{raw_text}'"
        )

    if "expected_file_type" in case:
        assert case["expected_file_type"] in parsed.file_types, (
            f"Expected file type '{case['expected_file_type']}' in '{parsed.file_types}' for '{raw_text}'"
        )

    if "expected_doc_type" in case:
        assert case["expected_doc_type"] in parsed.doc_types, (
            f"Expected doc type '{case['expected_doc_type']}' in '{parsed.doc_types}' for '{raw_text}'"
        )

    if case.get("has_date_filter"):
        assert parsed.min_modified is not None, (
            f"Expected min_modified date filter to be set for '{raw_text}'"
        )
