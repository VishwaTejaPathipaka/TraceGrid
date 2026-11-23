"""Add shared abuse counters without rewriting application records."""

from alembic import op
import sqlalchemy as sa


revision = "20261123_06"
down_revision = "20261123_05"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rate_limit_counters",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
    )
    op.create_index("ix_rate_limit_counters_expiry", "rate_limit_counters", ["expires_at"])


def downgrade():
    op.drop_table("rate_limit_counters")
