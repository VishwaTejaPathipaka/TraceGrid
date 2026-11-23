from sqlalchemy import BigInteger, Column, Integer, String, Float, DateTime, ForeignKey, Index
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
    reason = Column(String(32), nullable=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    schedule_lateness_ms = Column(BigInteger, nullable=True)
    execution_duration_ms = Column(Integer, nullable=True)

    checked_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    __table_args__ = (Index("ix_monitoring_history_endpoint_time", "endpoint_id", "checked_at", "id"),)
