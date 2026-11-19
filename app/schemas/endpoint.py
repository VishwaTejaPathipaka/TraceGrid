from pydantic import BaseModel, HttpUrl
from typing import Optional


class EndpointCreate(BaseModel):
    name: str
    url: HttpUrl
    method: str = "GET"


class EndpointResponse(BaseModel):
    id: int
    name: str
    url: str
    method: str
    is_active: bool

    class Config:
        from_attributes = True