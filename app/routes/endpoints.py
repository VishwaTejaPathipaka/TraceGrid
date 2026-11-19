from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import APIEndpoint
from app.models.users import User
from app.schemas.endpoint import EndpointCreate, EndpointResponse
from app.security import get_current_user

router = APIRouter()


@router.get("/", response_model=list[EndpointResponse])
def get_endpoints(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    endpoints = db.query(APIEndpoint).filter(
        APIEndpoint.user_id == current_user.id
    ).all()

    return endpoints


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
    new_endpoint = APIEndpoint(
        name=endpoint.name,
        url=str(endpoint.url),
        method=endpoint.method,
        user_id=current_user.id
    )

    db.add(new_endpoint)
    db.commit()
    db.refresh(new_endpoint)

    return new_endpoint


@router.put("/{endpoint_id}", response_model=EndpointResponse)
def update_endpoint(
    endpoint_id: int,
    updated_data: EndpointCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    endpoint = db.query(APIEndpoint).filter(
        APIEndpoint.id == endpoint_id,
        APIEndpoint.user_id == current_user.id
    ).first()

    if endpoint is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    endpoint.name = updated_data.name
    endpoint.url = str(updated_data.url)
    endpoint.method = updated_data.method

    db.commit()
    db.refresh(endpoint)

    return endpoint


@router.delete("/{endpoint_id}")
def delete_endpoint(
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

    db.delete(endpoint)
    db.commit()

    return {"message": "Endpoint deleted successfully"}