"""Document classification using rules and keyword scoring (English & Hinglish).

Classifies files based on:
1. Filename
2. Folder names (path components)
3. First 3000 characters of text

Categories:
- id_document
- insurance
- medical
- financial
- ticket
- warranty
- contract
- certificate
- education
- resume
- code_notes
- other
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Category keyword definitions
# Each category contains:
# - path_terms: matched against filename and folder names (high weight)
# - content_terms: matched against first 3000 characters of text

CATEGORY_RULES: dict[str, dict[str, list[str]]] = {
    "id_document": {
        "path_terms": [
            "passport",
            "aadhaar",
            "aadhar",
            "uidai",
            "pancard",
            "pan_card",
            "pan card",
            "voter",
            "epic",
            "driving_licence",
            "driving_license",
            "driving licence",
            "driving license",
            "identity",
            "id_card",
            "id card",
            "idcard",
            "pehchan",
            "citizen",
            "govt id",
        ],
        "content_terms": [
            "passport",
            "republic of india",
            "government of india",
            "bharat sarkar",
            "unique identification authority",
            "aadhaar",
            "aadhar",
            "uidai",
            "income tax department",
            "permanent account number",
            "election commission",
            "elector photo identity",
            "voter id",
            "driving licence",
            "driving license",
            "motor vehicles department",
            "identity card",
            "father's name",
            "fathers name",
            "date of birth",
            "dob",
            "pehchan patra",
            "nationality indian",
            "indian citizen",
        ],
    },
    "insurance": {
        "path_terms": [
            "insurance",
            "policy",
            "premium",
            "bima",
            "lic",
            "mediclaim",
            "tpa",
            "health insurance",
            "health_insurance",
            "car insurance",
            "car_insurance",
            "motor insurance",
            "motor_insurance",
            "life insurance",
            "life_insurance",
            "term insurance",
            "cover note",
            "vehicle insurance",
        ],
        "content_terms": [
            "insurance",
            "policy number",
            "policy schedule",
            "policy period",
            "sum insured",
            "insured name",
            "premium amount",
            "total premium",
            "bima",
            "claim",
            "coverage",
            "third party",
            "comprehensive",
            "nominee",
            "deductible",
            "tpa",
            "insurer",
            "cashless",
            "endorsement",
            "no claim bonus",
            "ncb",
        ],
    },
    "medical": {
        "path_terms": [
            "medical",
            "prescription",
            "lab report",
            "lab_report",
            "blood test",
            "blood_test",
            "doctor",
            "hospital",
            "clinic",
            "rx",
            "discharge",
            "pathology",
            "diagnostics",
            "davai",
            "ilaj",
            "health checkup",
            "mri",
            "xray",
            "ct scan",
            "patient",
        ],
        "content_terms": [
            "patient name",
            "referred by",
            "diagnosis",
            "investigation",
            "dr.",
            "doctor",
            "hospital",
            "clinic",
            "blood test",
            "hemoglobin",
            "platelets",
            "serum",
            "test report",
            "prescription",
            "rx",
            "dosage",
            "tablets",
            "capsules",
            "syrup",
            "consultation",
            "symptoms",
            "treatment",
            "discharge summary",
            "pathology",
            "davai",
            "ilaj",
        ],
    },
    "financial": {
        "path_terms": [
            "invoice",
            "bill",
            "receipt",
            "salary",
            "payslip",
            "tax",
            "itr",
            "statement",
            "bank statement",
            "bank_statement",
            "credit card",
            "gst",
            "form16",
            "payment",
            "expense",
            "expenses",
            "kharcha",
            "hisab",
            "balance sheet",
            "ledger",
        ],
        "content_terms": [
            "invoice",
            "tax invoice",
            "gstin",
            "bill to",
            "amount payable",
            "subtotal",
            "grand total",
            "payment receipt",
            "receipt no",
            "salary slip",
            "payslip",
            "earnings",
            "deductions",
            "provident fund",
            "pf",
            "net pay",
            "account number",
            "ifsc",
            "debit",
            "credit",
            "transaction",
            "bank statement",
            "assessment year",
            "income tax return",
            "itr-v",
            "form 16",
            "total amount",
            "kharcha",
            "hisab",
        ],
    },
    "ticket": {
        "path_terms": [
            "ticket",
            "boarding pass",
            "boarding_pass",
            "boarding",
            "pnr",
            "flight",
            "train",
            "irctc",
            "bus ticket",
            "air ticket",
            "eticket",
            "e-ticket",
            "yatra",
            "booking",
            "reservation",
        ],
        "content_terms": [
            "pnr",
            "flight",
            "boarding pass",
            "terminal",
            "gate",
            "seat no",
            "seat number",
            "departure",
            "arrival",
            "electronic reservation slip",
            "irctc",
            "train no",
            "coach",
            "passenger details",
            "fare details",
            "e-ticket",
            "air ticket",
            "yatra",
            "booking status",
        ],
    },
    "warranty": {
        "path_terms": [
            "warranty",
            "guarantee",
            "warranty card",
            "warranty_card",
            "service card",
            "user manual",
            "manual",
        ],
        "content_terms": [
            "warranty",
            "guarantee",
            "warranty card",
            "warranty period",
            "valid for 1 year",
            "valid for 2 years",
            "limited warranty",
            "terms of warranty",
            "service center",
            "repair or replacement",
            "customer care",
            "serial number",
            "product model",
        ],
    },
    "contract": {
        "path_terms": [
            "contract",
            "agreement",
            "nda",
            "lease",
            "rent agreement",
            "rent_agreement",
            "deed",
            "mou",
            "terms of service",
            "legal notice",
            "affidavit",
            "undertaking",
            "memorandum",
        ],
        "content_terms": [
            "agreement",
            "contract",
            "whereas",
            "herein",
            "hereto",
            "indemnify",
            "jurisdiction",
            "parties",
            "tenant",
            "landlord",
            "lessor",
            "lessee",
            "non-disclosure",
            "confidential information",
            "in witness whereof",
            "terms and conditions",
            "stamp paper",
            "notary",
            "severability",
        ],
    },
    "certificate": {
        "path_terms": [
            "certificate",
            "certif",
            "certs",
            "cert",
            "certification",
            "diploma",
            "degree",
            "praman patra",
            "praman_patra",
            "sanad",
            "appreciation",
            "participation",
            "completion",
        ],
        "content_terms": [
            "certificate of completion",
            "certificate of participation",
            "this certificate is presented to",
            "this is to certify that",
            "has successfully completed",
            "in recognition of",
            "awarded to",
            "honors",
            "director",
            "dean",
            "coordinator",
            "grade",
            "praman patra",
            "sanad",
        ],
    },
    "education": {
        "path_terms": [
            "marksheet",
            "report card",
            "report_card",
            "syllabus",
            "assignment",
            "homework",
            "transcript",
            "timetable",
            "tuition",
            "school",
            "college",
            "university",
            "semester",
            "grade card",
            "exam",
        ],
        "content_terms": [
            "marksheet",
            "semester",
            "roll no",
            "roll number",
            "registration no",
            "course code",
            "subject",
            "credits",
            "grade point",
            "cgpa",
            "sgpa",
            "internal assessment",
            "academic year",
            "examination",
            "syllabus",
            "assignment",
            "homework",
            "tuition",
            "lecture",
            "curriculum",
        ],
    },
    "resume": {
        "path_terms": [
            "resume",
            "cv",
            "curriculum vitae",
            "curriculum_vitae",
            "biodata",
            "bio data",
            "bio_data",
            "profile",
        ],
        "content_terms": [
            "curriculum vitae",
            "resume",
            "work experience",
            "employment history",
            "professional summary",
            "education",
            "skills",
            "technical skills",
            "projects",
            "languages known",
            "linkedin.com",
            "github.com",
            "contact details",
            "biodata",
            "career objective",
        ],
    },
    "code_notes": {
        "path_terms": [
            "readme",
            "changelog",
            "api",
            "docs",
            "documentation",
            "notes",
            "snippet",
            "script",
            "dev",
            "guide",
            "setup",
            "cheatsheet",
        ],
        "content_terms": [
            "import ",
            "export ",
            "function ",
            "class ",
            "def ",
            "const ",
            "npm install",
            "pip install",
            "git clone",
            "docker",
            "api reference",
            "endpoint",
            "curl ",
            "bash",
            "powershell",
            "markdown",
            "syntax",
            "todo:",
        ],
    },
}

CODE_EXTENSIONS = {".py", ".js", ".ts", ".sql", ".sh", ".json", ".yml", ".yaml", ".md", ".html", ".css"}


def _clean_string(s: str) -> str:
    """Normalize a string to lowercase with spaces separating tokens."""
    return re.sub(r"[\W_]+", " ", s.lower()).strip()


def classify_file(
    path: Path | str,
    filename: str,
    text: str | None = None,
) -> tuple[str, float]:
    """
    Classify a file into one of:
    id_document, insurance, medical, financial, ticket, warranty, contract,
    certificate, education, resume, code_notes, other.

    Uses:
    - filename (high weight: 3.0 per match)
    - folder names in path (medium weight: 1.5 per match)
    - first 3000 chars of text (weight: 1.0 per match)

    Returns (best_type, score) where score is in [0.0, 1.0].
    """
    p = Path(path)
    clean_fn = _clean_string(filename)
    folder_parts = [_clean_string(part) for part in p.parts[:-1]]
    clean_folders = " ".join(folder_parts)
    clean_text = _clean_string(text[:3000]) if text else ""
    ext = p.suffix.lower()

    scores: dict[str, float] = {k: 0.0 for k in CATEGORY_RULES}

    # Code notes extension check
    if ext in CODE_EXTENSIONS:
        scores["code_notes"] += 1.5

    for category, rules in CATEGORY_RULES.items():
        # 1. Check filename
        for term in rules["path_terms"]:
            term_clean = _clean_string(term)
            if term_clean in clean_fn:
                scores[category] += 3.0
                break

        # 2. Check folder names
        for term in rules["path_terms"]:
            term_clean = _clean_string(term)
            if term_clean in clean_folders:
                scores[category] += 1.5
                break

        # 3. Check first 3000 characters of text
        if clean_text:
            content_matches = 0
            for term in rules["content_terms"]:
                term_clean = _clean_string(term)
                if term_clean in clean_text:
                    content_matches += 1
                    scores[category] += 1.0
                    if content_matches >= 6:
                        break

    best_cat = "other"
    best_raw = 0.0

    for cat, raw in scores.items():
        if raw > best_raw:
            best_raw = raw
            best_cat = cat

    if best_raw < 0.5:
        return ("other", 0.0)

    # Normalize score between 0.0 and 1.0
    normalized_score = round(min(1.0, best_raw / 5.0), 2)
    return (best_cat, normalized_score)
