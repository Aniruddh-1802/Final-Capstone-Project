"""FastAPI dependencies: database session, current user, and the single role check."""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import AppUser
from app.permissions import roles_for
from app.security import decode_access_token

log = logging.getLogger(__name__)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)
_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


def get_db(request: Request) -> Iterator[Session]:
    """One session per request, bound to the app's engine and always closed."""
    with Session(request.app.state.engine, expire_on_commit=False) as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated caller (role comes from the database, not from the token)."""

    user_id: int
    username: str
    role: str


def _unauthorized() -> ApiError:
    return ApiError(401, "unauthorized", "Not authenticated", headers=_UNAUTHORIZED)


def get_current_user(token: Annotated[str | None, Depends(oauth2_scheme)], db: DbSession) -> CurrentUser:
    """Decode the bearer token and load the active user; any failure is the same 401."""
    if not token:
        raise _unauthorized()
    try:
        claims = decode_access_token(token)
        user_id = int(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise _unauthorized() from None
    user = db.scalar(select(AppUser).where(AppUser.user_id == user_id))
    if user is None or not user.is_active:
        raise _unauthorized()
    return CurrentUser(user_id=user.user_id, username=user.username, role=user.role)


def require_roles(*roles: str) -> Callable[[CurrentUser], CurrentUser]:
    """Dependency factory: 403 unless the caller's role is in ``roles`` (the only place roles are checked)."""
    allowed = frozenset(roles)

    def checker(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in allowed:
            log.warning("403 for user_id=%s role=%s", user.user_id, user.role)
            raise ApiError(403, "forbidden", "You do not have permission to perform this action")
        return user

    return checker


def require_capability(capability: str) -> Callable[[CurrentUser], CurrentUser]:
    """``require_roles`` driven by the permission-matrix constant, so the matrix stays the single source of truth."""
    return require_roles(*roles_for(capability))
