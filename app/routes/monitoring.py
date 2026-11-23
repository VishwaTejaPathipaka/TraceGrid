from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import APIEndpoint, MonitoringHistory
from app.models.users import User
from app.security import get_current_user
from app.services.monitor import check_api
from app.services.connection_limits import manual_probe_slot
from app.services.monitoring_policy import MonitoringPolicyError
from app.services.advanced_analytics import availability_totals
from app.services.probe_history import record_probe, stage_probe_update
from app.services.rate_limits import limit_owner
from app.services.websocket_manager import websocket_manager
from app.schemas.monitor import HistoryEntry, MonitorResponse, RecentActivity
from app.schemas.analytics import AnalyticsResponse
from app.schemas.analytics import DashboardSummary


router = APIRouter()


@router.get("/{endpoint_id}/check", response_model=MonitorResponse)
def monitor_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    owner_id = current_user.id
    limit_owner(db, owner_id, "manual_check")
    endpoint = db.query(APIEndpoint).filter(
        APIEndpoint.id == endpoint_id,
        APIEndpoint.user_id == current_user.id
    ).first()

    if endpoint is None:
        raise HTTPException(
            status_code=404,
            detail="Endpoint not found"
        )

    endpoint_name, revision, url, method = endpoint.name, endpoint.configuration_revision, endpoint.url, endpoint.method
    engine = db.get_bind()
    db.rollback()
    try:
        with manual_probe_slot(engine, owner_id):
            result = check_api(url, method)
    except MonitoringPolicyError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    saved_endpoint, incident_change = record_probe(db, endpoint_id, revision, result=result)
    if saved_endpoint is None:
        raise HTTPException(status_code=409, detail="Endpoint changed during the check. Try again.")
    event = stage_probe_update(db, saved_endpoint, incident_change)
    db.commit()
    websocket_manager.publish_local(event)

    return {
        "endpoint_id": endpoint_id,
        "endpoint_name": endpoint_name,
        **result
    }
    
@router.get("/{endpoint_id}/history", response_model=list[HistoryEntry])
def get_monitoring_history(
    endpoint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
    before_id: Annotated[int | None, Query(gt=0)] = None,
):
    owner_id = current_user.id
    limit_owner(db, owner_id, "history")
    endpoint = db.query(APIEndpoint).filter(
        APIEndpoint.id == endpoint_id,
        APIEndpoint.user_id == current_user.id
    ).first()

    if endpoint is None:
        raise HTTPException(
            status_code=404,
            detail="Endpoint not found"
        )

    query = select(MonitoringHistory).where(MonitoringHistory.endpoint_id == endpoint_id)
    if before_id is not None:
        before = db.scalar(query.where(MonitoringHistory.id == before_id))
        if before is None:
            raise HTTPException(422, "Invalid monitoring history cursor.")
        if before.checked_at is None:
            query = query.where(MonitoringHistory.checked_at.is_(None), MonitoringHistory.id < before_id)
        else:
            query = query.where(or_(MonitoringHistory.checked_at.is_(None),
                                    MonitoringHistory.checked_at < before.checked_at,
                                    and_(MonitoringHistory.checked_at == before.checked_at,
                                         MonitoringHistory.id < before_id)))
    return db.scalars(query.order_by(MonitoringHistory.checked_at.desc().nulls_last(),
                                     MonitoringHistory.id.desc()).limit(limit)).all()


@router.get("/{endpoint_id}/analytics", response_model=AnalyticsResponse)
def get_endpoint_analytics(
    endpoint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    limit_owner(db, current_user.id, "analytics")
    endpoint = db.query(APIEndpoint).filter(
        APIEndpoint.id == endpoint_id,
        APIEndpoint.user_id == current_user.id
    ).first()

    if endpoint is None:
        raise HTTPException(
            status_code=404,
            detail="Endpoint not found"
        )

    row = db.execute(select(*availability_totals(MonitoringHistory.status, MonitoringHistory.response_time))
                     .where(MonitoringHistory.endpoint_id == endpoint_id)).one()
    total_checks = row.successful + row.unsuccessful
    uptime_percentage = (row.successful / total_checks) * 100 if total_checks else None

    return {
        "endpoint_id": endpoint_id,
        "total_checks": total_checks,
        "successful_checks": row.successful,
        "failed_checks": row.unsuccessful,
        "average_response_time": round(row.average or 0, 2),
        "uptime_percentage": round(uptime_percentage, 2) if uptime_percentage is not None else None
    }
    
    
    
@router.get("/dashboard/recent", response_model=list[RecentActivity])
def get_recent_activity(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if db.get_bind().dialect.name == "postgresql":
        # At most five candidates per owned endpoint can appear in the overall top five.
        latest = select(MonitoringHistory.id, MonitoringHistory.checked_at).where(
            MonitoringHistory.endpoint_id == APIEndpoint.id, MonitoringHistory.checked_at.is_not(None),
        ).order_by(MonitoringHistory.checked_at.desc(), MonitoringHistory.id.desc()).limit(5).correlate(APIEndpoint).lateral()
        recent = select(latest.c.id, APIEndpoint.name).select_from(APIEndpoint).join(latest, true()).where(
            APIEndpoint.user_id == current_user.id,
        ).order_by(latest.c.checked_at.desc(), latest.c.id.desc()).limit(5).subquery()
        query = select(MonitoringHistory, recent.c.name).join(recent, recent.c.id == MonitoringHistory.id).order_by(
            MonitoringHistory.checked_at.desc(), MonitoringHistory.id.desc(),
        )
    else:
        query = select(MonitoringHistory, APIEndpoint.name).join(
            APIEndpoint, APIEndpoint.id == MonitoringHistory.endpoint_id,
        ).where(APIEndpoint.user_id == current_user.id, MonitoringHistory.checked_at.is_not(None)).order_by(
            MonitoringHistory.checked_at.desc(), MonitoringHistory.id.desc(),
        ).limit(5)
    rows = db.execute(query)
    return [
        RecentActivity(**HistoryEntry.model_validate(check).model_dump(), endpoint_name=name)
        for check, name in rows
    ]


@router.get("/dashboard/summary", response_model=DashboardSummary)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    owner = current_user.id
    limit_owner(db, owner, "analytics")
    owned = select(APIEndpoint.id, APIEndpoint.is_active).where(APIEndpoint.user_id == owner).cte("owned_endpoints")
    endpoints = select(
        func.count().label("total_endpoints"),
        func.count().filter(owned.c.is_active.is_(True)).label("active_endpoints"),
    ).select_from(owned).subquery()
    checks = select(*availability_totals(MonitoringHistory.status, MonitoringHistory.response_time)).where(
        MonitoringHistory.endpoint_id.in_(select(owned.c.id)),
    ).subquery()
    row = db.execute(select(endpoints, checks).select_from(endpoints.join(checks, true()))).one()
    total_checks = row.successful + row.unsuccessful
    uptime_percentage = row.successful / total_checks * 100 if total_checks else None

    return {
        "total_endpoints": row.total_endpoints,
        "active_endpoints": row.active_endpoints,
        "total_checks": total_checks,
        "successful_checks": row.successful,
        "failed_checks": row.unsuccessful,
        "average_response_time": round(row.average or 0, 2),
        "latency_samples": row.latency_samples,
        "uptime_percentage": round(uptime_percentage, 2) if uptime_percentage is not None else None
    }
