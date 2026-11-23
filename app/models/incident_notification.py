from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint

from app.database import Base


class IncidentNotification(Base):
    __tablename__ = "incident_notifications"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    kind = Column(String(12), nullable=False)
    endpoint_origin = Column(String(512))
    state = Column(String(12), nullable=False, server_default="pending")
    attempts = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False)
    available_at = Column(DateTime(timezone=True), nullable=False)
    lease_until = Column(DateTime(timezone=True))
    claim_id = Column(String(32))
    completed_at = Column(DateTime(timezone=True))
    last_error = Column(String(32))

    __table_args__ = (
        UniqueConstraint("incident_id", "kind", name="uq_incident_notification_kind"),
        CheckConstraint("kind IN ('opened','recovered')", name="ck_incident_notification_kind"),
        CheckConstraint("state IN ('pending','processing','retrying','sent','failed')",
                        name="ck_incident_notification_state"),
        CheckConstraint("attempts >= 0", name="ck_incident_notification_attempts"),
        CheckConstraint(
            "(state = 'processing' AND claim_id IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(state <> 'processing' AND claim_id IS NULL AND lease_until IS NULL)",
            name="ck_incident_notification_claim",
        ),
        CheckConstraint(
            "(state IN ('sent','failed') AND completed_at IS NOT NULL) OR "
            "(state NOT IN ('sent','failed') AND completed_at IS NULL)",
            name="ck_incident_notification_completion",
        ),
        Index("ix_incident_notifications_ready", "state", "available_at", "id"),
        Index("ix_incident_notifications_lease", "state", "lease_until"),
        Index("ix_incident_notifications_completed", "completed_at"),
    )
