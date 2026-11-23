from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema

from app import database
from app.config import settings
from app.main import app
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


def test_postgres_account_requests_use_migrated_schema(postgres_schema, monkeypatch, tmp_path):
    upgrade_schema(postgres_schema)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=postgres_schema))
    monkeypatch.setattr("app.main.start_scheduler", lambda: None)
    monkeypatch.setattr("app.main.scheduler.shutdown", lambda: None)
    monkeypatch.setattr(settings, "EMAIL_DELIVERY", "outbox")
    monkeypatch.setattr(settings, "EMAIL_OUTBOX_DIR", tmp_path / "outbox")
    account = {"username": "ci_fixture", "email": "ci-fixture@example.com", "password": "TestPass@123"}
    login = {key: account[key] for key in ("username", "password")}

    with TestClient(app) as client:
        assert client.post("/users/register", json=account).status_code == 202
        assert client.post("/users/login", json=login).status_code == 403
        verify_test_account(client, account["email"])
        response = client.post("/users/login", json=login)
        assert response.status_code == 200
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        assert client.get("/endpoints/", headers=headers).json() == []


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
