"""Index time-bounded monitoring history queries."""

from alembic import op


revision = "20261123_05"
down_revision = "20261123_04"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_monitoring_history_endpoint_time", "monitoring_history", ["endpoint_id", "checked_at", "id"])


def downgrade():
    op.drop_index("ix_monitoring_history_endpoint_time", table_name="monitoring_history")
