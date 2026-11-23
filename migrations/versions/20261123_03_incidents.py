"""Add incident lifecycle and persisted failure streaks."""

from alembic import op
import sqlalchemy as sa


revision = "20261123_03"
down_revision = "20261123_02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("api_endpoints", sa.Column("incident_failure_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("api_endpoints", sa.Column("incident_failure_since", sa.DateTime(timezone=True)))
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("endpoint_id", sa.Integer(), sa.ForeignKey("api_endpoints.id", ondelete="SET NULL")),
        sa.Column("endpoint_name", sa.String(100), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.Column("failure_reason", sa.String(32), nullable=False),
        sa.Column("failure_http_status", sa.Integer()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution", sa.String(16)),
        sa.Column("recovery_http_status", sa.Integer()),
        sa.Column("recovery_response_ms", sa.Float()),
        sa.CheckConstraint("status IN ('open','acknowledged','resolved')", name="ck_incident_status"),
        sa.CheckConstraint("severity IN ('warning','critical')", name="ck_incident_severity"),
        sa.CheckConstraint("resolution IN ('manual','recovered')", name="ck_incident_resolution"),
    )
    op.create_index("ix_incidents_owner_started", "incidents", ["owner_id", "started_at", "id"])
    op.create_index("ix_incidents_owner_resolved", "incidents", ["owner_id", "resolved_at", "id"])
    unresolved = sa.text("resolved_at IS NULL")
    op.create_index("uq_incidents_active_endpoint", "incidents", ["endpoint_id"], unique=True,
                    postgresql_where=unresolved, sqlite_where=unresolved)


def downgrade():
    op.drop_table("incidents")
    op.drop_column("api_endpoints", "incident_failure_since")
    op.drop_column("api_endpoints", "incident_failure_count")
