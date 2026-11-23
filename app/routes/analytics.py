from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import APIEndpoint, User
from app.schemas.advanced_analytics import AnalyticsRange, AnalyticsReport, ComparisonMetric, TimelineChecks
from app.security import get_current_user
from app.services.advanced_analytics import Window, comparison_report, endpoint_report, exact_bucket, incident_report
from app.services.rate_limits import limit_owner


router = APIRouter()
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
SelectedRange = Annotated[AnalyticsRange, Query(alias="range")]


def owned_endpoint(db, owner, endpoint_id):
    endpoint = db.scalar(select(APIEndpoint).where(APIEndpoint.id == endpoint_id, APIEndpoint.user_id == owner))
    if endpoint is None:
        raise HTTPException(404, "Endpoint not found.")
    return endpoint


@router.get("/report", response_model=AnalyticsReport)
def report(
    db: Database,
    user: CurrentUser,
    window_range: SelectedRange = "24h",
    endpoint_id: Annotated[int | None, Query(gt=0)] = None,
    compare: bool = True,
    metric: ComparisonMetric = "uptime",
    descending: bool = True,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
):
    limit_owner(db, user.id, "analytics")
    window = Window.from_range(window_range)
    endpoint = owned_endpoint(db, user.id, endpoint_id) if endpoint_id is not None else None
    return {
        "window": window,
        "endpoint": endpoint_report(db, endpoint, window) if endpoint is not None else None,
        "comparison": comparison_report(db, user.id, window, metric, offset, descending) if compare else None,
        "incidents": incident_report(db, user.id, window, endpoint_id),
    }


@router.get("/endpoints/{endpoint_id}/checks", response_model=TimelineChecks)
def bucket_checks(
    db: Database,
    user: CurrentUser,
    endpoint_id: int,
    end: AwareDatetime,
    bucket: Annotated[int, Query(ge=0, lt=72)],
    window_range: SelectedRange = "24h",
    after_at: AwareDatetime | None = None,
    after_id: Annotated[int | None, Query(gt=0)] = None,
):
    limit_owner(db, user.id, "analytics")
    owned_endpoint(db, user.id, endpoint_id)
    now = datetime.now(timezone.utc)
    if not now - timedelta(days=8) <= end <= now + timedelta(seconds=2):
        raise HTTPException(422, "Refresh analytics before inspecting this time window.")
    window = Window.from_range(window_range, end)
    if bucket >= window.bucket_count or (after_at is None) != (after_id is None):
        raise HTTPException(422, "Invalid bucket or check cursor.")
    start, finish = window.bucket_bounds(bucket)
    if after_at is not None and not start <= after_at < finish:
        raise HTTPException(422, "Check cursor is outside the selected bucket.")
    return exact_bucket(db, endpoint_id, window, bucket, after_at, after_id)
