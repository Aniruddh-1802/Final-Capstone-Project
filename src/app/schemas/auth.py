"""Request/response models for authentication."""
from __future__ import annotations

from pydantic import BaseModel


class TokenOut(BaseModel):
    """Login response (OAuth2 bearer token)."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserOut(BaseModel):
    """The authenticated user. Never includes the password hash."""

    user_id: int
    username: str
    role: str
