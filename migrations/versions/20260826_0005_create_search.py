"""创建搜索派生文档与幂等请求表。

Revision ID: 20260826_0005
Revises: 20260826_0004
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0005"
down_revision: str | None = "20260826_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.String(length=160), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("category_path", sa.JSON(), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "item_id", name="uq_search_documents_item"),
    )
    op.create_index("ix_search_documents_account_id", "search_documents", ["account_id"])

    op.create_table(
        "search_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_search_requests_status",
        ),
        sa.CheckConstraint("credits = 2", name="ck_search_requests_credits"),
        sa.ForeignKeyConstraint(["token_id"], ["app_tokens.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_id", "idempotency_key", name="uq_search_requests_key"),
    )
    op.create_index("ix_search_requests_token_id", "search_requests", ["token_id"])


def downgrade() -> None:
    op.drop_index("ix_search_requests_token_id", table_name="search_requests")
    op.drop_table("search_requests")
    op.drop_index("ix_search_documents_account_id", table_name="search_documents")
    op.drop_table("search_documents")
