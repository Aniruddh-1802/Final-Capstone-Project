"""API test fixtures: a TestClient bound to healthcare_test with one user per role (known test passwords)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import AppUser
from app.security import hash_password

PASSWORDS = {"admin": "Admin-Test-Pass-1", "ops": "Ops-Test-Pass-1", "ana": "Analyst-Test-Pass-1"}
ROLES = {"admin": "administrator", "ops": "clinical_ops", "ana": "analyst"}


@pytest.fixture()
def users_db(clean_db: Engine) -> Engine:
    import seed_reference
    seed_reference.seed_reference(clean_db)  # lookup rows the CRUD endpoints validate against
    with Session(clean_db) as s, s.begin():
        for name, role in ROLES.items():
            s.add(AppUser(username=name, password_hash=hash_password(PASSWORDS[name]), role=role))
        s.add(AppUser(username="inactive", password_hash=hash_password("Inactive-Pass-1"), role="analyst",
                      is_active=False))
    return clean_db


@pytest.fixture()
def client(users_db: Engine) -> TestClient:
    # raise_server_exceptions=False so the catch-all 500 handler's response can be inspected
    return TestClient(create_app(engine=users_db), raise_server_exceptions=False)


def login(client: TestClient, username: str, password: str | None = None):
    return client.post("/auth/login", data={"username": username, "password": password or PASSWORDS[username]})


def auth_header(client: TestClient, username: str) -> dict[str, str]:
    token = login(client, username).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
