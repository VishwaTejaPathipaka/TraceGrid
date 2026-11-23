from datetime import datetime, timezone

from sqlalchemy import select

from app.models import APIEndpoint, MonitoringHistory
from app.services.incidents import observe_incident, stage_incident_event
from app.services.monitoring_events import stage_monitoring_update


AVAILABILITY_STATUSES = ("UP", "DOWN", "REDIRECT")


def record_probe(db, endpoint_id, revision, *, result=None, configuration_error=None,
                 claim_id=None, scheduled_for=None, schedule_lateness_ms=None, execution_duration_ms=None):
    query = select(APIEndpoint).where(
        APIEndpoint.id == endpoint_id, APIEndpoint.configuration_revision == revision,
    )
    if claim_id is not None:
        query = query.where(APIEndpoint.scheduled_claim_id == claim_id, APIEndpoint.is_active.is_(True))
    endpoint = db.scalar(query.with_for_update().execution_options(populate_existing=True))
    if endpoint is None:
        return None, None
    if configuration_error is not None:
        endpoint.configuration_error = configuration_error
        return endpoint, None

    checked_at = datetime.now(timezone.utc)
    if result["status"] == "UP":
        endpoint.configuration_error = None
    db.add(MonitoringHistory(
        endpoint_id=endpoint_id,
        status=result["status"],
        status_code=result["status_code"],
        response_time=result["response_time"],
        reason=result.get("reason"),
        scheduled_for=scheduled_for,
        schedule_lateness_ms=schedule_lateness_ms,
        execution_duration_ms=execution_duration_ms,
        checked_at=checked_at,
    ))
    return endpoint, observe_incident(db, endpoint, result, checked_at)


def stage_probe_update(db, endpoint, change):
    if change is not None:
        return stage_incident_event(db, *change)
    return stage_monitoring_update(db, endpoint)
