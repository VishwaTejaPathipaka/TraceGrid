
import socket
import os
from email import policy
from email.parser import BytesParser
import re

import pytest
from alembic.migration import MigrationContext
from sqlalchemy import URL, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db, initialize_schema
from app.main import app
from app.config import settings


@pytest.fixture(scope="session")
def ci_postgres():
    port = os.environ.get("TRACEGRID_CI_POSTGRES_PORT")
    if port is None:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail("The disposable PostgreSQL service must be configured in CI")
        pytest.skip("The disposable PostgreSQL CI service is not configured")

    assert port.isascii() and port.isdecimal() and 1024 <= int(port) <= 65535 and int(port) != 5432
    password = os.environ["TRACEGRID_CI_POSTGRES_PASSWORD"]
    engine = create_engine(
        URL.create("postgresql+psycopg2", username="tracegrid_ci", password=password,
                   host="127.0.0.1", port=int(port), database="tracegrid_ci"),
        hide_parameters=True, connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            identity = connection.exec_driver_sql("""
                SELECT current_database(), current_user, current_setting('server_version_num')::int / 10000,
                       shobj_description(oid, 'pg_database')
                FROM pg_database WHERE datname = current_database()
            """).one()
            assert identity == ("tracegrid_ci", "tracegrid_ci", 17, "TraceGrid disposable CI database")
            assert MigrationContext.configure(connection).get_current_revision() == "20261123_06"
        initialize_schema(engine)
        yield engine
    finally:
        engine.dispose()


def email_tokens(email, page):
    tokens = []
    for path in settings.EMAIL_OUTBOX_DIR.glob("*.eml"):
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        if message["To"] == email:
            tokens.extend(re.findall(rf"/{page}#token=([\w-]{{43}})", message.get_content()))
    return tokens


def verify_test_account(client, email):
    token, = email_tokens(email, "verify-email")
    response = client.post("/users/verify-email", json={"token": token, "password": "TestPass@123"})
    assert response.status_code == 200


def fail_probe_commit(monkeypatch):
    """Allow the rate counter commit, then fail the separate probe write."""
    commit = Session.commit
    calls = 0

    def fail_second(session):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SQLAlchemyError("fixture write failure")
        return commit(session)

    monkeypatch.setattr(Session, "commit", fail_second)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "EMAIL_DELIVERY", "outbox")
    monkeypatch.setattr(settings, "EMAIL_OUTBOX_DIR", tmp_path / "mail")
    monkeypatch.setattr("app.main.start_scheduler", lambda: None)
    monkeypatch.setattr("app.main.scheduler.shutdown", lambda: None)

    def resolve_test_endpoint(host, port, *_):
        assert host == "jsonplaceholder.typicode.com"
        return [(socket.AF_INET, ("8.8.8.8", port))]

    monkeypatch.setattr("app.services.monitoring_policy.lookup_host", resolve_test_endpoint)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
    )

    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
