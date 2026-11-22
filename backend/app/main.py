"""Main FastAPI application for Dyanphil personal search assistant."""

from __future__ import annotations

import logging
import secrets
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.db import get_connection, init_db
from app.ingestion.auto_index import get_auto_index_worker
from app.search.hybrid import warmup_vector_cache
from app.security.logger import PrivacyLogFilter
from app.security.permissions import restrict_data_permissions

logger = logging.getLogger(__name__)

# Apply privacy logging filter
for handler in logging.root.handlers:
    handler.addFilter(PrivacyLogFilter())
logging.getLogger("app").addFilter(PrivacyLogFilter())

# Cookie name and server-generated API session token
API_COOKIE_NAME = "session_token"
_api_token: str = secrets.token_urlsafe(32)


def get_api_token() -> str:
    """Retrieve current in-memory API session token."""
    global _api_token
    return _api_token


def set_api_token(token: str) -> None:
    """Set or override API session token (useful for testing)."""
    global _api_token
    _api_token = token


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager to initialize DB, restrict permissions, warmup vector cache, and manage worker."""
    init_db()
    restrict_data_permissions()
    conn = get_connection()
    try:
        warmup_vector_cache(conn)
    finally:
        conn.close()
    worker = get_auto_index_worker()
    worker.start()
    yield
    worker.stop()


app = FastAPI(
    title="Dyanphil",
    description="Local-first, privacy-first personal search assistant backend",
    version="0.1.0",
    lifespan=lifespan,
)

# 1. Local-only access: TrustedHostMiddleware allowing only 127.0.0.1, localhost (and testserver)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost", "testserver"],
)

# 2. CORS configuration with explicit allow-list
ALLOWED_ORIGIN_HOSTS = {
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGIN_HOSTS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_protection_middleware(request: Request, call_next):
    """
    Harden backend access:
    - Reject any request whose Origin or Referer header is present and not in the allow-list.
    - Require HttpOnly SameSite=Strict session cookie on every API route except /health.
    """
    path = request.url.path

    # Check Origin header if present
    origin = request.headers.get("origin")
    if origin:
        clean_origin = origin.rstrip("/")
        if clean_origin not in ALLOWED_ORIGIN_HOSTS:
            return JSONResponse(
                status_code=403,
                content={"detail": f"Forbidden: Origin '{origin}' is not allowed."},
            )

    # Check Referer header if present
    referer = request.headers.get("referer")
    if referer:
        parsed = urllib.parse.urlparse(referer)
        ref_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        if ref_origin not in ALLOWED_ORIGIN_HOSTS:
            return JSONResponse(
                status_code=403,
                content={"detail": f"Forbidden: Referer '{ref_origin}' is not allowed."},
            )

    # Health check is exempt from cookie requirement
    is_health = path in ("/health", "/api/health")
    is_root_get = path == "/" and request.method == "GET"
    is_static = (
        path.startswith("/assets")
        or path in ("/sw.js", "/manifest.webmanifest", "/favicon.svg", "/icons.svg")
        or path.endswith((".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".ico", ".woff2", ".webmanifest", ".json"))
    )

    if not is_health and not is_root_get and not is_static:
        cookie_val = (
            request.cookies.get(API_COOKIE_NAME)
            or request.cookies.get("app_token")
            or request.headers.get("x-session-token")
        )
        if cookie_val != get_api_token():
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized: missing or invalid session cookie."},
            )

    response = await call_next(request)
    return response


# Paths for mounting frontend
project_root = Path(__file__).resolve().parent.parent.parent
dist_dir = (project_root / "ui" / "dist").resolve()
if not dist_dir.exists():
    dist_dir = Path("ui/dist").resolve()


@app.get("/")
def get_root_page():
    """
    Serve the built UI app and set the HttpOnly, SameSite=Strict session cookie.
    """
    token = get_api_token()
    index_file = dist_dir / "index.html"
    if dist_dir.exists() and index_file.exists():
        resp = FileResponse(str(index_file))
    else:
        resp = HTMLResponse("<!doctype html><html><body>Dyanphil</body></html>")

    resp.set_cookie(
        key=API_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return resp


# Support both root routes (/ask, /open) and /api prefixed routes (/api/ask, /api/open)
app.include_router(router)
app.include_router(router, prefix="/api")

# Mount built UI from ui/dist if it exists for assets
if dist_dir.exists() and (dist_dir / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="static")
