"""Permissions module for securing the local data directory on Windows."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def restrict_data_permissions(data_dir: Path | str | None = None) -> bool:
    """
    On startup, restrict the data folder (e.g. D:\\prompteng\\data) to the current Windows user
    using icacls (removes inherited access).
    Logs a warning instead of crashing if it fails.
    """
    if os.name != "nt":
        return True

    try:
        target = Path(data_dir or settings.data_dir).resolve()
        target.mkdir(parents=True, exist_ok=True)

        username = os.environ.get("USERNAME")
        if not username:
            logger.warning("Could not determine current Windows USERNAME for icacls permission restriction.")
            return False

        # /inheritance:r removes inherited permissions
        # /grant:r grants specified user full control with inheritance for child objects/containers
        cmd = [
            "icacls",
            str(target),
            "/inheritance:r",
            "/grant:r",
            f"{username}:(OI)(CI)F",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            logger.warning(
                "icacls failed with return code %d: %s",
                result.returncode,
                result.stderr.strip() or result.stdout.strip(),
            )
            return False

        return True

    except Exception as exc:
        logger.warning("Failed to restrict data folder permissions with icacls: %s", exc)
        return False
