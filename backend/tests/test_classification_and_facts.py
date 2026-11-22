"""Tests for document classification, fact extraction, privacy masking, fact answers, and expiring endpoints."""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db import (
    delete_facts_by_file_id,
    get_connection,
    get_expiring_facts,
    get_facts_by_file_id,
    init_db,
    insert_facts_batch,
    update_file_classification,
    upsert_file_record,
)
from app.ingestion.classifier import classify_file
from app.ingestion.facts import (
    extract_facts,
    mask_sensitive_data,
    parse_and_normalize_date,
)
from app.main import app
from app.search.facts_answer import detect_fact_intent, find_fact_answer


# --- 1. Classifier Tests ---


def test_classifier_all_categories():
    """Verify keyword scoring correctly classifies various document types."""
    # id_document
    cat, score = classify_file(
        "C:/users/docs/passport.pdf",
        "passport.pdf",
        "Republic of India. Date of birth: 1995-05-10. Nationality Indian.",
    )
    assert cat == "id_document"
    assert score > 0.5

    # insurance
    cat, score = classify_file(
        "C:/insurance/car.pdf",
        "car.pdf",
        "Vehicle Insurance Policy. Policy Number: POL-9988. Sum Insured: Rs. 500000. Comprehensive coverage.",
    )
    assert cat == "insurance"
    assert score > 0.5

    # medical
    cat, score = classify_file(
        "C:/health/prescription.pdf",
        "prescription.pdf",
        "Dr. Sharma Clinic. Patient name: John. Rx: Tablets Paracetamol 500mg twice daily.",
    )
    assert cat == "medical"
    assert score > 0.5

    # financial
    cat, score = classify_file(
        "C:/accounting/tax_invoice.pdf",
        "tax_invoice.pdf",
        "Tax Invoice. GSTIN: 27AAAAA0000A1Z5. Subtotal: 1000. Grand Total: Rs. 1180.",
    )
    assert cat == "financial"
    assert score > 0.5

    # ticket
    cat, score = classify_file(
        "C:/travel/flight_ticket.pdf",
        "flight_ticket.pdf",
        "Electronic Reservation Slip. PNR: 2849182. Flight AI-101. Terminal 3. Gate 4.",
    )
    assert cat == "ticket"
    assert score > 0.5

    # warranty
    cat, score = classify_file(
        "C:/appliances/sony_tv.pdf",
        "sony_tv.pdf",
        "Limited Warranty Card. Warranty period: valid for 2 years from purchase. Service center.",
    )
    assert cat == "warranty"
    assert score > 0.5

    # contract
    cat, score = classify_file(
        "C:/legal/rent_agreement.pdf",
        "rent_agreement.pdf",
        "This Rental Agreement is made between the Tenant and the Landlord. Terms and conditions.",
    )
    assert cat == "contract"
    assert score > 0.5

    # certificate
    cat, score = classify_file(
        "C:/certs/nasa.pdf",
        "nasa.pdf",
        "This is to certify that John Doe has successfully completed the space workshop. Certificate of completion.",
    )
    assert cat == "certificate"
    assert score > 0.5

    # education
    cat, score = classify_file(
        "C:/college/semester_marksheet.pdf",
        "semester_marksheet.pdf",
        "Bachelor of Technology. Semester 4 Marksheet. Roll No: 12345. CGPA: 8.5.",
    )
    assert cat == "education"
    assert score > 0.5

    # resume
    cat, score = classify_file(
        "C:/jobs/john_resume.pdf",
        "john_resume.pdf",
        "Curriculum Vitae. Professional Summary. Work experience: Senior Software Engineer. Technical skills.",
    )
    assert cat == "resume"
    assert score > 0.5

    # code_notes
    cat, score = classify_file(
        "C:/projects/setup.md",
        "setup.md",
        "# Project Setup\nRun `npm install` and `git clone`. Api reference and documentation.",
    )
    assert cat == "code_notes"
    assert score > 0.3

    # other (unrelated text)
    cat, score = classify_file(
        "C:/random/fruit_basket.txt",
        "fruit_basket.txt",
        "Apples, oranges, bananas, and grapes in a basket.",
    )
    assert cat == "other"
    assert score == 0.0


# --- 2. Date Parsing and Normalization Tests ---


def test_date_parsing_formats():
    """Verify common date formats are converted into ISO YYYY-MM-DD."""
    assert parse_and_normalize_date("14 Aug 2026") == "2026-08-14"
    assert parse_and_normalize_date("14 August 2026") == "2026-08-14"
    assert parse_and_normalize_date("14th Aug 2026") == "2026-08-14"
    assert parse_and_normalize_date("14-Aug-2026") == "2026-08-14"
    assert parse_and_normalize_date("August 14, 2026") == "2026-08-14"
    assert parse_and_normalize_date("Aug 14 2026") == "2026-08-14"
    assert parse_and_normalize_date("14/08/2026") == "2026-08-14"
    assert parse_and_normalize_date("2026-08-14") == "2026-08-14"
    assert parse_and_normalize_date("2026/08/14") == "2026-08-14"
    assert parse_and_normalize_date("invalid date string") is None


# --- 3. Privacy Masking Tests ---


def test_privacy_masking_rules():
    """Verify Aadhaar, PAN, and card numbers are masked and passwords/OTPs omitted."""
    # Aadhaar masking
    aadhaar_masked = mask_sensitive_data("Aadhaar: 1234 5678 9012")
    assert "XXXX-XXXX-9012" in aadhaar_masked
    assert "1234 5678" not in aadhaar_masked

    # PAN masking
    pan_masked = mask_sensitive_data("PAN: ABCDE1234F")
    assert "XXXXXX234F" in pan_masked
    assert "ABCDE" not in pan_masked

    # Card masking
    card_masked = mask_sensitive_data("Card: 4111 2222 3333 4444")
    assert "****-****-****-4444" in card_masked
    assert "4111" not in card_masked

    # Fact extraction with passwords/OTPs
    doc = """
    Account details:
    Aadhaar: 9876 5432 1098
    PAN: FGHIJ5678K
    Credit Card: 5555 4444 3333 2222
    Password: SecretPassword123
    OTP: 456789
    Valid until: 14 Aug 2026
    Total Amount: Rs. 15000
    Email: contact@example.com
    Phone: 9876543210
    """
    facts = extract_facts(doc)
    labels = [f.label.lower() for f in facts]
    values = [f.value for f in facts]

    # Passwords and OTPs never stored
    assert not any("password" in l for l in labels)
    assert not any("otp" in l for l in labels)
    assert not any("SecretPassword123" in v for v in values)
    assert not any("456789" in v for v in values)

    # Privacy masked values in facts
    assert any("XXXX-XXXX-1098" in v for v in values)
    assert any("XXXXXX678K" in v for v in values)
    assert any("****-****-****-2222" in v for v in values)

    # Normalized date
    expiry_fact = next(f for f in facts if f.kind == "expiry")
    assert expiry_fact.value_date == "2026-08-14"

    # Amount
    amount_fact = next(f for f in facts if f.kind == "amount")
    assert "15000" in amount_fact.value


# --- 4. Fact Lookup in /ask Tests ---


def test_fact_intent_detection():
    """Verify fact questions are correctly identified with their targets."""
    assert detect_fact_intent("when does car insurance expire") == ("expiry", "car insurance")
    assert detect_fact_intent("what is my passport number") == ("id_number", "passport")
    assert detect_fact_intent("how much is electricity bill") == ("amount", "electricity bill")
    assert detect_fact_intent("show me resume") is None


def test_fact_answer_in_ask_endpoint(tmp_path: Path):
    """Test /ask endpoint fact question lookup and formatted answers."""
    db_file = tmp_path / "test_facts.db"
    conn = get_connection(db_file)
    init_db(db_file)

    try:
        # Insert a file with facts
        fid = upsert_file_record(
            conn=conn,
            path=str(tmp_path / "car_insurance.pdf"),
            filename="car_insurance.pdf",
            ext=".pdf",
            size=1024,
            created_at=100.0,
            modified_at=100.0,
            content_hash="hash1",
            indexed_at=100.0,
            status="indexed",
            text="Car insurance policy. Valid till 14 Aug 2026. Premium: Rs. 4500. Policy no: POL-998811.",
        )
        update_file_classification(conn, fid, "insurance", 0.9)
        insert_facts_batch(
            conn,
            [
                (fid, "expiry", "Valid Till", "14 Aug 2026", "2026-08-14", "Valid till 14 Aug 2026"),
                (fid, "amount", "Premium", "Rs. 4500", None, "Premium: Rs. 4500"),
                (fid, "id_number", "Policy No", "POL-998811", None, "Policy no: POL-998811"),
            ],
        )
        conn.commit()

        def mock_search(*args, **kwargs):
            q = kwargs.get("query") or (args[1] if len(args) > 1 else "")
            if "car" in q or "insurance" in q:
                return [
                    {
                        "path": str(tmp_path / "car_insurance.pdf"),
                        "filename": "car_insurance.pdf",
                        "modified_at": 100.0,
                        "snippet": "Car insurance policy",
                        "score": 1.0,
                        "match_type": "keyword",
                    }
                ]
            return []

        # Patch get_connection to use our test db
        with patch("app.api.routes.get_connection", side_effect=lambda: get_connection(db_file)), \
             patch("app.search.facts_answer.hybrid_search", side_effect=mock_search), \
             patch("app.api.routes.hybrid_search", side_effect=mock_search):
            client = TestClient(app)

            # 1. Ask about expiry
            res1 = client.post("/ask", json={"message": "when does car insurance expire"})
            assert res1.status_code == 200
            data1 = res1.json()
            assert "14 Aug 2026" in data1["message"]
            assert len(data1["results"]) >= 1
            assert data1["results"][0]["filename"] == "car_insurance.pdf"
            assert data1["results"][0]["doc_type"] == "insurance"
            assert len(data1["results"][0]["facts"]) > 0

            # 2. Ask about policy number
            res2 = client.post("/ask", json={"message": "what is my car insurance number"})
            assert res2.status_code == 200
            data2 = res2.json()
            assert "POL-998811" in data2["message"]

            # 3. Fallback when no fact matches
            res3 = client.post("/ask", json={"message": "when does my flight ticket expire"})
            assert res3.status_code == 200
            data3 = res3.json()
            assert "couldn't find" in data3["message"] or "Here is" in data3["message"] or "Found" in data3["message"]
    finally:
        conn.close()


# --- 5. Expiring Documents Endpoint & Function Tests ---


def test_get_expiring_facts(tmp_path: Path):
    """Test fetching expiring documents within N days and expired ones."""
    db_file = tmp_path / "test_expiring.db"
    conn = get_connection(db_file)
    init_db(db_file)

    ref_date = datetime.date(2026, 8, 1)

    try:
        f1 = upsert_file_record(
            conn, str(tmp_path / "passport.pdf"), "passport.pdf", ".pdf", 100, 1.0, 1.0, "h1", 1.0, "indexed",
        )
        f2 = upsert_file_record(
            conn, str(tmp_path / "car_insurance.pdf"), "car_insurance.pdf", ".pdf", 100, 1.0, 1.0, "h2", 1.0, "indexed",
        )
        f3 = upsert_file_record(
            conn, str(tmp_path / "warranty.pdf"), "warranty.pdf", ".pdf", 100, 1.0, 1.0, "h3", 1.0, "indexed",
        )
        update_file_classification(conn, f1, "id_document", 0.9)
        update_file_classification(conn, f2, "insurance", 0.9)
        update_file_classification(conn, f3, "warranty", 0.9)

        insert_facts_batch(
            conn,
            [
                # Already expired: 2026-07-15 (17 days ago)
                (f1, "expiry", "Expiry Date", "15 Jul 2026", "2026-07-15", "Expiry date 15 Jul 2026"),
                # Due in 13 days: 2026-08-14
                (f2, "expiry", "Valid Till", "14 Aug 2026", "2026-08-14", "Valid till 14 Aug 2026"),
                # Due in 180 days: 2027-01-28 (beyond 60 days)
                (f3, "expiry", "Warranty Expiry", "28 Jan 2027", "2027-01-28", "Warranty expiry 28 Jan 2027"),
            ],
        )
        conn.commit()

        # Query next 60 days
        items_60 = get_expiring_facts(conn, days=60, reference_date=ref_date)
        assert len(items_60) == 2  # f1 (expired) and f2 (in 13 days)

        # Sorted by date ascending
        assert items_60[0]["filename"] == "passport.pdf"
        assert items_60[0]["is_expired"] is True
        assert items_60[0]["days_remaining"] == -17

        assert items_60[1]["filename"] == "car_insurance.pdf"
        assert items_60[1]["is_expired"] is False
        assert items_60[1]["days_remaining"] == 13

        # Query with 200 days includes all 3
        items_200 = get_expiring_facts(conn, days=200, reference_date=ref_date)
        assert len(items_200) == 3

        # Test endpoint
        with patch("app.api.routes.get_connection", side_effect=lambda: get_connection(db_file)):
            client = TestClient(app)
            res = client.get("/expiring?days=60")
            assert res.status_code == 200
            data = res.json()
            assert len(data) >= 2
    finally:
        conn.close()


# --- 6. CLI Commands Tests ---


def test_cli_classify_and_facts_and_expiring(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Test CLI commands: classify, facts, and expiring."""
    from app.cli import handle_classify, handle_expiring, handle_facts

    db_file = tmp_path / "test_cli.db"
    conn = get_connection(db_file)
    init_db(db_file)

    try:
        # File 1: unclassified invoice
        f1 = upsert_file_record(
            conn,
            str(tmp_path / "invoice_101.pdf"),
            "invoice_101.pdf",
            ".pdf",
            200,
            1.0,
            1.0,
            "h101",
            1.0,
            "indexed",
            text="Tax Invoice. Total Amount: Rs. 2500. Due date: 2026-09-01.",
        )
        # File 2: unclassified policy
        f2 = upsert_file_record(
            conn,
            str(tmp_path / "lic_policy.pdf"),
            "lic_policy.pdf",
            ".pdf",
            300,
            1.0,
            1.0,
            "h102",
            1.0,
            "indexed",
            text="Life Insurance Policy. Policy No: POL-7788. Valid till 14 Aug 2026.",
        )
        conn.commit()

        # Run handle_classify
        class ArgsClassify:
            limit = None

        with patch("app.cli.get_connection", side_effect=lambda: get_connection(db_file)):
            ret = handle_classify(ArgsClassify())
            assert ret == 0

        # Verify classifications in DB
        r1 = conn.execute("SELECT doc_type, doc_type_score FROM files WHERE id = ?", (f1,)).fetchone()
        assert r1["doc_type"] == "financial"
        assert r1["doc_type_score"] > 0.0

        r2 = conn.execute("SELECT doc_type, doc_type_score FROM files WHERE id = ?", (f2,)).fetchone()
        assert r2["doc_type"] == "insurance"

        # Verify facts extracted
        facts2 = get_facts_by_file_id(conn, f2)
        assert len(facts2) >= 2
        labels2 = [f["label"] for f in facts2]
        assert "Valid Till" in labels2 or "Policy No" in labels2

        # Run handle_facts
        class ArgsFacts:
            query = "lic_policy"

        with patch("app.cli.get_connection", side_effect=lambda: get_connection(db_file)):
            ret_f = handle_facts(ArgsFacts())
            assert ret_f == 0
            captured = capsys.readouterr()
            assert "Type:  insurance" in captured.out
            assert "lic_policy.pdf" in captured.out

        # Run handle_expiring
        class ArgsExpiring:
            days = 120

        with patch("app.cli.get_connection", side_effect=lambda: get_connection(db_file)):
            ret_e = handle_expiring(ArgsExpiring())
            assert ret_e == 0
            captured_e = capsys.readouterr()
            assert "Expiring / Due Documents" in captured_e.out
    finally:
        conn.close()
