"""Password hashing (bcrypt) and JWT creation / decoding (PyJWT)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import get_settings

log = logging.getLogger(__name__)
ALGORITHM = "HS256"
MIN_SECRET_LENGTH = 32
PLACEHOLDER_MARKERS = ("change_me", "changeme", "placeholder", "your_secret", "example", "secret_key", "todo")
# Hash checked when the username does not exist, so unknown users cost the same time as wrong passwords.
DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt()).decode("ascii")


def validate_jwt_secret(secret: str | None) -> str:
    """Return the secret or raise RuntimeError if it is missing, too short or a known placeholder."""
    if not secret or not secret.strip():
        raise RuntimeError("JWT_SECRET is not set; refusing to start")
    lowered = secret.lower()
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        raise RuntimeError("JWT_SECRET is a placeholder value; set a random secret in .env")
    if len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters")
    return secret


def hash_password(password: str) -> str:
    """bcrypt hash of a password (bcrypt only uses the first 72 bytes, so longer ones are rejected)."""
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("password longer than 72 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time bcrypt check; malformed hashes and over-long passwords simply fail."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def create_access_token(user_id: int, role: str, expires_minutes: float | None = None) -> str:
    """Signed token holding only the user id (sub), role, issue and expiry times - never a password or hash."""
    settings = get_settings()
    minutes = settings.jwt_expire_minutes if expires_minutes is None else expires_minutes
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user_id), "role": role, "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(claims, validate_jwt_secret(settings.jwt_secret), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify signature and expiry and return the claims; raises ``jwt.PyJWTError`` on any problem."""
    return jwt.decode(token, validate_jwt_secret(get_settings().jwt_secret), algorithms=[ALGORITHM],
                      options={"require": ["exp", "sub", "role"]})
