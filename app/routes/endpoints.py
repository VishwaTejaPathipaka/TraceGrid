from socket import gaierror

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models import APIEndpoint, MonitoringHistory
from app.models.users import User
from app.schemas.endpoint import EndpointCreate, EndpointListItem, EndpointResponse
from app.schemas.monitor import HistoryEntry
from app.security import get_current_user
from app.services.connection_limits import manual_probe_slot
from app.services.rate_limits import limit_owner
from app.services.monitoring_events import stage_event
from app.services.websocket_manager import websocket_manager
from app.services.dns_resolver import is_missing_hostname
from app.services.monitoring_policy import (
    MonitoringPolicyError,
    parse_monitoring_url,
    resolve_public_addresses,
)

router = APIRouter()


def commit_endpoint_change(db, endpoint_id, owner_id):
    event = stage_event(db, {"type": "endpoint.updated", "endpoint_id": endpoint_id, "user_id": owner_id})
    db.commit()
    websocket_manager.publish_local(event)


def validate_monitoring_destination(url: str) -> None:
    try:
        resolve_public_addresses(parse_monitoring_url(url))
    except MonitoringPolicyError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except TimeoutError as error:
        raise HTTPException(
            status_code=503,
            detail="The monitoring hostname lookup timed out. Try saving again.",
        ) from error
    except gaierror as error:
        raise HTTPException(
            status_code=422 if is_missing_hostname(error) else 503,
            detail="The monitoring hostname could not be resolved. Check the URL and try again.",
        ) from error
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=503, detail="The monitoring resolver is unavailable. Try again.") from error


@router.get("/", response_model=list[EndpointListItem])
def get_endpoints(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    latest = (
        select(MonitoringHistory.id)
        .where(MonitoringHistory.endpoint_id == APIEndpoint.id, MonitoringHistory.checked_at.is_not(None))
        .order_by(MonitoringHistory.checked_at.desc(), MonitoringHistory.id.desc())
        .limit(1).correlate(APIEndpoint).scalar_subquery()
    )
    undated = (
        select(MonitoringHistory.id)
        .where(MonitoringHistory.endpoint_id == APIEndpoint.id, MonitoringHistory.checked_at.is_(None))
        .order_by(MonitoringHistory.id.desc()).limit(1).correlate(APIEndpoint).scalar_subquery()
    )
    rows = db.execute(
        select(APIEndpoint, MonitoringHistory)
        .outerjoin(MonitoringHistory, MonitoringHistory.id == func.coalesce(latest, undated))
        .where(APIEndpoint.user_id == current_user.id)
        .order_by(APIEndpoint.id)
    )
    return [
        EndpointListItem(
            **EndpointResponse.model_validate(endpoint).model_dump(),
            latest_check=HistoryEntry.model_validate(check) if check is not None else None,
        )
        for endpoint, check in rows
    ]


@router.get("/{endpoint_id}", response_model=EndpointResponse)
def get_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    endpoint = db.query(APIEndpoint).filter(
        APIEndpoint.id == endpoint_id,
        APIEndpoint.user_id == current_user.id
    ).first()

    if endpoint is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    return endpoint


@router.post("/", response_model=EndpointResponse)
def create_endpoint(
    endpoint: EndpointCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    owner_id = current_user.id
    limit_owner(db, owner_id, "endpoint_write")
    with manual_probe_slot(db.get_bind(), owner_id):
        validate_monitoring_destination(str(endpoint.url))
    # Serialize the quota check and insert across workers for this owner.
    db.scalar(select(User.id).where(User.id == owner_id).with_for_update())
    size = db.scalar(select(func.count()).select_from(APIEndpoint).where(APIEndpoint.user_id == owner_id))
    if size >= settings.MAX_ENDPOINTS_PER_USER:
        raise HTTPException(409, "Endpoint limit reached. Remove an endpoint before adding another.")
    new_endpoint = APIEndpoint(
        name=endpoint.name,
        url=str(endpoint.url),
        method=endpoint.method,
        user_id=owner_id
    )

    db.add(new_endpoint)
    db.flush()
    commit_endpoint_change(db, new_endpoint.id, owner_id)
    db.refresh(new_endpoint)

    return new_endpoint


@router.put("/{endpoint_id}", response_model=EndpointResponse)
def update_endpoint(
    endpoint_id: int,
    updated_data: EndpointCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    owner_id = current_user.id
    limit_owner(db, owner_id, "endpoint_write")
    endpoint = db.query(APIEndpoint).filter(
        APIEndpoint.id == endpoint_id,
        APIEndpoint.user_id == current_user.id
    ).first()

    if endpoint is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    engine = db.get_bind()
    db.rollback()
    with manual_probe_slot(engine, owner_id):
        validate_monitoring_destination(str(updated_data.url))
    updated = db.execute(update(APIEndpoint).where(
        APIEndpoint.id == endpoint_id, APIEndpoint.user_id == owner_id,
    ).values(
        name=updated_data.name,
        url=str(updated_data.url),
        method=updated_data.method,
        configuration_error=None,
        configuration_revision=APIEndpoint.configuration_revision + 1,
        incident_failure_count=0,
        incident_failure_since=None,
    ))
    if updated.rowcount == 0:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    commit_endpoint_change(db, endpoint_id, owner_id)
    db.refresh(endpoint)

    return endpoint


@router.delete("/{endpoint_id}")
def delete_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    endpoint = db.scalar(select(APIEndpoint).where(
        APIEndpoint.id == endpoint_id,
        APIEndpoint.user_id == current_user.id
    ).with_for_update())

    if endpoint is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    # Serialize deletion with probe writers, which lock the same endpoint before saving.
    db.execute(delete(MonitoringHistory).where(MonitoringHistory.endpoint_id == endpoint_id))
    db.delete(endpoint)
    commit_endpoint_change(db, endpoint_id, current_user.id)

    return {"message": "Endpoint deleted successfully"}
