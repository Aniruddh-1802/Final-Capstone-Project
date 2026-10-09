"""Authentication endpoints: POST /auth/login and GET /auth/me."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.config import get_settings
from app.deps import CurrentUser, DbSession, get_current_user
from app.errors import ApiError
from app.models import AppUser
from app.schemas.auth import TokenOut, UserOut
from app.security import DUMMY_HASH, create_access_token, verify_password

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
INVALID_CREDENTIALS = "Incorrect username or password"  # one message for unknown user, wrong password, inactive user


@router.post("/login", response_model=TokenOut, summary="Log in and receive a bearer token")
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession) -> TokenOut:
    """OAuth2 password flow. Unknown user and wrong password return the identical 401."""
    user = db.scalar(select(AppUser).where(AppUser.username == form.username))
    password_ok = verify_password(form.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not password_ok or not user.is_active:
        log.warning("login failed")
        raise ApiError(401, "invalid_credentials", INVALID_CREDENTIALS, headers={"WWW-Authenticate": "Bearer"})
    user.last_login_at = datetime.now()
    db.commit()
    log.info("login ok user_id=%s role=%s", user.user_id, user.role)
    return TokenOut(access_token=create_access_token(user.user_id, user.role),
                    expires_in=get_settings().jwt_expire_minutes * 60)


@router.get("/me", response_model=UserOut, summary="The authenticated user")
def me(user: Annotated[CurrentUser, Depends(get_current_user)]) -> UserOut:
    """Return the caller's id, username and role."""
    return UserOut(user_id=user.user_id, username=user.username, role=user.role)
