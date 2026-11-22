"""Tests for Emergency Vault PIN authentication, lockout, token protection, and pin/unpin/suggestions."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.routes import router
from app.db import (
    get_connection,
    init_db,
    upsert_file_record,
)
from app.main import app
from app.vault.service import reset_vault_state


@pytest.fixture(autouse=True)
def setup_test_vault(tmp_path: Path):
    """Provide an isolated database and reset in-memory vault security state for each test."""
    db_file = tmp_path / "test_vault.db"
    init_db(db_file)
    reset_vault_state()

    with patch("app.api.routes.get_connection", side_effect=lambda: get_connection(db_file)), \
         patch("app.db.get_connection", side_effect=lambda: get_connection(db_file)):
        yield db_file

    reset_vault_state()


def test_vault_pin_setup_valid_and_invalid():
    client = TestClient(app)

    # 1. Invalid PIN: too short (< 4 digits)
    res = client.post("/vault/setup", json={"pin": "123"})
    assert res.status_code == 400
    assert "PIN must be between 4 and 8" in res.json()["detail"]

    # 2. Invalid PIN: too long (> 8 digits)
    res = client.post("/vault/setup", json={"pin": "123456789"})
    assert res.status_code == 400

    # 3. Invalid PIN: non-digits
    res = client.post("/vault/setup", json={"pin": "abcd"})
    assert res.status_code == 400

    # 4. Valid PIN setup
    res = client.post("/vault/setup", json={"pin": "1234"})
    assert res.status_code == 200
    assert res.json()["ok"] is True

    # 5. Second setup must fail (already setup)
    res = client.post("/vault/setup", json={"pin": "5678"})
    assert res.status_code == 400
    assert "already setup" in res.json()["detail"].lower()


def test_vault_unlock_success_and_wrong_pin():
    client = TestClient(app)

    # Setup PIN
    client.post("/vault/setup", json={"pin": "9876"})

    # Wrong PIN
    res = client.post("/vault/unlock", json={"pin": "1111"})
    assert res.status_code == 401
    assert "remaining" in res.json()["detail"].lower()

    # Correct PIN
    res = client.post("/vault/unlock", json={"pin": "9876"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert len(data["token"]) == 64  # secrets.token_hex(32)
    assert data["expires_in"] == 600


def test_vault_lockout_after_5_failed_attempts():
    client = TestClient(app)
    client.post("/vault/setup", json={"pin": "4321"})

    # 4 failed attempts
    for i in range(1, 5):
        res = client.post("/vault/unlock", json={"pin": "0000"})
        assert res.status_code == 401
        assert f"{5 - i} attempt" in res.json()["detail"]

    # 5th failed attempt triggers lockout
    res = client.post("/vault/unlock", json={"pin": "0000"})
    assert res.status_code == 429
    assert "locked for 60 seconds" in res.json()["detail"].lower()

    # Even with correct PIN, must be rejected while locked
    res = client.post("/vault/unlock", json={"pin": "4321"})
    assert res.status_code == 429
    assert "locked due to too many failed attempts" in res.json()["detail"].lower()


def test_vault_endpoints_token_protection():
    client = TestClient(app)
    client.post("/vault/setup", json={"pin": "1234"})
    token = client.post("/vault/unlock", json={"pin": "1234"}).json()["token"]

    # No token provided -> 401
    assert client.get("/vault").status_code == 401
    assert client.post("/vault/pin", json={"path": "dummy.pdf"}).status_code == 401
    assert client.delete("/vault/1").status_code == 401
    assert client.get("/vault/suggestions").status_code == 401

    # Invalid token provided -> 401
    headers_bad = {"X-Vault-Token": "bad_token_123"}
    assert client.get("/vault", headers=headers_bad).status_code == 401

    # Valid token provided -> 200
    headers_good = {"X-Vault-Token": token}
    res = client.get("/vault", headers=headers_good)
    assert res.status_code == 200
    assert res.json() == []


def test_vault_pin_and_unpin_flow(tmp_path: Path):
    db_file = tmp_path / "test_vault.db"
    conn = get_connection(db_file)
    f_path = str(tmp_path / "passport.pdf")
    fid = upsert_file_record(
        conn=conn,
        path=f_path,
        filename="passport.pdf",
        ext=".pdf",
        size=1024,
        created_at=time.time(),
        modified_at=time.time(),
        content_hash="h1",
        indexed_at=time.time(),
        status="indexed",
        text="Passport ID Document Expiry 2029-05-12",
    )
    conn.execute("UPDATE files SET doc_type = 'id_document' WHERE id = ?", (fid,))
    conn.commit()
    conn.close()

    client = TestClient(app)
    client.post("/vault/setup", json={"pin": "1234"})
    token = client.post("/vault/unlock", json={"pin": "1234"}).json()["token"]
    headers = {"X-Vault-Token": token}

    # Pin file
    res = client.post("/vault/pin", json={"path": f_path, "label": "My Passport"}, headers=headers)
    assert res.status_code == 200
    vault_id = res.json()["id"]

    # Get vault items
    res = client.get("/vault", headers=headers)
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["id"] == vault_id
    assert items[0]["filename"] == "passport.pdf"
    assert items[0]["label"] == "My Passport"
    assert items[0]["doc_type"] == "id_document"

    # Unpin file
    res = client.delete(f"/vault/{vault_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["ok"] is True

    # Empty now
    res = client.get("/vault", headers=headers)
    assert res.json() == []

    # Non-existent unpin
    res = client.delete("/vault/9999", headers=headers)
    assert res.status_code == 404


def test_vault_suggestions(tmp_path: Path):
    db_file = tmp_path / "test_vault.db"
    conn = get_connection(db_file)

    # Eligible doc_types: id_document, insurance, medical, ticket, warranty
    # Ineligible: other, code_notes
    for name, dtype, score in [
        ("passport.pdf", "id_document", 0.95),
        ("health_ins.pdf", "insurance", 0.90),
        ("prescription.pdf", "medical", 0.85),
        ("flight.pdf", "ticket", 0.80),
        ("laptop_bill.pdf", "warranty", 0.75),
        ("notes.txt", "code_notes", 0.99),
        ("random.pdf", "other", 0.50),
    ]:
        p = str(tmp_path / name)
        fid = upsert_file_record(
            conn=conn,
            path=p,
            filename=name,
            ext=Path(name).suffix,
            size=500,
            created_at=time.time(),
            modified_at=time.time(),
            content_hash=name,
            indexed_at=time.time(),
            status="indexed",
            text="text",
        )
        conn.execute("UPDATE files SET doc_type = ?, doc_type_score = ? WHERE id = ?", (dtype, score, fid))
    conn.commit()
    conn.close()

    client = TestClient(app)
    client.post("/vault/setup", json={"pin": "1234"})
    token = client.post("/vault/unlock", json={"pin": "1234"}).json()["token"]
    headers = {"X-Vault-Token": token}

    res = client.get("/vault/suggestions", headers=headers)
    assert res.status_code == 200
    suggs = res.json()
    assert len(suggs) == 5
    filenames = [s["filename"] for s in suggs]
    assert "passport.pdf" in filenames
    assert "health_ins.pdf" in filenames
    assert "prescription.pdf" in filenames
    assert "flight.pdf" in filenames
    assert "laptop_bill.pdf" in filenames
    assert "notes.txt" not in filenames
    assert "random.pdf" not in filenames

    # If we pin passport, suggestions should no longer include it
    client.post("/vault/pin", json={"path": str(tmp_path / "passport.pdf")}, headers=headers)
    res2 = client.get("/vault/suggestions", headers=headers)
    filenames2 = [s["filename"] for s in res2.json()]
    assert "passport.pdf" not in filenames2
    assert len(filenames2) == 4
