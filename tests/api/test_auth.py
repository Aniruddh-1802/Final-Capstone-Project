"""Authentication, authorisation, permission-matrix and startup-safety tests."""
from __future__ import annotations

import re
from pathlib import Path

import jwt
import pytest
from fastapi import Depends
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import permissions, security
from app.config import get_settings
from app.deps import require_capability
from app.main import create_app
from app.models import AppUser
from tests.api.conftest import PASSWORDS, auth_header, login

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "data_contract.md"


def test_login_success_returns_bearer_token_and_updates_last_login(client: TestClient, users_db: Engine) -> None:
    r = login(client, "admin")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == get_settings().jwt_expire_minutes * 60
    assert r.headers["x-request-id"]
    with Session(users_db) as s:
        assert s.scalar(select(AppUser.last_login_at).where(AppUser.username == "admin")) is not None


def test_token_holds_only_id_role_and_times_never_password_or_hash(client: TestClient) -> None:
    token = login(client, "ops").json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert set(claims) == {"sub", "role", "iat", "exp"} and claims["role"] == "clinical_ops"
    assert PASSWORDS["ops"] not in token and "$2b$" not in token


def test_me_returns_user_and_role_without_hash(client: TestClient) -> None:
    r = client.get("/auth/me", headers=auth_header(client, "ana"))
    assert r.status_code == 200
    assert r.json() == {"user_id": r.json()["user_id"], "username": "ana", "role": "analyst"}
    assert "password" not in r.text.lower()


def test_wrong_password_and_unknown_user_give_identical_401(client: TestClient) -> None:
    wrong = login(client, "admin", "not-the-password")
    unknown = login(client, "nobody", "whatever")
    inactive = login(client, "inactive", "Inactive-Pass-1")
    for r in (wrong, unknown, inactive):
        assert r.status_code == 401
    assert wrong.json() == unknown.json() == inactive.json()
    assert wrong.json()["error"]["message"] == "Incorrect username or password"


def test_overlong_password_is_just_a_failed_login(client: TestClient) -> None:
    assert login(client, "admin", "x" * 200).status_code == 401


def test_missing_token_is_401(client: TestClient) -> None:
    r = client.get("/auth/me")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert r.json()["error"]["code"] == "unauthorized"


def test_expired_token_is_401(client: TestClient, users_db: Engine) -> None:
    with Session(users_db) as s:
        uid = s.scalar(select(AppUser.user_id).where(AppUser.username == "admin"))
    token = security.create_access_token(uid, "administrator", expires_minutes=-1)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_tampered_token_and_foreign_secret_are_401(client: TestClient) -> None:
    token = login(client, "admin").json()["access_token"]
    head, payload, sig = token.split(".")
    flipped = sig[:10] + ("A" if sig[10] != "A" else "B") + sig[11:]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {head}.{payload}.{flipped}"}).status_code == 401
    forged = jwt.encode({"sub": "1", "role": "administrator", "exp": 9999999999}, "a-different-secret-" * 3, "HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    unsigned = jwt.encode({"sub": "1", "role": "administrator", "exp": 9999999999}, None, algorithm="none")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {unsigned}"}).status_code == 401


def test_deactivated_user_token_stops_working(client: TestClient, users_db: Engine) -> None:
    headers = auth_header(client, "ana")
    with Session(users_db) as s, s.begin():
        s.scalar(select(AppUser).where(AppUser.username == "ana")).is_active = False
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_role_comes_from_database_not_token(client: TestClient, users_db: Engine) -> None:
    with Session(users_db) as s:
        uid = s.scalar(select(AppUser.user_id).where(AppUser.username == "ana"))
    forged_role = security.create_access_token(uid, "administrator")  # analyst user, admin claim
    app = client.app
    app.add_api_route("/_t/admin", lambda: {"ok": True}, dependencies=[Depends(require_capability("manage_users"))])
    assert client.get("/_t/admin", headers={"Authorization": f"Bearer {forged_role}"}).status_code == 403


def test_wrong_role_is_403_right_role_is_200(client: TestClient) -> None:
    client.app.add_api_route("/_t/admin", lambda: {"ok": True}, dependencies=[Depends(require_capability("manage_users"))])
    assert client.get("/_t/admin").status_code == 401
    assert client.get("/_t/admin", headers=auth_header(client, "ops")).status_code == 403
    assert client.get("/_t/admin", headers=auth_header(client, "ana")).status_code == 403
    assert client.get("/_t/admin", headers=auth_header(client, "admin")).status_code == 200


def test_every_route_except_login_and_health_requires_a_token(client: TestClient) -> None:
    public = {("POST", "/auth/login"), ("GET", "/health")}
    # app.routes only holds lazy router objects in recent FastAPI, so enumerate the endpoints from the OpenAPI spec
    # (docs, redoc and openapi.json are documentation routes, not data endpoints, and are not in the spec).
    spec = client.get("/openapi.json").json()["paths"]
    checked = []
    for route_path, operations in spec.items():
        path = re.sub(r"\{[^}]+\}", "1", route_path)
        for method in operations:
            if (method.upper(), route_path) in public:
                continue
            r = client.request(method.upper(), path)
            assert r.status_code == 401, f"{method.upper()} {route_path} is reachable without a token ({r.status_code})"
            checked.append((method.upper(), route_path))
    assert ("GET", "/auth/me") in checked and len(spec) >= 3  # fails loudly if enumeration ever returns nothing


# ---- permission matrix ------------------------------------------------------------------------------------
def _contract_matrix() -> dict[str, set[str]]:
    matrix: dict[str, set[str]] = {}
    for line in CONTRACT.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and re.fullmatch(r"`\w+`", cells[0]):
            roles = {role for role, cell in zip(("administrator", "clinical_ops", "analyst"), cells[2:]) if cell.startswith("Yes")}
            matrix[cells[0].strip("`")] = roles
    return matrix


def test_permission_matrix_in_code_matches_the_contract_document() -> None:
    doc = _contract_matrix()
    code = {k: set(v) for k, v in permissions.PERMISSIONS.items()}
    assert doc == code and len(doc) == 10


def test_matrix_spot_checks() -> None:
    assert permissions.roles_for("delete_records") == {"administrator"}
    assert "analyst" not in permissions.roles_for("view_patients")
    assert permissions.is_minimised("list_encounters", "analyst") and not permissions.is_minimised("list_encounters", "administrator")
    with pytest.raises(KeyError):
        permissions.roles_for("typo")


# ---- startup safety ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("secret", [None, "", "   ", "CHANGE_ME_RANDOM_LONG_STRING", "short", "my-secret_key-aaaaaaaaaaaaaaaaaaaaaaaaaaaa"])
def test_service_refuses_missing_or_placeholder_jwt_secret(secret: str | None) -> None:
    with pytest.raises(RuntimeError):
        security.validate_jwt_secret(secret)


def test_create_app_refuses_to_start_with_placeholder_secret(monkeypatch: pytest.MonkeyPatch, users_db: Engine) -> None:
    settings = get_settings().model_copy(update={"jwt_secret": "CHANGE_ME_RANDOM_LONG_STRING"})
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    with pytest.raises(RuntimeError, match="placeholder"):
        create_app(engine=users_db)


def test_a_valid_secret_is_accepted() -> None:
    assert security.validate_jwt_secret("x" * 40 + "abc") == "x" * 40 + "abc"
