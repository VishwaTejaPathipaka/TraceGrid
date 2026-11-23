from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import APIEndpoint, Incident, User
from app.schemas.incident import IncidentPage, IncidentResponse, IncidentStatus, IncidentSummary
from app.security import get_current_user
from app.services.incidents import reset_streak, resolve_incident, stage_incident_event
from app.services.websocket_manager import websocket_manager


router = APIRouter()


@router.get("/", response_model=IncidentPage)
def list_incidents(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    status: IncidentStatus | None = None,
    endpoint_id: Annotated[int | None, Query(gt=0)] = None,
    incident_id: Annotated[int | None, Query(gt=0)] = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    if from_date and to_date and from_date > to_date:
        raise HTTPException(422, "Start date must be on or before end date.")
    filters = [Incident.owner_id == user.id]
    if status is not None:
        filters.append(Incident.status == status)
    if endpoint_id is not None:
        filters.append(Incident.endpoint_id == endpoint_id)
    if incident_id is not None:
        filters.append(Incident.id == incident_id)
    if from_date is not None:
        filters.append(Incident.started_at >= datetime.combine(from_date, time.min, timezone.utc))
    if to_date is not None:
        filters.append(Incident.started_at <= datetime.combine(to_date, time.max, timezone.utc))
    total = db.scalar(select(func.count()).select_from(Incident).where(*filters))
    items = db.scalars(select(Incident).where(*filters).order_by(
        Incident.started_at.desc(), Incident.id.desc(),
    ).offset(offset).limit(limit)).all()
    return {"total": total, "items": items}


@router.get("/summary", response_model=IncidentSummary)
def incident_summary(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    owned = Incident.owner_id == user.id
    unresolved = Incident.resolved_at.is_(None)
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    active_count, affected = db.execute(select(func.count(Incident.id), func.count(
        distinct(Incident.endpoint_id),
    )).where(owned, unresolved)).one()
    active = db.scalars(select(Incident).where(owned, unresolved).order_by(
        Incident.started_at.desc(), Incident.id.desc(),
    ).limit(5)).all()
    recent = db.scalars(select(Incident).where(owned, Incident.resolved_at >= recent_cutoff).order_by(
        Incident.resolved_at.desc(), Incident.id.desc(),
    ).limit(5)).all()
    return {"active_count": active_count, "affected_endpoints": affected, "active": active,
            "recently_resolved": recent}


@router.post("/{incident_id}/{action}", response_model=IncidentResponse)
def change_incident(
    incident_id: int,
    action: Literal["acknowledge", "resolve"],
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    query = select(Incident).where(Incident.id == incident_id, Incident.owner_id == user.id)
    incident = db.scalar(query)
    if incident is None:
        raise HTTPException(404, "Incident not found.")
    endpoint = None
    if action == "resolve" and incident.endpoint_id is not None:
        # Match the probe writer's lock order so recovery and manual resolution serialize.
        endpoint = db.scalar(select(APIEndpoint).where(
            APIEndpoint.id == incident.endpoint_id, APIEndpoint.user_id == user.id,
        ).with_for_update())
    incident = db.scalar(query.with_for_update().execution_options(populate_existing=True))
    if incident is None:
        raise HTTPException(404, "Incident not found.")
    now = datetime.now(timezone.utc)
    if action == "acknowledge":
        if incident.status == "resolved":
            raise HTTPException(409, "This incident is already resolved.")
        if incident.status == "acknowledged":
            return incident
        incident.status = "acknowledged"
        incident.acknowledged_at = now
        event = stage_incident_event(db, incident, "acknowledged")
    else:
        if incident.status == "resolved":
            return incident
        resolve_incident(incident, now)
        if endpoint is not None:
            reset_streak(endpoint)
        event = stage_incident_event(db, incident, "resolved")
    response = IncidentResponse.model_validate(incident)
    db.commit()
    websocket_manager.publish_local(event)
    return response
