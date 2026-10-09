"""Create one user per role with bcrypt-hashed passwords. Idempotent.

Passwords come from ADMIN_PASSWORD / CLINICAL_OPS_PASSWORD / ANALYST_PASSWORD (env or .env). If unset, a
random password is generated and printed once for NEW users only. Existing users are never changed.
Usernames can be overridden with ADMIN_USERNAME / CLINICAL_OPS_USERNAME / ANALYST_USERNAME.

Run from the repository root:  python db/seed_users.py
"""
from __future__ import annotations

import logging
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import bcrypt  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import Engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import create_all, get_engine  # noqa: E402
from app.models import AppUser  # noqa: E402
from utils.logging_config import setup_logging  # noqa: E402

log = logging.getLogger("seed_users")
DEFAULT_USERNAMES = {"administrator": "admin", "clinical_ops": "clinical_ops", "analyst": "analyst"}
ENV_PREFIX = {"administrator": "ADMIN", "clinical_ops": "CLINICAL_OPS", "analyst": "ANALYST"}


def hash_password(password: str) -> str:
    """Return a bcrypt hash (bcrypt only hashes the first 72 bytes, so longer passwords are rejected)."""
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("password longer than 72 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def seed_users(engine: Engine) -> dict[str, str]:
    """Create missing users; return {username: generated_password} for users created with a random password."""
    generated: dict[str, str] = {}
    with Session(engine) as session, session.begin():
        for role, default_name in DEFAULT_USERNAMES.items():
            prefix = ENV_PREFIX[role]
            username = os.environ.get(f"{prefix}_USERNAME") or default_name
            if session.scalar(select(AppUser).where(AppUser.username == username)):
                log.info("User %s already exists; left unchanged", username)
                continue
            password = os.environ.get(f"{prefix}_PASSWORD") or ""
            if not password:
                password = secrets.token_urlsafe(12)
                generated[username] = password
            session.add(AppUser(username=username, password_hash=hash_password(password), role=role))
            log.info("Created %s user %s", role, username)  # never log the password
    return generated


if __name__ == "__main__":
    setup_logging("seed_users", log_dir=ROOT / "logs")
    load_dotenv(ROOT / ".env")
    eng = get_engine()
    create_all(eng)
    for name, pwd in seed_users(eng).items():
        sys.stdout.write(f"GENERATED PASSWORD (shown once) {name}: {pwd}\n")
