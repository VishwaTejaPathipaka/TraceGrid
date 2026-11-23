from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


IncidentStatus = Literal["open", "acknowledged", "resolved"]


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    endpoint_id: int | None
    endpoint_name: str
    title: str
    status: IncidentStatus
    severity: Literal["warning", "critical"]
    failure_reason: str
    failure_http_status: int | None
    started_at: datetime
    detected_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    resolution: Literal["manual", "recovered"] | None
    recovery_http_status: int | None
    recovery_response_ms: float | None

    @field_validator("started_at", "detected_at", "acknowledged_at", "resolved_at")
    @classmethod
    def timestamps_have_timezones(cls, value):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class IncidentPage(BaseModel):
    items: list[IncidentResponse]
    total: int


class IncidentSummary(BaseModel):
    active_count: int
    affected_endpoints: int
    active: list[IncidentResponse]
    recently_resolved: list[IncidentResponse]
