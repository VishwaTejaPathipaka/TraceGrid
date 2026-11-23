from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from smtplib import SMTPDataError, SMTPRecipientsRefused
from threading import Event, Thread
from unittest.mock import Mock

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import APIEndpoint, Incident, IncidentNotification, User
from app.security import hash_password
from app.services.incident_email import safe_endpoint_origin, utc
from app.services.incident_notifications import (
    LEASE, MAX_AGE, MAX_ATTEMPTS, RETENTION, claim_notification, finish_notification,
    process_notification, prune_notifications, queue_incident_email,
)
from app.services.probe_history import record_probe
from conftest import fail_probe_commit, verify_test_account
from test_incidents import DOWN, ERROR, UP, action, items, probes
from test_websocket_monitoring import account, bearer, login


PATH = "/users/notification-preferences"
OPT_IN = {"incident_opened": True, "incident_recovered": True}


def database():
    return contextmanager(app.dependency_overrides[get_db])()


def jobs():
    with database() as db:
        return db.scalars(select(IncidentNotification).order_by(IncidentNotification.id)).all()


def opt_in(client, headers, **preferences):
    result = client.put(PATH, headers=headers, json=preferences or OPT_IN)
    assert result.status_code == 200


def test_preferences_validate_boolean_and_are_owner_only(client, probes):
    _, headers, _, _ = probes
    other = bearer(account(client, "other_preferences", endpoint=False))
    original = client.get(PATH, headers=headers).json()
    assert original == {"verified_email": "incident_owner@example.com", "incident_opened": False,
                        "incident_recovered": False}
    assert client.get(PATH).status_code in (401, 403)
    assert client.put(PATH, headers=headers, json={**OPT_IN, "verified_email": "third@example.com"}).status_code == 422
    assert client.put(PATH, headers=headers, json={**OPT_IN, "incident_opened": "true"}).status_code == 422
    opt_in(client, headers)
    assert client.get(PATH, headers=other).json() == {
        "verified_email": "other_preferences@example.com", "incident_opened": False, "incident_recovered": False,
    }
    opt_in(client, other, incident_opened=False, incident_recovered=True)
    assert client.get(PATH, headers=headers).json() == {**original, **OPT_IN}


def test_grandfathered_sign_in_is_not_verified_delivery_consent(client):
    name = "legacy_notification"
    email = f"{name}@example.com"
    with database() as db:
        db.add(User(username=name, email=email, email_key=email, hashed_password=hash_password("TestPass@123")))
        db.commit()
    headers = bearer(login(client, name))
    assert client.get(PATH, headers=headers).json()["verified_email"] is None
    assert client.put(PATH, headers=headers, json=OPT_IN).status_code == 409
    assert client.post("/users/resend-verification", json={"email": email}).status_code == 202
    verify_test_account(client, email)
    assert client.get(PATH, headers=headers).json()["verified_email"] == email
    opt_in(client, headers)


def test_threshold_recovery_and_excluded_transitions(client, probes):
    _, headers, endpoint_id, run = probes
    opt_in(client, headers)
    run(ERROR, DOWN, DOWN)
    with database() as db:
        endpoint = db.get(APIEndpoint, endpoint_id)
        record_probe(db, endpoint_id, endpoint.configuration_revision, configuration_error="Blocked target")
        db.commit()
    assert jobs() == []
    run(DOWN, DOWN, ERROR)
    assert [job.kind for job in jobs()] == ["opened"]
    incident, = items(client, headers)
    assert action(client, headers, incident, "acknowledge").status_code == 200
    assert [job.kind for job in jobs()] == ["opened"]
    assert action(client, headers, incident, "resolve").status_code == 200
    run(UP)
    assert [job.kind for job in jobs()] == ["opened"]
    run(DOWN, DOWN, DOWN, UP, UP)
    first, second, recovery = jobs()
    assert [first.kind, second.kind, recovery.kind] == ["opened", "opened", "recovered"]
    assert second.incident_id == recovery.incident_id
    assert all(job.state == "pending" for job in (first, second, recovery))


def test_preferences_suppress_jobs_and_recheck_pending_delivery(client, probes):
    _, headers, _, run = probes
    run(DOWN, DOWN, DOWN, UP)
    assert jobs() == []
    opt_in(client, headers, incident_opened=False, incident_recovered=True)
    run(DOWN, DOWN, DOWN, UP)
    queued, = jobs()
    assert queued.kind == "recovered"
    opt_in(client, headers, incident_opened=True, incident_recovered=False)
    deliver = Mock()
    with database() as db, db.get_bind().connect() as conn:
        assert process_notification(conn, deliver)
    deliver.assert_not_called()
    failed, = jobs()
    assert (failed.state, failed.last_error) == ("failed", "recipient_ineligible")
    run(DOWN, DOWN, DOWN, UP)
    assert [job.kind for job in jobs()] == ["recovered", "opened"]


def test_unverified_owner_cannot_queue_even_with_stale_preferences(client, probes):
    _, headers, _, run = probes
    opt_in(client, headers)
    with database() as db:
        owner = db.scalar(select(User).where(User.username == "incident_owner"))
        owner.email_verified_at = None
        db.commit()
    run(DOWN, DOWN, DOWN, UP)
    assert jobs() == []


def test_email_and_incident_roll_back_together(client, probes, monkeypatch):
    _, headers, endpoint_id, run = probes
    opt_in(client, headers)
    run(DOWN, DOWN)
    with monkeypatch.context() as patch:
        fail_probe_commit(patch)
        assert client.get(f"/monitor/{endpoint_id}/check", headers=headers).status_code == 503
    assert items(client, headers) == [] and jobs() == []
    run(DOWN)
    assert len(jobs()) == 1


def test_real_development_outbox_escapes_markup_and_removes_url_secrets(client, probes):
    _, headers, endpoint_id, run = probes
    opt_in(client, headers)
    with database() as db:
        endpoint = db.get(APIEndpoint, endpoint_id)
        endpoint.name = '<script>alert("unsafe")</script>\r\nBcc: hidden'
        endpoint.url = "https://user:credential@example.com:8443/private-key?token=private#secret"
        db.commit()
    before = set(settings.EMAIL_OUTBOX_DIR.glob("*.eml"))
    run(DOWN, DOWN, DOWN, UP)
    with database() as db, db.get_bind().connect() as conn:
        assert process_notification(conn)
        assert process_notification(conn)
        assert not process_notification(conn)
    paths = set(settings.EMAIL_OUTBOX_DIR.glob("*.eml")) - before
    assert len(paths) == 2 and all(job.state == "sent" for job in jobs())
    for path in paths:
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        assert message["To"] == "incident_owner@example.com" and message["Bcc"] is None
        html = message.get_body(preferencelist=("html",)).get_content()
        plain = message.get_body(preferencelist=("plain",)).get_content()
        assert "&lt;script&gt;" in html and "<script>" not in html
        for secret in ("credential", "private-key", "token=", "#secret"):
            assert secret not in plain and secret not in html
        assert "https://example.com:8443" in plain and "incidents?incident=" in plain
        assert "Unsuccessful HTTP response" in plain and "503" in plain
        if "recovered" in message["Subject"]:
            assert "Recovery HTTP status: 204" in plain and "Duration:" in plain
    assert safe_endpoint_origin("javascript:alert(1)") is None


def test_transient_failures_back_off_and_permanent_failures_stop(client, probes):
    _, headers, _, run = probes
    opt_in(client, headers)
    run(DOWN, DOWN, DOWN, UP)
    opened, recovered = jobs()
    now = utc(opened.available_at)
    delivered = Mock(side_effect=SMTPDataError(421, b"test temporary"))
    with database() as db, db.get_bind().connect() as conn:
        with Session(conn) as worker_db, worker_db.begin():
            worker_db.get(IncidentNotification, recovered.id).available_at = now + timedelta(hours=1)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            assert process_notification(conn, delivered, lambda: now)
            with Session(conn) as check:
                job = check.get(IncidentNotification, opened.id)
                assert job.attempts == attempt
                if attempt < MAX_ATTEMPTS:
                    assert job.state == "retrying"
                    assert utc(job.available_at) - now == timedelta(seconds=30 * 2 ** (attempt - 1))
                    next_attempt = utc(job.available_at)
                else:
                    assert job.state == "failed" and job.completed_at is not None
            assert not process_notification(conn, delivered, lambda: now)
            if attempt < MAX_ATTEMPTS:
                now = next_attempt
        rejected = Mock(side_effect=SMTPRecipientsRefused({"fixture@example.com": (550, b"test rejection")}))
        assert process_notification(conn, rejected, lambda: now + timedelta(hours=1))
        with Session(conn) as check:
            job = check.get(IncidentNotification, recovered.id)
            assert (job.state, job.attempts, job.last_error) == ("failed", 1, "recipient_rejected")


def test_abandoned_lease_restart_and_stale_claim_fencing(client, probes):
    _, headers, _, run = probes
    opt_in(client, headers)
    run(DOWN, DOWN, DOWN)
    queued, = jobs()
    now = utc(queued.available_at)
    with database() as db:
        original = claim_notification(db, now)
        db.commit()
    with database() as restarted:
        assert claim_notification(restarted, now + LEASE - timedelta(seconds=1)) is None
        takeover = claim_notification(restarted, now + LEASE)
        assert takeover.job_id == original.job_id and takeover.token != original.token
        restarted.commit()
    with database() as db:
        finish_notification(db, original, now + LEASE)
        assert db.get(IncidentNotification, queued.id).state == "processing"
        finish_notification(db, takeover, now + LEASE)
        db.commit()
    assert jobs()[0].state == "sent"


def test_expiry_and_retention_preserve_logical_deduplication(client, probes):
    _, headers, endpoint_id, run = probes
    opt_in(client, headers)
    run(DOWN, DOWN, DOWN)
    queued, = jobs()
    now = utc(queued.created_at) + MAX_AGE + timedelta(seconds=1)
    deliver = Mock()
    with database() as db, db.get_bind().connect() as conn:
        assert process_notification(conn, deliver, lambda: now)
        assert prune_notifications(conn, now + RETENTION + timedelta(seconds=1)) == 1
    deliver.assert_not_called()
    assert jobs() == []
    with database() as db:
        queue_incident_email(db, db.get(APIEndpoint, endpoint_id), db.get(Incident, queued.incident_id), "opened", now)
        db.commit()
    assert jobs() == []


def test_slow_email_does_not_hold_probe_transaction(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'notification-delay.sqlite3'}")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as db, db.begin():
        owner = User(username="slow", email="slow@example.com", hashed_password="unused",
                     email_verified_at=now, notify_incident_opened=True, notify_incident_recovered=True)
        db.add(owner)
        db.flush()
        endpoint = APIEndpoint(name="Slow relay fixture", url="https://example.com/", user_id=owner.id)
        db.add(endpoint)
        db.flush()
        endpoint_id = endpoint.id
    for _ in range(3):
        with Session(engine) as db, db.begin():
            record_probe(db, endpoint_id, 0, result=DOWN)
    sending = Event()
    release = Event()
    sent = Event()

    def paused(_):
        sending.set()
        assert release.wait(5)

    def worker():
        with engine.connect() as connection:
            if process_notification(connection, paused):
                sent.set()

    thread = Thread(target=worker)
    thread.start()
    try:
        assert sending.wait(5)
        with Session(engine) as db, db.begin():
            record_probe(db, endpoint_id, 0, result=UP)
        with Session(engine) as db:
            assert [row.state for row in db.scalars(select(IncidentNotification).order_by(IncidentNotification.id))] == [
                "processing", "pending",
            ]
    finally:
        release.set()
        thread.join(5)
        engine.dispose()
    assert sent.is_set()
