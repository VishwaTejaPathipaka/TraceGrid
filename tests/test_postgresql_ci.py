from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema

from app import database
from app.config import settings
from app.main import app
from app.models import APIEndpoint, Incident, MonitoringHistory, User
from app.services import rate_limits
from conftest import verify_test_account
from test_scheduler import assert_postgres_slots_and_claims
from test_schema_upgrade import assert_existing_history_survives_upgrade, upgrade_schema


@pytest.fixture
def postgres_schema(ci_postgres):
    # Each case gets a blank schema in the already verified disposable database.
    schema = f"ci_case_{uuid4().hex}"
    with ci_postgres.begin() as connection:
        connection.execute(CreateSchema(schema))
    url = ci_postgres.url.update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(url, hide_parameters=True)
    try:
        yield engine
    finally:
        engine.dispose()


def test_postgres_legacy_upgrade_preserves_history(postgres_schema):
    assert_existing_history_survives_upgrade(postgres_schema)


@pytest.fixture
def postgres_client(postgres_schema, monkeypatch, tmp_path):
    upgrade_schema(postgres_schema)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=postgres_schema))
    monkeypatch.setattr("app.main.start_scheduler", lambda: None)
    monkeypatch.setattr("app.main.scheduler.shutdown", lambda: None)
    monkeypatch.setattr(settings, "EMAIL_DELIVERY", "outbox")
    monkeypatch.setattr(settings, "EMAIL_OUTBOX_DIR", tmp_path / "outbox")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_postgres_account_requests_use_migrated_schema(postgres_client):
    client = postgres_client
    account = {"username": "ci_fixture", "email": "ci-fixture@example.com", "password": "TestPass@123"}
    login = {key: account[key] for key in ("username", "password")}

    assert client.post("/users/register", json=account).status_code == 202
    assert client.post("/users/login", json=login).status_code == 403
    verify_test_account(client, account["email"])
    response = client.post("/users/login", json=login)
    assert response.status_code == 200
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert client.get("/endpoints/", headers=headers).json() == []


def test_postgres_delete_endpoint_with_history_preserves_other_data(postgres_schema, postgres_client, monkeypatch):
    client = postgres_client
    account = {"username": "ci_delete", "email": "ci-delete@example.com", "password": "TestPass@123"}
    assert client.post("/users/register", json=account).status_code == 202
    verify_test_account(client, account["email"])
    login = client.post("/users/login", json={key: account[key] for key in ("username", "password")})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    with Session(postgres_schema) as db, db.begin():
        owner = db.scalar(select(User).where(User.username == account["username"]))
        other = User(username="ci_other", email="ci-other@example.com", hashed_password="unused")
        db.add(other)
        db.flush()
        target = APIEndpoint(name="Remove fixture", url="https://example.com/remove", user_id=owner.id)
        private = APIEndpoint(name="Keep fixture", url="https://example.com/keep", user_id=other.id)
        db.add_all([target, private])
        db.flush()
        target_id, private_id = target.id, private.id
        now = datetime.now(timezone.utc)
        incident = Incident(owner_id=owner.id, endpoint_id=target_id, endpoint_name=target.name,
                            title="Fixture incident", status="open", severity="critical",
                            failure_reason="http_error", started_at=now, detected_at=now)
        db.add_all([
            MonitoringHistory(endpoint_id=target_id, status="DOWN", status_code=503, response_time=12, checked_at=now),
            MonitoringHistory(endpoint_id=private_id, status="UP", status_code=200, response_time=8, checked_at=now),
            incident,
        ])
        db.flush()
        incident_id, owner_id = incident.id, owner.id

    def fail_after_deletions(db, _event):
        db.flush()
        db.execute(text("SELECT 1 / 0"))

    assert client.delete(f"/endpoints/{private_id}", headers=headers).status_code == 404
    with monkeypatch.context() as failure:
        failure.setattr("app.routes.endpoints.stage_event", fail_after_deletions)
        assert client.delete(f"/endpoints/{target_id}", headers=headers).status_code == 503
    with Session(postgres_schema) as db:
        assert db.get(APIEndpoint, target_id) is not None
        assert db.scalars(select(MonitoringHistory.endpoint_id).order_by(MonitoringHistory.endpoint_id)).all() == [
            target_id, private_id,
        ]
        assert db.get(Incident, incident_id).endpoint_id == target_id

    status = client.delete(f"/endpoints/{target_id}", headers=headers).status_code
    assert status == 200, f"Deleting the owned endpoint returned HTTP {status}"
    with Session(postgres_schema) as db:
        assert db.get(APIEndpoint, target_id) is None
        assert db.get(APIEndpoint, private_id) is not None
        assert db.scalars(select(MonitoringHistory.endpoint_id)).all() == [private_id]
        preserved_incident = db.get(Incident, incident_id)
        assert (preserved_incident.owner_id, preserved_incident.endpoint_id, preserved_incident.status) == (
            owner_id, None, "open",
        )


def test_postgres_independent_workers_share_one_rate_budget(postgres_schema, monkeypatch):
    upgrade_schema(postgres_schema)
    monkeypatch.setattr(settings, "SECURITY_RATE_OVERRIDES", {"login_account": 3})
    # Keep all workers in a single fixed window while PostgreSQL arbitrates writes.
    monkeypatch.setattr(rate_limits, "_clock", lambda _: 1_800_000_000)
    start = Barrier(8, timeout=10)

    def consume(_):
        start.wait()
        with Session(postgres_schema) as session:
            try:
                rate_limits.enforce_limits(session, ("login_account", "ci-shared-budget"))
                return 200
            except HTTPException as error:
                assert error.status_code == 429 and int(error.headers["Retry-After"]) > 0
                return error.status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(consume, range(8)))
    assert sorted(results) == [200] * 3 + [429] * 5


def test_postgres_independent_scheduler_slots_prevent_duplicates(postgres_schema, monkeypatch):
    upgrade_schema(postgres_schema)
    second_engine = create_engine(postgres_schema.url, hide_parameters=True)
    try:
        assert_postgres_slots_and_claims(postgres_schema, second_engine, monkeypatch)
    finally:
        second_engine.dispose()
