"""Record verified email consent and add the incident notification outbox."""

from alembic import op
import sqlalchemy as sa


revision = "20261123_04"
down_revision = "20261123_03"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    for name in ("notify_incident_opened", "notify_incident_recovered"):
        op.add_column("users", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()))
    for name in ("opened_email_queued", "recovery_email_queued"):
        op.add_column("incidents", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "incident_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("endpoint_origin", sa.String(512)),
        sa.Column("state", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("claim_id", sa.String(32)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(32)),
        sa.UniqueConstraint("incident_id", "kind", name="uq_incident_notification_kind"),
        sa.CheckConstraint("kind IN ('opened','recovered')", name="ck_incident_notification_kind"),
        sa.CheckConstraint("state IN ('pending','processing','retrying','sent','failed')",
                           name="ck_incident_notification_state"),
        sa.CheckConstraint("attempts >= 0", name="ck_incident_notification_attempts"),
        sa.CheckConstraint(
            "(state = 'processing' AND claim_id IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(state <> 'processing' AND claim_id IS NULL AND lease_until IS NULL)",
            name="ck_incident_notification_claim",
        ),
        sa.CheckConstraint(
            "(state IN ('sent','failed') AND completed_at IS NOT NULL) OR "
            "(state NOT IN ('sent','failed') AND completed_at IS NULL)",
            name="ck_incident_notification_completion",
        ),
    )
    op.create_index("ix_incident_notifications_ready", "incident_notifications", ["state", "available_at", "id"])
    op.create_index("ix_incident_notifications_lease", "incident_notifications", ["state", "lease_until"])
    op.create_index("ix_incident_notifications_completed", "incident_notifications", ["completed_at"])


def downgrade():
    op.drop_table("incident_notifications")
    for name in ("opened_email_queued", "recovery_email_queued"):
        op.drop_column("incidents", name)
    for name in ("notify_incident_opened", "notify_incident_recovered", "email_verified_at"):
        op.drop_column("users", name)
