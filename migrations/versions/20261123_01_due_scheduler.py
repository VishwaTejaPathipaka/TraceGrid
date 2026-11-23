"""Adopt the existing schema and add durable scheduled checks."""

from alembic import op
import sqlalchemy as sa


revision = "20261123_01"
down_revision = None
branch_labels = None
depends_on = None


def _ensure_baseline(connection):
    tables = set(sa.inspect(connection).get_table_names())
    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(50), nullable=False, unique=True),
            sa.Column("email", sa.String(100), nullable=False, unique=True),
            sa.Column("hashed_password", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if "api_endpoints" not in tables:
        op.create_table(
            "api_endpoints",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("url", sa.String(500), nullable=False),
            sa.Column("method", sa.String(10), nullable=False),
            sa.Column("is_active", sa.Boolean()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        )
    if "monitoring_history" not in tables:
        op.create_table(
            "monitoring_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("endpoint_id", sa.Integer(), sa.ForeignKey("api_endpoints.id"), nullable=False),
            sa.Column("status", sa.String(10), nullable=False),
            sa.Column("status_code", sa.Integer()),
            sa.Column("response_time", sa.Float(), nullable=False),
            sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    if "revoked_tokens" not in tables:
        op.create_table(
            "revoked_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("token", sa.String(500), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def _add_missing_columns(connection, table, columns):
    present = {column["name"] for column in sa.inspect(connection).get_columns(table)}
    for column in columns:
        if column.name not in present:
            op.add_column(table, column)
    return present


def upgrade():
    connection = op.get_bind()
    _ensure_baseline(connection)
    endpoint_fields = _add_missing_columns(connection, "api_endpoints", [
        sa.Column("configuration_error", sa.String(255)),
        sa.Column("configuration_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("scheduled_claim_id", sa.String(32)),
        sa.Column("scheduled_lease_until", sa.DateTime(timezone=True)),
        sa.Column("last_schedule_lateness_ms", sa.BigInteger()),
        sa.Column("last_schedule_duration_ms", sa.Integer()),
        sa.Column("last_schedule_missed_intervals", sa.Integer()),
    ])
    _add_missing_columns(connection, "monitoring_history", [
        sa.Column("reason", sa.String(32)),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("schedule_lateness_ms", sa.BigInteger()),
        sa.Column("execution_duration_ms", sa.Integer()),
    ])

    if "next_check_at" not in endpoint_fields:
        if connection.dialect.name == "postgresql":
            op.execute(sa.text("""
                UPDATE api_endpoints
                SET next_check_at = CURRENT_TIMESTAMP + (id % 30) * INTERVAL '1 second'
                WHERE next_check_at IS NULL
            """))
        else:
            op.execute(sa.text("UPDATE api_endpoints SET next_check_at = CURRENT_TIMESTAMP WHERE next_check_at IS NULL"))
        with op.batch_alter_table("api_endpoints") as batch:
            batch.alter_column("next_check_at", existing_type=sa.DateTime(timezone=True),
                               nullable=False, server_default=sa.func.now())

    index = "ix_api_endpoints_active_due"
    if index not in {item["name"] for item in sa.inspect(connection).get_indexes("api_endpoints")}:
        op.create_index(index, "api_endpoints", ["next_check_at", "id"],
                        postgresql_where=sa.text("is_active IS TRUE"), sqlite_where=sa.text("is_active IS TRUE"))


def downgrade():
    op.drop_index("ix_api_endpoints_active_due", table_name="api_endpoints")
    with op.batch_alter_table("monitoring_history") as batch:
        for field in ("execution_duration_ms", "schedule_lateness_ms", "scheduled_for"):
            batch.drop_column(field)
    with op.batch_alter_table("api_endpoints") as batch:
        for field in ("last_schedule_missed_intervals", "last_schedule_duration_ms", "last_schedule_lateness_ms",
                      "scheduled_lease_until", "scheduled_claim_id", "next_check_at"):
            batch.drop_column(field)
