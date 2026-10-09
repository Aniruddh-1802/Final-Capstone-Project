"""Uniform error contract, request ids, health endpoint and database-failure behaviour."""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from app.main import create_app
from tests.api.conftest import auth_header, login


def assert_contract(body: dict, code: str | None = None) -> None:
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "details"}
    assert isinstance(body["error"]["code"], str) and isinstance(body["error"]["message"], str)
    if code:
        assert body["error"]["code"] == code


def test_401_403_404_405_422_share_one_shape(client: TestClient) -> None:
    client.app.add_api_route("/_t/admin", lambda: {}, dependencies=[__import__("fastapi").Depends(
        __import__("app.deps", fromlist=["x"]).require_capability("manage_users"))])
    responses = {
        401: client.get("/auth/me"),
        403: client.get("/_t/admin", headers=auth_header(client, "ana")),
        404: client.get("/does-not-exist"),
        405: client.put("/health"),
        422: client.post("/auth/login", data={"username": "x"}),
    }
    for status, response in responses.items():
        assert response.status_code == status
        assert_contract(response.json())
        assert response.headers["x-request-id"]


def test_422_details_name_the_field_but_never_echo_input(client: TestClient) -> None:
    r = client.post("/auth/login", data={"username": "someone"})  # password missing
    assert r.status_code == 422
    details = r.json()["error"]["details"]
    assert any(d["loc"][-1] == "password" for d in details)
    assert all(set(d) == {"loc", "msg", "type"} for d in details)
    r2 = client.post("/auth/login", data={"password": "Secret-Typed-Password-9"})
    assert "Secret-Typed-Password-9" not in r2.text


def test_unhandled_exception_gives_generic_500_without_internals(client: TestClient) -> None:
    def boom() -> None:
        raise ValueError("secret internal detail: /etc/passwd")
    client.app.add_api_route("/_t/boom", boom)
    r = client.get("/_t/boom")
    assert r.status_code == 500
    assert_contract(r.json(), "internal_error")
    assert "secret internal detail" not in r.text and "Traceback" not in r.text
    assert r.headers["x-request-id"]


def test_database_down_gives_uniform_500_with_no_sql_or_host(users_db: Engine) -> None:
    dead = create_engine("mysql+pymysql://nobody:nopass@127.0.0.1:1/ghost", connect_args={"connect_timeout": 1})
    c = TestClient(create_app(engine=dead), raise_server_exceptions=False)
    r = c.post("/auth/login", data={"username": "admin", "password": "x"})
    assert r.status_code == 500
    assert_contract(r.json(), "database_error")
    for leaked in ("SELECT", "app_users", "pymysql", "127.0.0.1", "nopass", "ghost"):
        assert leaked not in r.text


def test_health_reports_database_and_latest_run(client: TestClient, users_db: Engine) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "up", "latest_pipeline_run": None}
    from sqlalchemy import text
    with users_db.begin() as conn:
        conn.execute(text("INSERT INTO pipeline_runs (source_file, file_hash, status, rows_read, rows_loaded, "
                          "rows_rejected, rows_skipped_existing, triggered_by) VALUES "
                          "('b.csv', NULL, 'SUCCESS', 10, 8, 1, 1, 'test')"))
    run = client.get("/health").json()["latest_pipeline_run"]
    assert run["status"] == "SUCCESS" and run["rows_read"] == 10 and run["rows_loaded"] == 8


def test_health_is_503_degraded_when_database_is_down(users_db: Engine) -> None:
    dead = create_engine("mysql+pymysql://nobody:nopass@127.0.0.1:1/ghost", connect_args={"connect_timeout": 1})
    r = TestClient(create_app(engine=dead), raise_server_exceptions=False).get("/health")
    assert r.status_code == 503 and r.json()["status"] == "degraded" and r.json()["database"] == "down"
    assert "nopass" not in r.text and "pymysql" not in r.text


def test_request_ids_are_unique_and_appear_in_logs(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    ids = {client.get("/health").headers["x-request-id"] for _ in range(5)}
    assert len(ids) == 5
    logger = logging.getLogger("app")
    logger.propagate = True  # let caplog see it; the app logger normally writes to console and file only
    try:
        with caplog.at_level(logging.INFO, logger="app"):
            rid = client.get("/health").headers["x-request-id"]
        assert any("GET /health -> 200" in rec.getMessage() for rec in caplog.records)
        assert any(getattr(rec, "request_id", None) == rid for rec in caplog.records if "GET /health" in rec.getMessage())
    finally:
        logger.propagate = False


def test_cors_allows_the_vite_dev_origin_only(client: TestClient) -> None:
    ok = client.options("/auth/login", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/auth/login", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_swagger_and_openapi_describe_the_bearer_scheme(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    assert "OAuth2PasswordBearer" in spec["components"]["securitySchemes"]
    assert "/auth/login" in spec["paths"] and "/auth/me" in spec["paths"] and "/health" in spec["paths"]
