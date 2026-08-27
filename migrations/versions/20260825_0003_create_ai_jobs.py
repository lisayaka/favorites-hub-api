"""创建统一计费的 AI 整理任务。

Revision ID: 20260825_0003
Revises: 20260825_0002
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0003"
down_revision: str | None = "20260825_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("classification_item_ids", sa.JSON(), nullable=False),
        sa.Column("enrichment_item_ids", sa.JSON(), nullable=False),
        sa.Column("classification_call_limit", sa.Integer(), nullable=False),
        sa.Column("enrichment_call_limit", sa.Integer(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("mode IN ('all', 'selected')", name="ck_ai_jobs_mode"),
        sa.ForeignKeyConstraint(["token_id"], ["app_tokens.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_id", "idempotency_key", name="uq_ai_jobs_key"),
    )
    op.create_index("ix_ai_jobs_token_id", "ai_jobs", ["token_id"])
    op.add_column("ai_requests", sa.Column("job_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_ai_requests_job_id", "ai_requests", "ai_jobs", ["job_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_ai_requests_job_id", "ai_requests", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_requests_job_id", table_name="ai_requests")
    op.drop_constraint("fk_ai_requests_job_id", "ai_requests", type_="foreignkey")
    op.drop_column("ai_requests", "job_id")
    op.drop_index("ix_ai_jobs_token_id", table_name="ai_jobs")
    op.drop_table("ai_jobs")
