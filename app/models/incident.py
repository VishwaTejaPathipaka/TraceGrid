from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, false, text

from app.database import Base


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    endpoint_id = Column(Integer, ForeignKey("api_endpoints.id", ondelete="SET NULL"))
    endpoint_name = Column(String(100), nullable=False)
    title = Column(String(150), nullable=False)
    status = Column(String(16), nullable=False)
    severity = Column(String(8), nullable=False)
    failure_reason = Column(String(32), nullable=False)
    failure_http_status = Column(Integer)
    started_at = Column(DateTime(timezone=True), nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=False)
    acknowledged_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))
    resolution = Column(String(16))
    recovery_http_status = Column(Integer)
    recovery_response_ms = Column(Float)
    opened_email_queued = Column(Boolean, nullable=False, server_default=false())
    recovery_email_queued = Column(Boolean, nullable=False, server_default=false())

    __table_args__ = (
        CheckConstraint("status IN ('open','acknowledged','resolved')", name="ck_incident_status"),
        CheckConstraint("severity IN ('warning','critical')", name="ck_incident_severity"),
        CheckConstraint("resolution IN ('manual','recovered')", name="ck_incident_resolution"),
        Index("ix_incidents_owner_started", "owner_id", "started_at", "id"),
        Index("ix_incidents_owner_resolved", "owner_id", "resolved_at", "id"),
        Index("uq_incidents_active_endpoint", "endpoint_id", unique=True,
              postgresql_where=text("resolved_at IS NULL"), sqlite_where=text("resolved_at IS NULL")),
    )
