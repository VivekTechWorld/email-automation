"""
auth.py — API Key Authentication Dependency
=============================================
Enforces bearer-token authentication on all protected routes.
The API key is loaded from the API_KEY environment variable.

Usage in routes:
    @app.get("/protected", dependencies=[Depends(require_api_key)])
    async def protected_route(): ...
"""

import os
import logging
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

log = logging.getLogger(__name__)

_security = HTTPBearer(auto_error=False)

def require_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_security),
) -> str:
    """
    FastAPI dependency that validates the Bearer token against API_KEY env var.
    Returns the validated key on success; raises 401 otherwise.
    """
    api_key = os.getenv("API_KEY", "")
    if not api_key:
        log.warning(
            "API_KEY is not set in .env — all authenticated requests will be rejected. "
            "Set API_KEY in backend/.env to enable access."
        )
        raise HTTPException(status_code=401, detail="Server API_KEY not configured.")

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. Send: Authorization: Bearer <API_KEY>",
        )

    if credentials.credentials != api_key:
        raise HTTPException(status_code=401, detail="Invalid API key.")

    return credentials.credentials
