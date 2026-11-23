from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
import re
from unittest.mock import MagicMock

import psycopg2
import pytest
from sqlalchemy import URL, create_engine, func, select
from sqlalchemy.orm import Session

from app.maintain_history import RETENTION_LOCK, RetentionPlan, RetentionRefused, main, run_retention
from app.models import APIEndpoint, Incident, IncidentNotification, MonitoringHistory, RateLimitCounter, RevokedToken, User
from app.routes.monitoring import get_dashboard_summary, get_recent_activity
from app.services.advanced_analytics import Window, endpoint_report


def test_cleanup_disabled_without_explicit_enable_and_confirmation(monkeypatch):
    isolated = RetentionPlan("isolated", apply=True, confirmation="isolated")
    with pytest.raises(RetentionRefused):
        isolated.validate()
    with pytest.raises(RetentionRefused):
        RetentionPlan("isolated", apply=True, confirmation="other").validate(True)
    with pytest.raises(RetentionRefused):
        RetentionPlan("isolated", batch_size=2001).validate()
    monkeypatch.delenv("MONITORING_RETENTION_ENABLED", raising=False)
    connect = MagicMock()
    monkeypatch.setattr("app.maintain_history.psycopg2.connect", connect)
    monkeypatch.setattr("sys.argv", ["history", "--database", "isolated", "--apply", "--confirm-database", "isolated"])
    with pytest.raises(SystemExit, match="2"):
        main()
    connect.assert_not_called()


def test_default_command_reports_only_aggregate_values(monkeypatch, capsys):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    now = datetime(2026, 11, 23, tzinfo=timezone.utc)
    cursor.fetchone.side_effect = [("isolated", now), (19,)]
    monkeypatch.setattr("app.maintain_history.psycopg2.connect", lambda **_: connection)
    monkeypatch.setattr("sys.argv", ["history", "--database", "isolated", "--days", "90"])
    main()
    assert "mode=dry-run" in capsys.readouterr().out
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert "SET TRANSACTION READ ONLY" in statements
    assert all("DELETE" not in sql for sql in statements)
    assert cursor.execute.call_args.args[1] == (now - timedelta(days=90),)
    connection.close.assert_called_once()


def test_delete_permission_is_checked_before_locking():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [("isolated", datetime.now(timezone.utc)), (False,)]
    with pytest.raises(RetentionRefused, match="DELETE permission"):
        run_retention(connection, RetentionPlan("isolated", apply=True, confirmation="isolated"), enabled=True)
    assert not any("pg_try_advisory_lock" in call.args[0] for call in cursor.execute.call_args_list)


def test_batch_limit_stops_and_releases_leadership():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [("isolated", datetime.now(timezone.utc)), (True,), (True,), (1,)]
    cursor.rowcount = 2
    outcome = run_retention(connection, RetentionPlan("isolated", batch_size=2, max_batches=1,
                            apply=True, confirmation="isolated"), enabled=True)
    assert (outcome["deleted"], outcome["batches"], outcome["batch_limit_reached"]) == (2, 1, True)
    writes = [call for call in cursor.execute.call_args_list if "DELETE FROM" in call.args[0]]
    assert len(writes) == 1
    assert "checked_at < %s" in writes[0].args[0] and writes[0].args[1][-1] == 2
    assert cursor.execute.call_args.args[0] == "SELECT pg_advisory_unlock(%s)"


def test_postgresql_retention_in_verified_synthetic_database():
    name = os.environ.get("TRACEGRID_RETENTION_TEST_DATABASE")
    if not name:
        pytest.skip("Isolated PostgreSQL retention fixture was not started.")
    assert re.fullmatch(r"tracegrid_retention_[a-f0-9]{32}", name)
    role = os.environ["USERNAME"]
    args = {"dbname": name, "host": "127.0.0.1", "port": 55439, "user": role}
    with closing(psycopg2.connect(**args)) as check, check, check.cursor() as cursor:
        cursor.execute("""SELECT current_database(), inet_server_port(), shobj_description(oid,'pg_database')
                       FROM pg_database WHERE datname=current_database()""")
        assert cursor.fetchone() == (name, 55439, f"TraceGrid retention test {name.rsplit('_', 1)[-1]}")
        cursor.execute("SELECT count(*) FROM monitoring_history")
        assert cursor.fetchone() == (0,)
    engine = create_engine(URL.create("postgresql+psycopg2", username=role, host="127.0.0.1", port=55439, database=name),
                           hide_parameters=True)
    try:
        now = datetime.now(timezone.utc)
        with Session(engine) as db, db.begin():
            owner = User(username="retention_fixture", email="retention-fixture@example.com", hashed_password="unused")
            other = User(username="retention_other", email="retention-other@example.com", hashed_password="unused")
            db.add_all([owner, other])
            db.flush()
            endpoint = APIEndpoint(user_id=owner.id, name="Retention fixture", url="https://example.invalid/", is_active=False)
            private = APIEndpoint(user_id=other.id, name="Private fixture", url="https://example.invalid/", is_active=False)
            db.add_all([endpoint, private])
            db.flush()
            owner_id, endpoint_id = owner.id, endpoint.id
            incident = Incident(owner_id=owner_id, endpoint_id=endpoint_id, endpoint_name=endpoint.name,
                                title="Fixture incident", status="open", severity="critical", failure_reason="http_error",
                                started_at=now, detected_at=now)
            db.add(incident)
            db.flush()
            db.add_all([IncidentNotification(incident_id=incident.id, kind="opened", created_at=now, available_at=now),
                        RevokedToken(token="synthetic-maintenance-fixture"), RateLimitCounter(key="r"*64, expires_at=9, hits=1)])
            old = []
            for offset in (3, 2):
                row = MonitoringHistory(endpoint_id=endpoint_id, checked_at=now - timedelta(days=offset),
                                        status="UP", response_time=5)
                db.add(row)
                old.append(row)
            db.add_all([MonitoringHistory(endpoint_id=endpoint_id, checked_at=now - timedelta(seconds=i),
                                          status=status, response_time=latency)
                        for i, status, latency in [(20, "UP", 20), (40, "DOWN", 60), (55, "ERROR", 800)]])
            db.add(MonitoringHistory(endpoint_id=private.id, checked_at=now, status="UP", response_time=1))
            db.flush()
            oldest = old[0].id

        plan = RetentionPlan(name, days=1, batch_size=1, apply=True, confirmation=name)
        with closing(psycopg2.connect(**args)) as maintenance:
            dry = run_retention(maintenance, RetentionPlan(name, days=1))
            assert (dry["eligible"], dry["deleted"]) == (2, 0)
            with closing(psycopg2.connect(**args)) as leader, leader, leader.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(%s)", (RETENTION_LOCK,))
                with pytest.raises(RetentionRefused, match="Another retention run"):
                    run_retention(maintenance, plan, enabled=True)
            with closing(psycopg2.connect(**args)) as locked, locked, locked.cursor() as cursor:
                cursor.execute("SELECT id FROM monitoring_history WHERE id=%s FOR UPDATE", (oldest,))
                def interrupt(_):
                    raise KeyboardInterrupt
                with pytest.raises(KeyboardInterrupt):
                    run_retention(maintenance, plan, enabled=True, pause=interrupt)
                assert run_retention(maintenance, RetentionPlan(name, days=1))["eligible"] == 1
            resumed = run_retention(maintenance, plan, enabled=True, pause=lambda _: None)
            assert resumed["deleted"] == resumed["batches"] == 1
            assert run_retention(maintenance, RetentionPlan(name, days=1))["eligible"] == 0
        with Session(engine) as db:
            for model, count in [(User, 2), (APIEndpoint, 2), (Incident, 1), (IncidentNotification, 1),
                                 (RevokedToken, 1), (RateLimitCounter, 1), (MonitoringHistory, 4)]:
                assert db.scalar(select(func.count()).select_from(model)) == count
            analytics = endpoint_report(db, db.get(APIEndpoint, endpoint_id), Window.from_range("7d"))
            assert analytics["uptime"] == 50 and analytics["latency"]["average"] == 40
            assert analytics["availability"]["monitoring_errors"] == 1
            user = db.get(User, owner_id)
            assert len(get_recent_activity(db, user)) == 3
            dashboard = get_dashboard_summary(db, user)
            assert dashboard["total_endpoints"] == 1 and dashboard["uptime_percentage"] == 50
            assert dashboard["average_response_time"] == 40
    finally:
        engine.dispose()
