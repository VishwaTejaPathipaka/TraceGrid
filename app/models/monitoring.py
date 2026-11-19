from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.database import Base


class MonitoringHistory(Base):
    __tablename__ = "monitoring_history"

    id = Column(Integer, primary_key=True, index=True)

    endpoint_id = Column(
        Integer,
        ForeignKey("api_endpoints.id"),
        nullable=False
    )

    status = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=True)
    response_time = Column(Float, nullable=False)

    checked_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )