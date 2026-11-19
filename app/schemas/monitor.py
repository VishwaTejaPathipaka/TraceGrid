from pydantic import BaseModel
from typing import Optional


class MonitorResponse(BaseModel):
    endpoint_id: int
    endpoint_name: str
    status: str
    status_code: Optional[int]
    response_time: float