"""创建额度充值流水。

Revision ID: 20260826_0004
Revises: 20260825_0003
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0004"
down_revision: str | None = "20260825_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credit_recharges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("total_quota_before", sa.Integer(), nullable=False),
        sa.Column("total_quota_after", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("credits > 0", name="ck_credit_recharges_credits"),
        sa.ForeignKeyConstraint(["token_id"], ["app_tokens.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_id", "idempotency_key", name="uq_credit_recharges_key"),
    )
    op.create_index("ix_credit_recharges_token_id", "credit_recharges", ["token_id"])


def downgrade() -> None:
    op.drop_index("ix_credit_recharges_token_id", table_name="credit_recharges")
    op.drop_table("credit_recharges")
