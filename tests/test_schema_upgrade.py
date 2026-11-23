from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.database import initialize_schema
from app.models import APIEndpoint, MonitoringHistory, User


def upgrade_schema(engine):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def assert_existing_history_survives_upgrade(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql("""
            CREATE TABLE api_endpoints (
                id INTEGER PRIMARY KEY, name VARCHAR(100), url VARCHAR(500), method VARCHAR(10),
                is_active BOOLEAN, created_at TIMESTAMP, user_id INTEGER
            )
        """)
        connection.exec_driver_sql("""
            CREATE TABLE monitoring_history (
                id INTEGER PRIMARY KEY, endpoint_id INTEGER, status VARCHAR(10), status_code INTEGER,
                response_time FLOAT, checked_at TIMESTAMP
            )
        """)
        connection.exec_driver_sql("""
            INSERT INTO api_endpoints (id, name, url, method, is_active)
            VALUES (1, 'Legacy', 'https://example.com/', 'GET', TRUE)
        """)
        connection.exec_driver_sql("""
            INSERT INTO monitoring_history (id, endpoint_id, status, status_code, response_time)
            VALUES (1, 1, 'DOWN', 302, 10.0)
        """)

    upgrade_schema(engine)
    upgrade_schema(engine)
    initialize_schema(engine)

    with Session(engine) as db:
        endpoint = db.get(APIEndpoint, 1)
        assert endpoint.configuration_error is None
        assert endpoint.configuration_revision == 0
        assert endpoint.next_check_at is not None
        history = db.get(MonitoringHistory, 1)
        assert (history.status, history.status_code, history.reason) == ("DOWN", 302, None)
        assert history.scheduled_for is None
    assert "ix_api_endpoints_active_due" in {index["name"] for index in inspect(engine).get_indexes("api_endpoints")}


def test_schema_upgrade_preserves_existing_data():
    engine = create_engine("sqlite://")
    try:
        assert_existing_history_survives_upgrade(engine)
    finally:
        engine.dispose()


def test_migration_can_bootstrap_a_new_database():
    engine = create_engine("sqlite://")
    try:
        upgrade_schema(engine)
        initialize_schema(engine)
        with Session(engine) as db, db.begin():
            endpoint = APIEndpoint(name="New", url="https://example.com")
            db.add(endpoint)
            db.flush()
            assert endpoint.next_check_at is not None
    finally:
        engine.dispose()


def test_account_migration_preserves_case_colliding_legacy_users():
    engine = create_engine("sqlite://")
    try:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "20261123_01")
            connection.exec_driver_sql("""
                INSERT INTO users (id, username, email, hashed_password)
                VALUES (1, 'legacy', 'Legacy@example.com', 'old-hash'),
                       (2, 'other', 'legacy@example.com', 'other-hash')
            """)
            connection.commit()
        upgrade_schema(engine)
        with Session(engine) as db:
            users = db.query(User).order_by(User.id).all()
            assert [user.email for user in users] == ["Legacy@example.com", "legacy@example.com"]
            assert [user.hashed_password for user in users] == ["old-hash", "other-hash"]
            assert all(user.email_key == "legacy@example.com" and not user.email_verification_required
                       and user.session_version == 0 for user in users)
    finally:
        engine.dispose()
