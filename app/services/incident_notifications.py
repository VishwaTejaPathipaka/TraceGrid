from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import smtplib
import ssl
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy import and_, delete, or_, select, text
from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.models.incident_notification import IncidentNotification
from app.models.users import User
from app.services.account_email import send_email
from app.services.incident_email import incident_message, safe_endpoint_origin, utc


MAX_ATTEMPTS = 5
LEASE = timedelta(minutes=3)
MAX_AGE = timedelta(days=1)
RETENTION = timedelta(days=30)
IDLE_SECONDS = 5
STANDBY_SECONDS = 30
WORKER_LOCK = 1414679118
logger = logging.getLogger(__name__)


def eligible_recipient(kind):
    preference = User.notify_incident_opened if kind == "opened" else User.notify_incident_recovered
    return and_(User.email_verified_at.is_not(None), User.email_verification_required.is_(False), preference.is_(True))


def queue_incident_email(db, endpoint, incident, kind, now):
    marker = "opened_email_queued" if kind == "opened" else "recovery_email_queued"
    if getattr(incident, marker):
        return
    owner = db.scalar(select(User.id).where(User.id == incident.owner_id, eligible_recipient(kind)))
    if owner is None or endpoint.user_id != owner:
        return
    # The probe writer holds the endpoint/incident lock. Keep the marker after outbox retention.
    if incident.id is None:
        db.flush()
    setattr(incident, marker, True)
    db.add(IncidentNotification(incident_id=incident.id, kind=kind,
                                endpoint_origin=safe_endpoint_origin(endpoint.url), created_at=now, available_at=now))


@dataclass(frozen=True)
class Claim:
    job_id: int
    token: str | None


def claim_notification(db, now):
    job = db.scalar(select(IncidentNotification).where(or_(
        and_(IncidentNotification.state.in_(("pending", "retrying")), IncidentNotification.available_at <= now),
        and_(IncidentNotification.state == "processing", IncidentNotification.lease_until <= now),
    )).order_by(IncidentNotification.available_at, IncidentNotification.id).limit(1).with_for_update(skip_locked=True))
    if job is None:
        return None
    if job.attempts >= MAX_ATTEMPTS or now >= utc(job.created_at) + MAX_AGE:
        job.state = "failed"
        job.completed_at = now
        job.last_error = "attempts_exhausted" if job.attempts >= MAX_ATTEMPTS else "expired"
        job.claim_id = job.lease_until = None
        return Claim(job.id, None)
    job.state = "processing"
    job.attempts += 1
    job.claim_id = uuid4().hex
    job.lease_until = now + LEASE
    return Claim(job.id, job.claim_id)


def claimed_job(claim):
    return (
        IncidentNotification.id == claim.job_id,
        IncidentNotification.state == "processing",
        IncidentNotification.claim_id == claim.token,
    )


def failure_type(error):
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        responses = error.recipients.values()
        transient = any(400 <= code < 500 for code, _ in responses)
        return ("smtp_temporary", True) if transient else ("recipient_rejected", False)
    if isinstance(error, smtplib.SMTPResponseException):
        return ("smtp_temporary", True) if 400 <= error.smtp_code < 500 else ("smtp_rejected", False)
    if isinstance(error, (ssl.SSLCertVerificationError, smtplib.SMTPNotSupportedError, ValueError)):
        return "delivery_configuration", False
    return "transport_unavailable", True


def finish_notification(db, claim, now, *, error=None, transient=False):
    job = db.scalar(select(IncidentNotification).where(*claimed_job(claim)).with_for_update())
    if job is None:
        return
    job.claim_id = job.lease_until = None
    job.last_error = error
    if error is None:
        job.state = "sent"
    elif transient and job.attempts < MAX_ATTEMPTS and now < utc(job.created_at) + MAX_AGE:
        job.state = "retrying"
        delay = timedelta(seconds=min(900, 30 * 2 ** (job.attempts - 1)))
        job.available_at = min(now + delay, utc(job.created_at) + MAX_AGE)
        return
    else:
        job.state = "failed"
    job.completed_at = now


def _now():
    return datetime.now(timezone.utc)


def process_notification(connection, deliver=send_email, clock=_now):
    with Session(connection) as db, db.begin():
        claim = claim_notification(db, clock())
    if claim is None:
        return False
    if claim.token is None:
        return True

    message = None
    error, transient = None, False
    with Session(connection) as db, db.begin():
        data = db.execute(select(IncidentNotification, Incident, User.email)
                          .join(Incident, Incident.id == IncidentNotification.incident_id)
                          .join(User, User.id == Incident.owner_id)
                          .where(*claimed_job(claim), or_(
                              and_(IncidentNotification.kind == "opened", eligible_recipient("opened")),
                              and_(IncidentNotification.kind == "recovered", eligible_recipient("recovered")),
                          ))).one_or_none()
        if data is not None:
            try:
                message = incident_message(*data)
            except ValueError:
                error = "message_invalid"
    if message is None:
        error = error or "recipient_ineligible"
    else:
        try:
            # This connection holds only the election lock. SMTP runs outside any database transaction.
            deliver(message)
        except (OSError, smtplib.SMTPException, ValueError) as exc:
            error, transient = failure_type(exc)
    with Session(connection) as db, db.begin():
        finish_notification(db, claim, clock(), error=error, transient=transient)
    return True


def prune_notifications(connection, now):
    with Session(connection) as db, db.begin():
        expired = select(IncidentNotification.id).where(
            IncidentNotification.completed_at < now - RETENTION,
        ).order_by(IncidentNotification.completed_at).limit(1000)
        return db.execute(delete(IncidentNotification).where(IncidentNotification.id.in_(expired))).rowcount


class IncidentNotificationWorker:
    def __init__(self, engine):
        self.engine = engine
        self.stopping = Event()
        self.thread = Thread(target=self.run, name="tracegrid-incident-email", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.thread.join(timeout=15)

    def run(self):
        while not self.stopping.is_set():
            try:
                with self.engine.connect() as connection:
                    # Detach so standby and active workers do not hold application pool slots.
                    connection.detach()
                    with connection.begin():
                        elected = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": WORKER_LOCK})
                    if elected:
                        self.deliver_pending(connection)
            except Exception:
                logger.warning("Incident notification worker paused and will retry")
            self.stopping.wait(STANDBY_SECONDS)

    def deliver_pending(self, connection):
        prune_at = _now()
        while not self.stopping.is_set():
            now = _now()
            if now >= prune_at:
                count = prune_notifications(connection, now)
                prune_at = now + (timedelta(seconds=IDLE_SECONDS) if count == 1000 else timedelta(hours=1))
            if not process_notification(connection):
                self.stopping.wait(IDLE_SECONDS)
