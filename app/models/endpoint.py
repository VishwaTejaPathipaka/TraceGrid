from sqlalchemy import BigInteger, Column, Integer, String, Boolean, DateTime, ForeignKey, Index, text
from sqlalchemy.sql import func

from app.database import Base


class APIEndpoint(Base):
    __tablename__ = "api_endpoints"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    url = Column(String(500), nullable=False)
    method = Column(String(10), default="GET", nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    configuration_error = Column(String(255), nullable=True)
    configuration_revision = Column(Integer, nullable=False, server_default="0")
    next_check_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    scheduled_claim_id = Column(String(32), nullable=True)
    scheduled_lease_until = Column(DateTime(timezone=True), nullable=True)
    last_schedule_lateness_ms = Column(BigInteger, nullable=True)
    last_schedule_duration_ms = Column(Integer, nullable=True)
    last_schedule_missed_intervals = Column(Integer, nullable=True)
    incident_failure_count = Column(Integer, nullable=False, server_default="0")
    incident_failure_since = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_api_endpoints_active_due", "next_check_at", "id",
              postgresql_where=text("is_active IS TRUE"), sqlite_where=text("is_active IS TRUE")),
    )
