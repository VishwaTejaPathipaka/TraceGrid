from pydantic import BaseModel


class AnalyticsResponse(BaseModel):
    endpoint_id: int
    total_checks: int
    successful_checks: int
    failed_checks: int
    average_response_time: float
    uptime_percentage: float | None
    
    
class DashboardSummary(BaseModel):
    total_endpoints: int
    active_endpoints: int
    total_checks: int
    successful_checks: int
    failed_checks: int
    average_response_time: float
    latency_samples: int
    uptime_percentage: float | None
