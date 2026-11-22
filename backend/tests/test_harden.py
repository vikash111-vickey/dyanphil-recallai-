"""Tests for security hardening: local-only access, cookie protection,
origin/referer checks, data masking, delete-all, and privacy endpoints.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import (
    get_connection,
    init_db,
    insert_facts_batch,
    pin_file_to_vault,
    update_file_classification,
)
from app.ingestion.facts import ExtractedFact
from app.main import (
    API_COOKIE_NAME,
    ALLOWED_ORIGIN_HOSTS,
    app,
    get_api_token,
)
from app.security.masking import (
    mask_aadhaar,
    mask_all_sensitive,
    mask_cards,
    mask_pan,
    mask_passwords_and_otps,
)
from app.vault.service import setup_pin, unlock_vault


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Isolate database and data folder for testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "test_recall.db"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "db_path", db_file)
    init_db()
    yield db_file


def test_cookie_protection(temp_db: Path):
    """Verify API protection cookie enforcement."""
    client = TestClient(app)

    # 1. /health is exempt from cookie requirement
    client.cookies.clear()
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json() == {"status": "ok"}

    # 2. GET / sets the HttpOnly SameSite=Strict session cookie
    resp_root = client.get("/")
    assert resp_root.status_code == 200
    cookie = resp_root.cookies.get(API_COOKIE_NAME)
    assert cookie == get_api_token()

    # 3. API route without cookie returns 401
    client.cookies.clear()
    resp_unauth = client.get("/privacy")
    assert resp_unauth.status_code == 401
    assert "Unauthorized" in resp_unauth.json()["detail"]

    # 4. API route with invalid cookie returns 401
    client.cookies.set(API_COOKIE_NAME, "bogus_invalid_token")
    resp_bad = client.get("/privacy")
    assert resp_bad.status_code == 401

    # 5. API route with valid cookie returns 200
    client.cookies.set(API_COOKIE_NAME, get_api_token())
    resp_ok = client.get("/privacy")
    assert resp_ok.status_code == 200


def test_trusted_host_rules(temp_db: Path):
    """Verify TrustedHostMiddleware blocks non-local hosts."""
    client = TestClient(app)

    # Allowed local hosts
    resp_local = client.get("/health", headers={"Host": "127.0.0.1"})
    assert resp_local.status_code == 200

    resp_localhost = client.get("/health", headers={"Host": "localhost"})
    assert resp_localhost.status_code == 200

    # Disallowed host returns 400
    resp_evil = client.get("/health", headers={"Host": "evil.com"})
    assert resp_evil.status_code == 400


def test_origin_and_referer_rules(temp_db: Path):
    """Verify Origin and Referer headers validation."""
    client = TestClient(app)
    client.cookies.set(API_COOKIE_NAME, get_api_token())

    # Allowed Origins
    for origin in ALLOWED_ORIGIN_HOSTS:
        resp = client.get("/privacy", headers={"Origin": origin})
        assert resp.status_code == 200

    # Disallowed Origin returns 403
    resp_bad_origin = client.get("/privacy", headers={"Origin": "http://attacker.com"})
    assert resp_bad_origin.status_code == 403
    assert "Forbidden" in resp_bad_origin.json()["detail"]

    # Disallowed Referer returns 403
    resp_bad_ref = client.get("/privacy", headers={"Referer": "http://evil-site.org/phish"})
    assert resp_bad_ref.status_code == 403
    assert "Forbidden" in resp_bad_ref.json()["detail"]

    # Allowed Referer returns 200
    resp_good_ref = client.get("/privacy", headers={"Referer": "http://localhost:5173/dashboard"})
    assert resp_good_ref.status_code == 200


def test_masking_rules():
    """Verify sensitive data masking rules."""
    # Aadhaar (12 digits)
    assert mask_aadhaar("My Aadhaar is 1234 5678 9012 for KYC") == "My Aadhaar is XXXX-XXXX-9012 for KYC"
    assert mask_aadhaar("Aadhaar: 9988-7766-5544") == "Aadhaar: XXXX-XXXX-5544"

    # PAN (5 letters, 4 digits, 1 letter)
    assert mask_pan("My PAN is ABCDE1234F please verify") == "My PAN is XXXXXX234F please verify"

    # Card numbers (13-19 digits)
    assert mask_cards("Card: 4111 2222 3333 4444 expired") == "Card: ****-****-****-4444 expired"
    assert mask_cards("Number 4111222233334444") == "Number ****-****-****-4444"

    # Passwords and OTPs
    assert mask_passwords_and_otps("password: secretPass123") == "password: [REDACTED]"
    assert mask_passwords_and_otps("pwd = mysecret") == "pwd = [REDACTED]"
    assert mask_passwords_and_otps("passcode: 9876") == "passcode: [REDACTED]"
    assert mask_passwords_and_otps("Your OTP is 456789. Do not share.") == "Your OTP is [REDACTED]. Do not share."

    # Combined masking
    combined = (
        "User with PAN ABCDE1234F and Aadhaar 1234-5678-9012 paid with card 4111 2222 3333 4444. "
        "Temporary password: SuperSecret! OTP is 123456."
    )
    masked = mask_all_sensitive(combined)
    assert "ABCDE1234F" not in masked
    assert "XXXXXX234F" in masked
    assert "1234-5678-9012" not in masked
    assert "XXXX-XXXX-9012" in masked
    assert "4111 2222 3333 4444" not in masked
    assert "****-****-****-4444" in masked
    assert "SuperSecret!" not in masked
    assert "123456" not in masked
    assert "[REDACTED]" in masked


def test_api_masking_in_ask_and_expiring(temp_db: Path):
    """Verify /ask and /expiring mask sensitive data in returned snippets and facts."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO files (path, filename, ext, size, created_at, modified_at, indexed_at, status, doc_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("D:\\docs\\sensitive_kyc.pdf", "sensitive_kyc.pdf", ".pdf", 1024, 1000, 2000, 2000, "indexed", "id_document"),
        )
        fid = cur.lastrowid
        conn.execute("INSERT INTO contents (file_id, text) VALUES (?, ?)", (fid, "Confidential KYC details"))

        facts = [
            (
                fid,
                "id_number",
                "Aadhaar Number",
                "1234 5678 9012",
                None,
                "Aadhaar Number: 1234 5678 9012 for verification",
            ),
            (
                fid,
                "date",
                "Expires on",
                "2026-12-31",
                "2026-12-31",
                "Card: 4111 2222 3333 4444 expires on 2026-12-31 with password: secret",
            ),
        ]
        insert_facts_batch(conn, facts)
        conn.commit()
    finally:
        conn.close()

    client = TestClient(app)
    client.cookies.set(API_COOKIE_NAME, get_api_token())

    # Check /expiring
    resp_exp = client.get("/expiring?days=90")
    assert resp_exp.status_code == 200
    data_exp = resp_exp.json()
    assert len(data_exp) > 0
    exp_snippet = data_exp[0]["snippet"]
    assert "4111 2222 3333 4444" not in exp_snippet
    assert "****-****-****-4444" in exp_snippet
    assert "secret" not in exp_snippet
    assert "[REDACTED]" in exp_snippet

    # Check /ask
    resp_ask = client.post("/ask", json={"message": "sensitive_kyc"})
    assert resp_ask.status_code == 200
    data_ask = resp_ask.json()
    assert len(data_ask["results"]) > 0
    res_item = data_ask["results"][0]
    for fact in res_item["facts"]:
        assert "1234 5678 9012" not in fact["value"]


def test_delete_all_data(temp_db: Path):
    """Verify POST /data/delete-all functionality and safeguards."""
    conn = get_connection()
    try:
        # Seed test data
        cur = conn.execute(
            """
            INSERT INTO files (path, filename, ext, size, created_at, modified_at, indexed_at, status, doc_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("D:\\docs\\test1.txt", "test1.txt", ".txt", 500, 1000, 2000, 2000, "indexed", "other"),
        )
        fid = cur.lastrowid
        conn.execute("INSERT INTO contents (file_id, text) VALUES (?, ?)", (fid, "Sample text"))
        conn.commit()
    finally:
        conn.close()

    # Create dummy cache files in data_dir
    cache_file = settings.data_dir / "test.cache"
    cache_file.write_text("cache content", encoding="utf-8")
    last_search = settings.data_dir / "last_search.json"
    last_search.write_text("{}", encoding="utf-8")

    client = TestClient(app)
    client.cookies.set(API_COOKIE_NAME, get_api_token())

    # 1. Reject if confirm is not 'DELETE'
    resp_bad_confirm = client.post("/data/delete-all", json={"confirm": "NO"})
    assert resp_bad_confirm.status_code == 400

    # 2. If a PIN is set, require vault token
    conn = get_connection()
    try:
        setup_pin(conn, "1234")
    finally:
        conn.close()

    resp_no_token = client.post("/data/delete-all", json={"confirm": "DELETE"})
    assert resp_no_token.status_code == 401
    assert "Vault token required" in resp_no_token.json()["detail"] or "vault token" in resp_no_token.json()["detail"].lower()

    # Unlock vault to get token
    conn = get_connection()
    try:
        vault_token = unlock_vault(conn, "1234")
    finally:
        conn.close()

    # 3. Successful delete with vault token
    resp_del = client.post(
        "/data/delete-all",
        json={"confirm": "DELETE"},
        headers={"X-Vault-Token": vault_token},
    )
    assert resp_del.status_code == 200
    del_data = resp_del.json()
    assert del_data["ok"] is True
    assert del_data["deleted"]["files"] >= 1

    # Verify database is now empty
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        assert count == 0
        settings_count = conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0]
        assert settings_count == 0
    finally:
        conn.close()

    # Verify cache files were deleted
    assert not cache_file.exists()
    assert not last_search.exists()


def test_privacy_endpoint(temp_db: Path):
    """Verify GET /privacy returns correct metadata."""
    client = TestClient(app)
    client.cookies.set(API_COOKIE_NAME, get_api_token())

    resp = client.get("/privacy")
    assert resp.status_code == 200
    data = resp.json()

    assert "data_folder" in data
    assert "database_size" in data
    assert "files_indexed" in data
    assert "folders_count" in data
    assert "vault_pin_set" in data
    assert "embedding_model" in data
    assert isinstance(data["files_indexed"], int)
    assert isinstance(data["vault_pin_set"], bool)
