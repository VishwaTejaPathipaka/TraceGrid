from datetime import datetime, timezone

from pydantic import BaseModel, HttpUrl, field_validator
from typing import Literal

from app.schemas.monitor import HistoryEntry


class EndpointCreate(BaseModel):
    name: str
    url: HttpUrl
    method: Literal["GET", "HEAD"] = "GET"


class EndpointResponse(BaseModel):
    id: int
    name: str
    url: str
    method: str
    is_active: bool
    configuration_error: str | None = None
    next_check_at: datetime
    last_schedule_lateness_ms: int | None = None
    last_schedule_duration_ms: int | None = None
    last_schedule_missed_intervals: int | None = None

    @field_validator("next_check_at")
    @classmethod
    def assume_utc_for_naive_database_values(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    class Config:
        from_attributes = True


class EndpointListItem(EndpointResponse):
    latest_check: HistoryEntry | None = None
