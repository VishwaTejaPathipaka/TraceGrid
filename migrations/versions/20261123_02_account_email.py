"""Add account email links and session invalidation."""

from alembic import op
import sqlalchemy as sa


revision = "20261123_02"
down_revision = "20261123_01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email_key", sa.Text()))
    op.add_column("users", sa.Column("email_verification_required", sa.Boolean(),
                                    nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"))
    connection = op.get_bind()
    users = sa.table("users", sa.column("id"), sa.column("email"), sa.column("email_key"))
    rows = connection.execute(sa.select(users.c.id, users.c.email)).all()
    if rows:
        connection.execute(users.update().where(users.c.id == sa.bindparam("user_id")),
                           [{"user_id": row.id, "email_key": row.email.lower()} for row in rows])
    op.create_index("ix_users_email_key", "users", ["email_key"])
    op.create_table(
        "account_tokens",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("purpose", sa.String(16), primary_key=True),
        sa.Column("digest", sa.String(64), nullable=False, unique=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("account_tokens")
    op.drop_index("ix_users_email_key", table_name="users")
    op.drop_column("users", "session_version")
    op.drop_column("users", "email_verification_required")
    op.drop_column("users", "email_key")
