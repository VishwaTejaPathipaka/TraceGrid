from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Event
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, settings
from app.database import get_db
from app.main import app
from app.models import MonitoringHistory
from app.models.token import RevokedToken
from app.security import create_access_token, revocation_key
from app.services import rate_limits
from app.services.connection_limits import manual_probe_slot
from test_websocket_monitoring import account, bearer, connected, token_lifetime


def database():
    return contextmanager(app.dependency_overrides[get_db])()


def login(client, username, password, headers=None):
    return client.post("/users/login", headers=headers or {}, json={"username": username, "password": password})


def test_login_limit_is_atomic_by_identity_window_and_ignores_forwarded_headers(client, monkeypatch):
    now = [10]
    monkeypatch.setattr(rate_limits, "_clock", lambda _: now[0])
    account(client, "throttle_owner", endpoint=False)
    now[0] = 302
    monkeypatch.setattr(settings, "SECURITY_RATE_OVERRIDES", {"login_source_account": 2, "login_ip": 9})
    for index in range(2):
        assert login(client, "throttle_owner", "incorrect", {"X-Forwarded-For": f"203.0.113.{index+1}"}).status_code == 401
    rejected = login(client, "throttle_owner", "incorrect", {"X-Forwarded-For": "203.0.113.70"})
    assert rejected.status_code == 429
    assert rejected.headers["Retry-After"] == "298"
    assert login(client, "nonexistent_owner", "incorrect").status_code == 401
    now[0] = 600
    assert login(client, "throttle_owner", "TestPass@123").status_code == 200


def test_unknown_user_still_runs_password_verifier_and_returns_same_error(client, monkeypatch):
    account(client, "known_owner", endpoint=False)
    from app import security
    verifier = Mock(wraps=security.verify_password)
    monkeypatch.setattr(security, "verify_password", verifier)
    known = login(client, "known_owner", "not-correct")
    missing = login(client, "unknown_owner", "not-correct")
    assert known.status_code == missing.status_code == 401
    assert known.json() == missing.json()
    assert verifier.call_count == 2


def test_recovery_mail_limits_have_same_responses_for_known_and_unknown(client, monkeypatch):
    account(client, "mail_throttle", endpoint=False)
    monkeypatch.setattr(rate_limits, "_clock", lambda _: 1801)
    monkeypatch.setattr(settings, "SECURITY_RATE_OVERRIDES", {"mail_source_account": 1})
    responses = []
    for email in ("mail_throttle@example.com", "unknown@example.com"):
        requested = client.post("/users/forgot-password", json={"email": email})
        blocked = client.post("/users/resend-verification", json={"email": email.upper()})
        assert requested.status_code == 202 and blocked.status_code == 429
        responses.append((requested.json(), blocked.json(), blocked.headers["Retry-After"]))
    assert responses[0] == responses[1]


def test_body_limits_cors_headers_and_no_hsts_on_http(client, monkeypatch):
    origin = "http://localhost:5173"
    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_BYTES", 1024)
    monkeypatch.setattr(settings, "ENABLE_HSTS", True)
    payload = b"x" * 1100
    response = client.post("/users/login", headers={"Origin": origin}, content=payload)
    assert response.status_code == 413
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert "Retry-After" in response.headers["Access-Control-Expose-Headers"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "Strict-Transport-Security" not in response.headers
    assert client.get("https://testserver/health").headers["Strict-Transport-Security"] == "max-age=31536000"
    chunked = client.post("/users/login", headers={"Transfer-Encoding": "chunked"}, content=iter([payload[:600], payload[600:]]))
    assert chunked.status_code == 413
    denied = client.options("/users/login", headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST"})
    assert denied.status_code == 400 and "Access-Control-Allow-Origin" not in denied.headers
    with pytest.raises(ValueError):
        Settings(_env_file=None, DATABASE_URL="sqlite://", SECRET_KEY="fixture-key", FRONTEND_ORIGINS=["*"])
    with pytest.raises(ValueError):
        Settings(_env_file=None, DATABASE_URL="sqlite://", SECRET_KEY="fixture-key", TRUSTED_PROXY_NETWORKS=["0.0.0.0/0"])


def test_invalid_input_and_database_errors_do_not_echo_values(client, monkeypatch, caplog):
    private_fixture = "not-a-real-sensitive-value"
    invalid = client.post("/users/verify-email", json={"token": private_fixture, "password": "short"})
    assert invalid.status_code == 422 and private_fixture not in invalid.text
    monkeypatch.setattr("app.routes.users.limit_account_request", Mock(side_effect=SQLAlchemyError(private_fixture)))
    failed = login(client, "missing", "incorrect")
    assert failed.status_code == 503 and private_fixture not in failed.text
    assert private_fixture not in caplog.text


def test_jwt_expiry_and_old_and_new_revocations_still_apply(client, monkeypatch):
    name = "token_owner"
    current = account(client, name, endpoint=False)
    expired = token_lifetime(monkeypatch, name, -60)
    assert client.get("/endpoints/", headers=bearer(expired)).status_code == 401
    old = create_access_token({"sub": name})
    with database() as db:
        db.add(RevokedToken(token=old))
        db.commit()
    assert client.get("/endpoints/", headers=bearer(old)).status_code == 401
    assert client.post("/users/logout", headers=bearer(current)).status_code == 200
    with database() as db:
        revocations = db.scalars(select(RevokedToken.token)).all()
        assert revocation_key(current) in revocations and current not in revocations
    assert client.get("/endpoints/", headers=bearer(current)).status_code == 401


def test_socket_frame_and_connection_limits_release_capacity(client, monkeypatch):
    token = account(client, "socket_capacity_fixture", endpoint=False)
    monkeypatch.setattr(settings, "MAX_WEBSOCKETS_PER_USER", 1)
    with connected(client, token):
        with client.websocket_connect("/ws/monitoring") as excess:
            excess.send_json({"type": "authenticate", "token": token})
            assert excess.receive()["code"] == 1013
    with connected(client, token):
        pass
    monkeypatch.setattr(settings, "MAX_WEBSOCKETS_PER_IP", 1)
    with client.websocket_connect("/ws/monitoring") as waiting:
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect("/ws/monitoring") as _:
                pass
        assert rejected.value.code == 1013
        waiting.send_text("é" * 4500)
        assert waiting.receive()["code"] == 1009


def test_endpoint_manual_and_analytics_limits_are_per_owner(client, monkeypatch):
    _, endpoint = account(client, "busy_owner")
    owner = bearer(login(client, "busy_owner", "TestPass@123").json()["access_token"])
    other, other_endpoint = account(client, "other_owner")
    other = bearer(other)
    monkeypatch.setattr(settings, "MAX_ENDPOINTS_PER_USER", 1)
    payload = {"name": "Test", "url": "https://jsonplaceholder.typicode.com/"}
    assert client.post("/endpoints/", headers=owner, json=payload).status_code == 409
    assert client.put(f"/endpoints/{endpoint}", headers=owner, json=payload).status_code == 200
    monkeypatch.setattr(settings, "SECURITY_RATE_OVERRIDES", {"manual_check": 1, "analytics": 1})
    monkeypatch.setattr("app.routes.monitoring.check_api", Mock(return_value={
        "status": "UP", "status_code": 204, "response_time": 1.5,
    }))
    assert client.get(f"/monitor/{endpoint}/check", headers=owner).status_code == 200
    assert client.get(f"/monitor/{endpoint}/check", headers=owner).status_code == 429
    assert client.get(f"/monitor/{other_endpoint}/check", headers=other).status_code == 200
    assert client.get("/analytics/report", headers=owner).status_code == 200
    assert client.get("/analytics/report", headers=owner).status_code == 429
    assert client.get("/analytics/report", headers=other).status_code == 200


def test_manual_probe_slots_are_released_and_separate_from_database_transactions(client, monkeypatch):
    monkeypatch.setattr(settings, "MANUAL_PROBE_SLOTS", 1)
    with database() as db:
        engine = db.get_bind()
    entered, release = Event(), Event()

    def probe():
        with manual_probe_slot(engine, 1):
            entered.set()
            assert release.wait(3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        task = pool.submit(probe)
        try:
            assert entered.wait(3)
            with pytest.raises(HTTPException) as error:
                with manual_probe_slot(engine, 2):
                    pass
            assert error.value.status_code == 429 and error.value.headers["Retry-After"] == "10"
        finally:
            release.set()
        task.result(timeout=3)
    with manual_probe_slot(engine, 2):
        pass


def test_monitoring_history_pages_without_missing_equal_timestamps(client):
    token, endpoint = account(client, "history_pages")
    stamp = datetime.now(timezone.utc)
    with database() as db:
        db.add_all([MonitoringHistory(endpoint_id=endpoint, checked_at=stamp, status="UP", status_code=204,
                                      response_time=float(index)) for index in range(30)])
        db.commit()
    path = f"/monitor/{endpoint}/history"
    first = client.get(path, headers=bearer(token), params={"limit": 15}).json()
    second = client.get(path, headers=bearer(token), params={"limit": 15, "before_id": first[-1]["id"]}).json()
    assert [row["response_time"] for row in [*first, *second]] == list(reversed(range(30)))
    assert client.get(path, headers=bearer(token), params={"limit": 251}).status_code == 422


def test_launcher_keeps_forwarding_opt_in_and_disables_handshake_query_logging(monkeypatch):
    from app import serve

    run = Mock()
    monkeypatch.setattr(serve.uvicorn, "run", run)
    monkeypatch.setattr("sys.argv", ["tracegrid"])
    monkeypatch.setattr(settings, "TRUSTED_PROXY_NETWORKS", [])
    serve.main()
    assert run.call_args.kwargs["proxy_headers"] is False
    assert run.call_args.kwargs["access_log"] is False
    assert run.call_args.kwargs["log_level"] == "warning"
    assert run.call_args.kwargs["ws_max_size"] == 8192
    monkeypatch.setattr(settings, "TRUSTED_PROXY_NETWORKS", ["127.0.0.2/32"])
    serve.main()
    assert run.call_args.kwargs["forwarded_allow_ips"] == "127.0.0.2/32"
    assert run.call_args.kwargs["proxy_headers"] is True
