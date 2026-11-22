"""OAuth2 authentication and Windows Credential Manager integration for Gmail."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import settings

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "dyanphil_gmail"
KEYRING_USERNAME = "token"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SCOPES = [GMAIL_READONLY_SCOPE]


def get_client_secret_path() -> Path:
    """Return path to client_secret.json in data directory credentials folder."""
    return settings.data_dir / "credentials" / "client_secret.json"


def save_credentials(creds: Credentials) -> None:
    """Store credentials serialized as JSON securely in Windows Credential Manager via keyring."""
    token_data = creds.to_json()
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, token_data)


def load_raw_credentials() -> str | None:
    """Retrieve raw credentials JSON string from keyring."""
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception as exc:
        logger.debug("Failed to read token from keyring: %s", exc)
        return None


def get_credentials() -> Credentials | None:
    """
    Load credentials from keyring and automatically refresh if expired.
    Raises RuntimeError("please connect again") if refresh fails or token is invalid.
    """
    raw = load_raw_credentials()
    if not raw:
        return None

    try:
        info = json.loads(raw)
        creds = Credentials.from_authorized_user_info(info, scopes=SCOPES)
    except Exception as exc:
        logger.error("Failed to parse credentials from keyring: %s", exc)
        raise RuntimeError("please connect again") from exc

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_credentials(creds)
        except Exception as exc:
            logger.error("Failed to refresh Gmail token: %s", exc)
            raise RuntimeError("please connect again") from exc

    if not creds or not creds.valid:
        raise RuntimeError("please connect again")

    return creds


def start_auth_flow(open_browser: bool = True) -> Credentials:
    """
    Start OAuth InstalledAppFlow using ONLY the gmail.readonly scope on 127.0.0.1.
    Reads client secret from <data_dir>/credentials/client_secret.json.
    """
    secret_path = get_client_secret_path()
    if not secret_path.exists():
        raise FileNotFoundError(
            f"Gmail client secret not found at {secret_path}. "
            f"Please download your OAuth2 client secret JSON from Google Cloud Console "
            f"and place it at {secret_path}."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(secret_path),
        scopes=SCOPES,
    )
    creds = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=open_browser,
    )
    save_credentials(creds)
    return creds


def delete_credentials() -> None:
    """Delete Gmail credentials from Windows Credential Manager."""
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:
        # Ignore if password does not exist
        pass


def is_connected() -> bool:
    """Check whether a valid or refreshable Gmail credential exists."""
    try:
        creds = get_credentials()
        return creds is not None and creds.valid
    except Exception:
        return False
