from datetime import datetime
from math import isfinite

from pydantic import BaseModel, ConfigDict, field_validator


class ProbeResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status: str
    status_code: int | None
    response_time: float
    reason: str | None = None


class MonitorResponse(ProbeResult):
    endpoint_id: int
    endpoint_name: str


class HistoryEntry(ProbeResult):
    id: int
    endpoint_id: int
    checked_at: datetime | None
    scheduled_for: datetime | None = None
    schedule_lateness_ms: int | None = None
    execution_duration_ms: int | None = None
    response_time: float | None

    @field_validator("response_time")
    @classmethod
    def valid_response_time(cls, value):
        return value if value is not None and isfinite(value) and value >= 0 else None


class RecentActivity(HistoryEntry):
    endpoint_name: str
