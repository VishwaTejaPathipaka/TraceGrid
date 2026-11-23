from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from threading import Lock
from time import monotonic, sleep
from uuid import uuid4

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.database import SessionLocal
from app.models import APIEndpoint
from app.services.monitor import check_api
from app.services.monitoring_policy import MonitoringPolicyError
from app.services.probe_history import record_probe, stage_probe_update
from app.services.websocket_manager import websocket_manager


logger = logging.getLogger(__name__)
INTERVAL = timedelta(seconds=30)
CLAIM_LEASE = timedelta(seconds=45)
DISPATCH_POLL_SECONDS = 1
_SLOT_LOCK_NAMESPACE = 1414678355
_ENDPOINT_LOCK_NAMESPACE = 1414678341
_OWNER_LOCK_NAMESPACE = 1414679250
_LOCAL_SLOTS = tuple(Lock() for _ in range(32))
_WRITE_ATTEMPTS = 3


@dataclass(frozen=True)
class ScheduledCheck:
    endpoint_id: int
    revision: int
    url: str
    method: str
    due_at: datetime
    claim_id: str


def _utc(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _wall_time():
    return datetime.now(timezone.utc)


def _database_time(db):
    if db.get_bind().dialect.name == "postgresql":
        return db.scalar(select(func.clock_timestamp()))
    return _wall_time()


def _try_advisory_lock(executor, namespace, key):
    return executor.scalar(text("SELECT pg_try_advisory_lock(:namespace, :key)"), {
        "namespace": namespace, "key": key,
    })


@contextmanager
def _slot_connection(engine, slot):
    with engine.connect() as connection:
        if engine.dialect.name != "postgresql":
            yield connection
            return

        acquired = False
        try:
            with connection.begin():
                acquired = _try_advisory_lock(connection, _SLOT_LOCK_NAMESPACE, slot)
            yield connection if acquired else None
        finally:
            if acquired and not connection.invalidated:
                try:
                    # These are scheduler-owned locks on this checked-out connection.
                    with connection.begin():
                        connection.execute(text("SELECT pg_advisory_unlock_all()"))
                except SQLAlchemyError:
                    # Never give a connection with a possibly held lock back to the pool.
                    connection.invalidate()
                    logger.warning("Could not release the scheduled probe advisory locks")


def _set_transaction_limits(db):
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
        db.execute(text("SET LOCAL statement_timeout = '5s'"))


def _claim_due_check(connection):
    postgres = connection.dialect.name == "postgresql"
    with SessionLocal(bind=connection) as db, db.begin():
        _set_transaction_limits(db)
        now = _database_time(db)
        candidates = (
            select(APIEndpoint)
            .where(
                APIEndpoint.is_active.is_(True), APIEndpoint.next_check_at <= now,
                or_(APIEndpoint.scheduled_lease_until.is_(None), APIEndpoint.scheduled_lease_until <= now),
            )
            .order_by(APIEndpoint.next_check_at, APIEndpoint.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        skipped = []
        saturated_owners = []
        for _ in range(2 * settings.SCHEDULED_PROBE_WORKERS + 1):
            remaining = candidates
            if skipped:
                remaining = remaining.where(APIEndpoint.id.not_in(skipped))
            if saturated_owners:
                remaining = remaining.where(or_(APIEndpoint.user_id.is_(None),
                                                APIEndpoint.user_id.not_in(saturated_owners)))
            endpoint = db.scalar(remaining)
            if endpoint is None:
                return None
            if postgres and not _try_advisory_lock(db, _ENDPOINT_LOCK_NAMESPACE, endpoint.id):
                skipped.append(endpoint.id)
                continue
            if postgres and endpoint.user_id is not None and not any(
                _try_advisory_lock(db, _OWNER_LOCK_NAMESPACE + slot, endpoint.user_id)
                for slot in range(min(settings.SCHEDULED_PROBES_PER_OWNER, settings.SCHEDULED_PROBE_WORKERS))
            ):
                db.execute(text("SELECT pg_advisory_unlock(:namespace, :key)"),
                           {"namespace": _ENDPOINT_LOCK_NAMESPACE, "key": endpoint.id})
                saturated_owners.append(endpoint.user_id)
                continue

            # The due time stays put until the result commits. A dead worker's claim expires.
            claim_id = uuid4().hex
            endpoint.scheduled_claim_id = claim_id
            endpoint.scheduled_lease_until = now + CLAIM_LEASE
            return ScheduledCheck(endpoint.id, endpoint.configuration_revision, endpoint.url,
                                  endpoint.method, _utc(endpoint.next_check_at), claim_id)
    return None


def _next_due_time(due_at, finished_at):
    intervals = max(1, (finished_at - due_at) // INTERVAL + 1)
    return due_at + intervals * INTERVAL, intervals - 1


def _persist_result(connection, job, result, configuration_error, lateness_ms, duration_ms):
    with SessionLocal(bind=connection) as db, db.begin():
        _set_transaction_limits(db)
        endpoint, incident_change = record_probe(
            db, job.endpoint_id, job.revision, result=result, configuration_error=configuration_error,
            claim_id=job.claim_id, scheduled_for=job.due_at, schedule_lateness_ms=lateness_ms,
            execution_duration_ms=duration_ms,
        )
        if endpoint is None:
            # An edit can invalidate a probe. Only release our own claim, leaving the slot due.
            db.execute(update(APIEndpoint).where(
                APIEndpoint.id == job.endpoint_id, APIEndpoint.scheduled_claim_id == job.claim_id,
            ).values(scheduled_claim_id=None, scheduled_lease_until=None))
            return None

        endpoint.next_check_at, missed = _next_due_time(job.due_at, _database_time(db))
        endpoint.scheduled_claim_id = None
        endpoint.scheduled_lease_until = None
        endpoint.last_schedule_lateness_ms = lateness_ms
        endpoint.last_schedule_duration_ms = duration_ms
        endpoint.last_schedule_missed_intervals = missed
        return stage_probe_update(db, endpoint, incident_change)


def _store_result(connection, job, result, configuration_error, lateness_ms, duration_ms):
    for attempt in range(_WRITE_ATTEMPTS):
        try:
            notification = _persist_result(connection, job, result, configuration_error, lateness_ms, duration_ms)
        except SQLAlchemyError:
            if connection.invalidated or attempt == _WRITE_ATTEMPTS - 1:
                logger.warning("Scheduled result for endpoint %s remains due after claim recovery", job.endpoint_id)
                return
            sleep(0.1 * (attempt + 1))
        else:
            websocket_manager.publish_local(notification)
            return


def _run_check(connection, job):
    lateness_ms = max(0, round((_wall_time() - job.due_at).total_seconds() * 1000))
    started = monotonic()
    configuration_error = None
    try:
        result = check_api(job.url, job.method)
    except MonitoringPolicyError as error:
        configuration_error = str(error)
        result = None
        logger.warning("Monitoring configuration error for endpoint %s: %s", job.endpoint_id, error)
    except Exception:
        logger.warning("Scheduled probe failed internally for endpoint %s", job.endpoint_id)
        result = {"status": "ERROR", "status_code": None, "reason": "monitor_error",
                  "response_time": (monotonic() - started) * 1000}
    duration_ms = round((monotonic() - started) * 1000)
    _store_result(connection, job, result, configuration_error, lateness_ms, duration_ms)


def dispatch_due_check(slot):
    if not 0 <= slot < settings.SCHEDULED_PROBE_WORKERS:
        return
    lock = _LOCAL_SLOTS[slot]
    if not lock.acquire(blocking=False):
        return
    try:
        with SessionLocal() as db:
            engine = db.get_bind()
        with _slot_connection(engine, slot) as connection:
            if connection is not None:
                job = _claim_due_check(connection)
                if job is not None:
                    _run_check(connection, job)
    except SQLAlchemyError:
        logger.warning("Could not dispatch a scheduled probe in slot %s", slot)
    finally:
        lock.release()


scheduler = BackgroundScheduler()


def start_scheduler():
    workers = settings.SCHEDULED_PROBE_WORKERS
    scheduler.configure(executors={"default": ThreadPoolExecutor(workers)})
    for slot in range(workers):
        scheduler.add_job(
            dispatch_due_check, "interval", seconds=DISPATCH_POLL_SECONDS, args=(slot,),
            id=f"scheduled_probe_slot_{slot}", replace_existing=True, max_instances=1, coalesce=True,
            next_run_time=_wall_time(),
        )
    scheduler.start()
