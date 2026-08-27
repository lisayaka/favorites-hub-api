"""创建 AI 幂等请求与用量记录表。

Revision ID: 20260825_0002
Revises: 20260825_0001
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0002"
down_revision: str | None = "20260825_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("quota_units", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "operation IN ('classify', 'enrich')", name="ck_ai_requests_operation"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_ai_requests_status",
        ),
        sa.ForeignKeyConstraint(["token_id"], ["app_tokens.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_id", "operation", "idempotency_key", name="uq_ai_requests_key"
        ),
    )
    op.create_index("ix_ai_requests_token_id", "ai_requests", ["token_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_requests_token_id", table_name="ai_requests")
    op.drop_table("ai_requests")
