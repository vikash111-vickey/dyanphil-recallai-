"""Vault security service: PIN setup, scrypt hashing, lockout, and token sessions."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from typing import Dict

from fastapi import HTTPException

from app.db import get_setting, set_setting

SETTINGS_PIN_KEY = "vault_pin"
TOKEN_EXPIRY_SECONDS = 600.0  # 10 minutes
LOCKOUT_THRESHOLD = 5
LOCKOUT_SECONDS = 60.0

# In-memory session and lockout tracking
_valid_tokens: Dict[str, float] = {}  # token -> expiry_timestamp
_failed_attempts: int = 0
_locked_until: float = 0.0


def reset_vault_state() -> None:
    """Reset in-memory tokens and lockout counters (used in testing)."""
    global _failed_attempts, _locked_until, _valid_tokens
    _valid_tokens.clear()
    _failed_attempts = 0
    _locked_until = 0.0


def validate_pin_format(pin: str) -> None:
    """Validate that PIN is 4 to 8 digits."""
    if not (pin and pin.isdigit() and 4 <= len(pin) <= 8):
        raise HTTPException(
            status_code=400,
            detail="PIN must be between 4 and 8 numeric digits.",
        )


def is_pin_setup(conn: sqlite3.Connection) -> bool:
    """Check if vault PIN has already been configured."""
    return get_setting(conn, SETTINGS_PIN_KEY) is not None


def setup_pin(conn: sqlite3.Connection, pin: str) -> None:
    """
    Set up vault PIN with salted scrypt hash.
    Fails if a PIN is already configured.
    """
    validate_pin_format(pin)
    if is_pin_setup(conn):
        raise HTTPException(
            status_code=400,
            detail="Vault PIN is already setup.",
        )

    salt = os.urandom(16)
    # hashlib.scrypt: standard parameters (n=16384, r=8, p=1)
    derived = hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
    stored_val = f"{salt.hex()}:{derived.hex()}"
    set_setting(conn, SETTINGS_PIN_KEY, stored_val)


def unlock_vault(conn: sqlite3.Connection, pin: str) -> str:
    """
    Verify PIN and return a 10-minute random token.
    Enforces a 60-second lock after 5 wrong attempts.
    """
    global _failed_attempts, _locked_until

    now = time.time()
    if now < _locked_until:
        remaining = int(_locked_until - now) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Vault is locked due to too many failed attempts. Try again in {remaining} seconds.",
        )

    stored_val = get_setting(conn, SETTINGS_PIN_KEY)
    if not stored_val:
        raise HTTPException(
            status_code=400,
            detail="Vault PIN has not been set up yet.",
        )

    try:
        salt_hex, hash_hex = stored_val.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupt vault PIN setting.")

    derived = hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=16384, r=8, p=1)

    if hmac.compare_digest(derived, expected_hash):
        # Success: reset lockout counters and issue random token
        _failed_attempts = 0
        _locked_until = 0.0
        token = secrets.token_hex(32)
        _valid_tokens[token] = now + TOKEN_EXPIRY_SECONDS
        return token
    else:
        _failed_attempts += 1
        if _failed_attempts >= LOCKOUT_THRESHOLD:
            _locked_until = now + LOCKOUT_SECONDS
            _failed_attempts = 0
            raise HTTPException(
                status_code=429,
                detail="Too many failed attempts. Vault locked for 60 seconds.",
            )
        else:
            remaining = LOCKOUT_THRESHOLD - _failed_attempts
            raise HTTPException(
                status_code=401,
                detail=f"Invalid PIN. {remaining} attempt{'s' if remaining != 1 else ''} remaining.",
            )


def verify_token(token: str | None) -> bool:
    """Verify that the token exists and has not expired."""
    if not token:
        return False
    expiry = _valid_tokens.get(token)
    if expiry is None:
        return False
    if time.time() > expiry:
        _valid_tokens.pop(token, None)
        return False
    return True
