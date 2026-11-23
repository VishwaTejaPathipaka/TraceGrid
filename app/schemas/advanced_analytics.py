from datetime import datetime
from typing import Literal

from pydantic import BaseModel


AnalyticsRange = Literal["1h", "6h", "24h", "7d"]
ComparisonMetric = Literal["uptime", "latency", "successful", "unsuccessful", "measured"]


class WindowResponse(BaseModel):
    start: datetime
    end: datetime
    bucket_seconds: int
    bucket_count: int


class AvailabilityCounts(BaseModel):
    successful: int
    unsuccessful: int
    monitoring_errors: int


class LatencyStatistics(BaseModel):
    samples: int
    average: float | None
    median: float | None
    p95: float | None
    p99: float | None
    maximum: float | None


class ProbeSample(BaseModel):
    id: int
    checked_at: datetime
    status: str
    status_code: int | None
    response_time: float | None
    reason: str | None


class TrendPoint(ProbeSample):
    segment: int | None


class TimelineBucket(AvailabilityCounts):
    index: int
    gaps: int


class LatencyBin(BaseModel):
    lower: float
    upper: float | None
    count: int


class EndpointAnalyticsDetail(BaseModel):
    id: int
    name: str
    availability: AvailabilityCounts
    uptime: float | None
    latency: LatencyStatistics
    histogram: list[LatencyBin]
    trend: list[TrendPoint]
    timeline: list[TimelineBucket]
    gap_seconds: int


class ComparisonItem(BaseModel):
    id: int
    name: str
    value: float | None
    samples: int


class ComparisonResponse(BaseModel):
    items: list[ComparisonItem]
    total: int
    offset: int
    limit: int
    maximum: float | None


class AffectedEndpoint(BaseModel):
    id: int | None
    name: str
    incidents: int


class IncidentAnalytics(BaseModel):
    overlapping: int
    opened: int
    recovered: int
    manually_resolved: int
    average_recovery_seconds: float | None
    affected: list[AffectedEndpoint]


class AnalyticsReport(BaseModel):
    window: WindowResponse
    endpoint: EndpointAnalyticsDetail | None
    comparison: ComparisonResponse | None
    incidents: IncidentAnalytics


class ProbeCursor(BaseModel):
    at: datetime
    id: int


class TimelineChecks(BaseModel):
    items: list[ProbeSample]
    next_cursor: ProbeCursor | None
