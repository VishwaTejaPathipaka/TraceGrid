from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import APIEndpoint, MonitoringHistory, User
from app.services import scheduler


DUE = datetime(2026, 11, 23, tzinfo=timezone.utc)
RESULT = {"status": "UP", "status_code": 200, "response_time": 5.0}


@pytest.fixture
def schedule(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'schedule.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    clock = SimpleNamespace(now=DUE)
    monkeypatch.setattr(scheduler, "SessionLocal", factory)
    monkeypatch.setattr(scheduler, "_wall_time", lambda: clock.now)
    monkeypatch.setattr(scheduler, "check_api", Mock(return_value=RESULT))
    monkeypatch.setattr(scheduler, "sleep", lambda _: None)
    with factory.begin() as db:
        db.add(User(id=1, username="owner", email="owner@example.com", hashed_password="unused"))
        db.add_all([
            APIEndpoint(id=id_, name=f"Endpoint {id_}", url=f"https://example.com/{id_}",
                        next_check_at=DUE, user_id=1, is_active=(id_ < 5))
            for id_ in range(1, 6)
        ])
    yield engine, factory, clock
    engine.dispose()


def history(factory):
    with factory() as db:
        return list(db.scalars(select(MonitoringHistory).order_by(MonitoringHistory.id)))


def test_schedule_advances_30_seconds_and_ignores_inactive_endpoints(schedule):
    _, factory, clock = schedule
    for _ in range(5):
        scheduler.dispatch_due_check(0)
    assert [row.endpoint_id for row in history(factory)] == [1, 2, 3, 4]
    clock.now += timedelta(seconds=29)
    scheduler.dispatch_due_check(0)
    assert len(history(factory)) == 4
    clock.now += timedelta(seconds=1)
    scheduler.dispatch_due_check(0)
    assert scheduler._utc(history(factory)[-1].scheduled_for) == DUE + scheduler.INTERVAL
    with factory() as db:
        assert scheduler._utc(db.get(APIEndpoint, 1).next_check_at) == DUE + 2 * scheduler.INTERVAL
        assert scheduler._utc(db.get(APIEndpoint, 5).next_check_at) == DUE


def test_lateness_duration_and_missed_windows_are_persisted_without_replay(schedule, monkeypatch):
    _, factory, clock = schedule
    clock.now += timedelta(seconds=95)
    monotonic = Mock(side_effect=[10, 10.125])
    monkeypatch.setattr(scheduler, "monotonic", monotonic)
    scheduler.dispatch_due_check(0)

    row, = history(factory)
    assert scheduler._utc(row.scheduled_for) == DUE
    assert (row.schedule_lateness_ms, row.execution_duration_ms) == (95_000, 125)
    with factory() as db:
        endpoint = db.get(APIEndpoint, 1)
        assert scheduler._utc(endpoint.next_check_at) == DUE + timedelta(seconds=120)
        assert endpoint.last_schedule_missed_intervals == 3


def test_slow_probe_keeps_its_claim_and_other_slots_make_progress(schedule, monkeypatch):
    _, factory, _ = schedule
    started = Event()
    release = Event()
    calls = []
    mutex = Lock()

    def check(url, _):
        id_ = int(url.rsplit("/", 1)[1])
        with mutex:
            calls.append(id_)
        if id_ == 1:
            started.set()
            assert release.wait(5)
        return RESULT

    monkeypatch.setattr(scheduler, "check_api", check)
    with ThreadPoolExecutor(max_workers=4) as executor:
        slow = executor.submit(scheduler.dispatch_due_check, 0)
        try:
            assert started.wait(3)
            executor.submit(scheduler.dispatch_due_check, 0).result(timeout=2)
            for slot in (1, 2, 3):
                executor.submit(scheduler.dispatch_due_check, slot).result(timeout=2)
            assert [row.endpoint_id for row in history(factory)] == [2, 3, 4]
            assert calls == [1, 2, 3, 4]
        finally:
            release.set()
        slow.result(timeout=3)
    assert [row.endpoint_id for row in history(factory)] == [2, 3, 4, 1]


def test_abandoned_claim_recovers_after_restart_and_fences_old_result(schedule, monkeypatch):
    engine, factory, clock = schedule
    with engine.connect() as connection:
        old_job = scheduler._claim_due_check(connection)
    with factory.begin() as db:
        for id_ in (2, 3, 4):
            db.get(APIEndpoint, id_).is_active = False

    # A new engine has no in-memory state from the abandoned worker.
    restarted = create_engine(engine.url)
    monkeypatch.setattr(scheduler, "SessionLocal", sessionmaker(bind=restarted))
    try:
        scheduler.dispatch_due_check(0)
        assert history(factory) == []
        clock.now += scheduler.CLAIM_LEASE
        with restarted.connect() as connection:
            recovered = scheduler._claim_due_check(connection)
            assert recovered.claim_id != old_job.claim_id
            assert recovered.due_at == old_job.due_at
            assert scheduler._persist_result(connection, old_job, RESULT, None, 0, 0) is None
            assert history(factory) == []
            scheduler._run_check(connection, recovered)
        assert len(history(factory)) == 1
    finally:
        restarted.dispose()


@pytest.mark.parametrize("failures", [1, scheduler._WRITE_ATTEMPTS])
def test_write_failure_retries_and_only_publishes_after_commit(schedule, monkeypatch, caplog, failures):
    _, factory, clock = schedule
    failing = failures
    published = []

    def fail_history(db, *_):
        nonlocal failing
        if failing and any(isinstance(row, MonitoringHistory) for row in db.new):
            failing -= 1
            raise SQLAlchemyError("simulated write failure")

    def publish(event):
        if event is not None:
            assert len(history(factory)) == 1
            published.append(event)

    event.listen(factory, "before_flush", fail_history)
    monkeypatch.setattr(scheduler.websocket_manager, "publish_local", publish)
    scheduler.dispatch_due_check(0)

    if failures == scheduler._WRITE_ATTEMPTS:
        assert published == []
        assert history(factory) == []
        assert "remains due after claim recovery" in caplog.text
        with factory() as db:
            assert scheduler._utc(db.get(APIEndpoint, 1).next_check_at) == DUE
        clock.now += scheduler.CLAIM_LEASE
        scheduler.dispatch_due_check(0)

    assert published == [{"type": "monitoring.updated", "endpoint_id": 1, "user_id": 1}]
    assert len(history(factory)) == 1


def test_internal_worker_error_is_recorded_as_infrastructure(schedule, monkeypatch):
    _, factory, _ = schedule
    monkeypatch.setattr(scheduler, "check_api", Mock(side_effect=RuntimeError("worker failure")))
    scheduler.dispatch_due_check(0)
    assert [(row.status, row.reason) for row in history(factory)] == [("ERROR", "monitor_error")]


def test_apscheduler_registers_only_four_coalescing_slots(monkeypatch):
    runner = Mock()
    monkeypatch.setattr(scheduler, "scheduler", runner)
    monkeypatch.setattr(scheduler.settings, "SCHEDULED_PROBE_WORKERS", 4)
    scheduler.start_scheduler()

    assert [call.kwargs["args"] for call in runner.add_job.call_args_list] == [(0,), (1,), (2,), (3,)]
    assert all(call.kwargs["coalesce"] and call.kwargs["max_instances"] == 1 for call in runner.add_job.call_args_list)
    runner.start.assert_called_once()


def assert_postgres_slots_and_claims(engine, second_engine, monkeypatch):
    """Exercise independent database sessions, bypassing the per-process Python mutex."""
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(scheduler, "SessionLocal", factory)
    due = datetime.now(timezone.utc) - timedelta(days=31)
    with factory.begin() as db:
        db.add(APIEndpoint(name="Production probe", url="https://example.com", next_check_at=due))
    with scheduler._slot_connection(engine, 0) as first:
        job = scheduler._claim_due_check(first)
        assert job is not None
        assert not first.in_transaction()
        with scheduler._slot_connection(second_engine, 0) as duplicate:
            assert duplicate is None
        with scheduler._slot_connection(second_engine, 1) as other_slot:
            assert scheduler._claim_due_check(other_slot) is None
        # Even an expired durable claim cannot bypass a live PostgreSQL endpoint lock.
        with factory.begin() as db:
            db.get(APIEndpoint, job.endpoint_id).scheduled_lease_until = due
        with scheduler._slot_connection(second_engine, 1) as other_slot:
            assert scheduler._claim_due_check(other_slot) is None

    with scheduler._slot_connection(second_engine, 0) as recovered:
        replacement = scheduler._claim_due_check(recovered)
        assert replacement.claim_id != job.claim_id
        assert scheduler._persist_result(recovered, job, RESULT, None, 0, 0) is None
        scheduler._persist_result(recovered, replacement, RESULT, None, 2_678_400_000, 25)
    row, = history(factory)
    assert row.schedule_lateness_ms == 2_678_400_000
