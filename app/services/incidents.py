from sqlalchemy import select

from app.models.incident import Incident
from app.services.incident_notifications import queue_incident_email
from app.services.monitoring_events import stage_event


FAILURE_THRESHOLD = 3


def active_incident(db, endpoint_id):
    return db.scalar(select(Incident).where(
        Incident.endpoint_id == endpoint_id, Incident.resolved_at.is_(None),
    ).with_for_update())


def reset_streak(endpoint):
    endpoint.incident_failure_count = 0
    endpoint.incident_failure_since = None


def resolve_incident(incident, now, probe=None):
    incident.status = "resolved"
    incident.resolved_at = now
    incident.resolution = "manual" if probe is None else "recovered"
    if probe is not None:
        incident.recovery_http_status = probe["status_code"]
        incident.recovery_response_ms = probe["response_time"]


def observe_incident(db, endpoint, probe, now):
    """Track availability in the same transaction and under the same endpoint lock as the probe."""
    if endpoint.user_id is None or probe["status"] not in {"UP", "DOWN", "REDIRECT"}:
        return None
    if probe["status"] == "UP":
        reset_streak(endpoint)
        incident = active_incident(db, endpoint.id)
        if incident is not None:
            resolve_incident(incident, now, probe)
            queue_incident_email(db, endpoint, incident, "recovered", now)
            return incident, "resolved"
        return None

    if endpoint.incident_failure_count >= FAILURE_THRESHOLD:
        return None
    if not endpoint.incident_failure_count:
        endpoint.incident_failure_since = now
    endpoint.incident_failure_count += 1
    if endpoint.incident_failure_count < FAILURE_THRESHOLD or active_incident(db, endpoint.id) is not None:
        return None

    status_code = probe["status_code"]
    incident = Incident(
        owner_id=endpoint.user_id, endpoint_id=endpoint.id, endpoint_name=endpoint.name,
        title=f"{endpoint.name} availability incident", status="open",
        severity="critical" if status_code is None or status_code >= 500 else "warning",
        failure_reason=probe.get("reason") or ("redirect" if probe["status"] == "REDIRECT" else "availability_failure"),
        failure_http_status=status_code, started_at=endpoint.incident_failure_since, detected_at=now,
    )
    db.add(incident)
    queue_incident_email(db, endpoint, incident, "opened", now)
    return incident, "created"


def stage_incident_event(db, incident, action):
    db.flush()
    return stage_event(db, {
        "type": "incident.updated", "user_id": incident.owner_id, "incident_id": incident.id,
        "endpoint_id": incident.endpoint_id, "action": action,
    })
