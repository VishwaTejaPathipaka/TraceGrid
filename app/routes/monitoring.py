from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import APIEndpoint, MonitoringHistory
from app.models.users import User
from app.security import get_current_user
from app.services.monitor import check_api
from app.schemas.monitor import MonitorResponse
from app.schemas.analytics import AnalyticsResponse
from app.schemas.analytics import DashboardSummary


router = APIRouter()


@router.get("/{endpoint_id}/check", response_model=MonitorResponse)
def monitor_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    endpoint = db.query(APIEndpoint).filter(
        APIEndpoint.id == endpoint_id,
        APIEndpoint.user_id == current_user.id
    ).first()

    if endpoint is None:
        raise HTTPException(
            status_code=404,
            detail="Endpoint not found"
        )

    result = check_api(endpoint.url, endpoint.method)

    history = MonitoringHistory(
        endpoint_id=endpoint.id,
        status=result["status"],
        status_code=result["status_code"],
        response_time=result["response_time"]
    )

    db.add(history)
    db.commit()

    return {
        "endpoint_id": endpoint.id,
        "endpoint_name": endpoint.name,
        **result
    }
    
@router.get("/{endpoint_id}/history")
def get_monitoring_history(
    endpoint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    endpoint = db.query(APIEndpoint).filter(
        APIEndpoint.id == endpoint_id,
        APIEndpoint.user_id == current_user.id
    ).first()

    if endpoint is None:
        raise HTTPException(
            status_code=404,
            detail="Endpoint not found"
        )

    history = db.query(MonitoringHistory).filter(
        MonitoringHistory.endpoint_id == endpoint_id
    ).order_by(
        MonitoringHistory.checked_at.desc()
    ).all()

    return history


@router.get("/{endpoint_id}/analytics", response_model=AnalyticsResponse)
def get_endpoint_analytics(
    endpoint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    endpoint = db.query(APIEndpoint).filter(
        APIEndpoint.id == endpoint_id,
        APIEndpoint.user_id == current_user.id
    ).first()

    if endpoint is None:
        raise HTTPException(
            status_code=404,
            detail="Endpoint not found"
        )

    history = db.query(MonitoringHistory).filter(
        MonitoringHistory.endpoint_id == endpoint_id
    ).all()

    total_checks = len(history)

    successful_checks = sum(
        1 for record in history if record.status == "UP"
    )

    failed_checks = total_checks - successful_checks

    average_response_time = (
        sum(record.response_time for record in history) / total_checks
        if total_checks > 0 else 0
    )

    uptime_percentage = (
        (successful_checks / total_checks) * 100
        if total_checks > 0 else 0
    )

    return {
        "endpoint_id": endpoint_id,
        "total_checks": total_checks,
        "successful_checks": successful_checks,
        "failed_checks": failed_checks,
        "average_response_time": round(average_response_time, 2),
        "uptime_percentage": round(uptime_percentage, 2)
    }
    
    
    
@router.get("/dashboard/summary", response_model=DashboardSummary)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    total_endpoints = db.query(APIEndpoint).filter(
        APIEndpoint.user_id == current_user.id
    ).count()

    active_endpoints = db.query(APIEndpoint).filter(
        APIEndpoint.user_id == current_user.id,
        APIEndpoint.is_active == True
    ).count()

    endpoint_ids = db.query(APIEndpoint.id).filter(
        APIEndpoint.user_id == current_user.id
    ).subquery()

    history = db.query(MonitoringHistory).filter(
        MonitoringHistory.endpoint_id.in_(endpoint_ids)
    )

    total_checks = history.count()

    successful_checks = history.filter(
        MonitoringHistory.status == "UP"
    ).count()

    failed_checks = total_checks - successful_checks

    average_response_time = db.query(
        func.avg(MonitoringHistory.response_time)
    ).filter(
        MonitoringHistory.endpoint_id.in_(endpoint_ids)
    ).scalar() or 0

    uptime_percentage = (
        successful_checks / total_checks * 100
        if total_checks > 0 else 0
    )

    return {
        "total_endpoints": total_endpoints,
        "active_endpoints": active_endpoints,
        "total_checks": total_checks,
        "successful_checks": successful_checks,
        "failed_checks": failed_checks,
        "average_response_time": round(average_response_time, 2),
        "uptime_percentage": round(uptime_percentage, 2)
    }