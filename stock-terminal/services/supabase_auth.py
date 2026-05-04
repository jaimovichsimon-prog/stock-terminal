"""Verify JWTs issued by Supabase Auth using the project's JWKS endpoint."""
import time
from typing import Optional

import httpx
from fastapi import HTTPException, Header
from jose import jwt, JWTError

from config import SUPABASE_URL, SUPABASE_JWT_ALG, logger


_JWKS_CACHE: dict = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 3600  # 1 hour


def _fetch_jwks(force: bool = False) -> dict:
    now = time.time()
    if not force and _JWKS_CACHE["keys"] and now - _JWKS_CACHE["fetched_at"] < _JWKS_TTL_SECONDS:
        return _JWKS_CACHE["keys"]
    url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    resp = httpx.get(url, timeout=5.0)
    resp.raise_for_status()
    _JWKS_CACHE["keys"] = resp.json()
    _JWKS_CACHE["fetched_at"] = now
    return _JWKS_CACHE["keys"]


def _key_for_kid(kid: str, jwks: dict) -> Optional[dict]:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def verify_supabase_jwt(token: str) -> dict:
    """Returns the decoded payload; raises JWTError on failure."""
    try:
        headers = jwt.get_unverified_header(token)
    except JWTError as e:
        raise JWTError(f"Malformed token header: {e}") from e

    kid = headers.get("kid")
    if not kid:
        raise JWTError("Token header missing 'kid'")

    jwks = _fetch_jwks()
    key = _key_for_kid(kid, jwks)
    if key is None:
        # Possible key rotation — refresh once and retry
        jwks = _fetch_jwks(force=True)
        key = _key_for_kid(kid, jwks)
        if key is None:
            raise JWTError(f"No JWKS key found for kid={kid}")

    return jwt.decode(
        token,
        key,
        algorithms=[SUPABASE_JWT_ALG],
        audience="authenticated",
    )


def require_user(authorization: Optional[str] = Header(None)) -> dict:
    """FastAPI dependency: validates the Bearer token and returns the JWT payload.

    Payload contains 'sub' (user UUID) and 'email' among other claims.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return verify_supabase_jwt(authorization.split(" ", 1)[1])
    except JWTError:
        logger.warning("Supabase JWT verification failed", exc_info=True)
        raise HTTPException(status_code=401, detail="Invalid token")
