"""
auth.py — API Key + Dashboard Session Authentication
=====================================================
Two kinds of bearer tokens are accepted on protected routes:

1. API_KEY            — for machine clients (n8n, scripts). Never shipped to the browser.
2. Dashboard session  — issued by POST /auth/login after the server checks
                        DASHBOARD_PASSWORD. Signed with HMAC and expires after
                        DASHBOARD_SESSION_HOURS (default 12).

Usage in routes:
    @app.get("/protected", dependencies=[Depends(require_api_key)])
    async def protected_route(): ...
"""

import os
import hmac
import time
import base64
import hashlib
import logging
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

log = logging.getLogger(__name__)

_security = HTTPBearer(auto_error=False)

# Values copied from .env.example — refuse to treat them as real secrets
INSECURE_DEFAULTS = {"", "changeme-secret-api-key-2026", "admin123", "changeme"}


def _signing_key() -> bytes:
    secret = os.getenv("SESSION_SECRET") or os.getenv("API_KEY", "")
    return hashlib.sha256(f"dashboard-session::{secret}".encode()).digest()


def issue_session_token() -> tuple[str, int]:
    """Create a signed dashboard session token. Returns (token, expires_at_unix)."""
    hours = float(os.getenv("DASHBOARD_SESSION_HOURS", "12"))
    expires_at = int(time.time() + hours * 3600)
    payload = f"dash.{expires_at}"
    sig = hmac.new(_signing_key(), payload.encode(), hashlib.sha256).digest()
    token = f"{payload}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"
    return token, expires_at


def _valid_session_token(token: str) -> bool:
    try:
        prefix, expires_str, sig_b64 = token.split(".")
        if prefix != "dash" or int(expires_str) < time.time():
            return False
        expected = hmac.new(_signing_key(), f"dash.{expires_str}".encode(), hashlib.sha256).digest()
        given = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
        return hmac.compare_digest(expected, given)
    except (ValueError, TypeError):
        return False


def check_dashboard_password(password: str) -> bool:
    expected = os.getenv("DASHBOARD_PASSWORD", "")
    if not expected:
        log.warning("DASHBOARD_PASSWORD is not set — dashboard login disabled.")
        return False
    return hmac.compare_digest(password.encode(), expected.encode())


def require_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_security),
) -> str:
    """
    FastAPI dependency that validates the Bearer token (API key or dashboard session).
    Returns the token on success; raises 401 otherwise.
    """
    api_key = os.getenv("API_KEY", "")
    if not api_key:
        log.warning("API_KEY is not set in backend/.env — all authenticated requests will be rejected.")
        raise HTTPException(status_code=401, detail="Server API key not configured.")

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. Send: Authorization: Bearer <token>",
        )

    token = credentials.credentials
    if hmac.compare_digest(token.encode(), api_key.encode()) or _valid_session_token(token):
        return token

    raise HTTPException(status_code=401, detail="Invalid or expired credentials.")
