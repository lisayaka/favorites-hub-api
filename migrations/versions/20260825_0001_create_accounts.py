"""创建邮箱账户与应用 Token 表。

Revision ID: 20260825_0001
Revises:
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')", name="ck_accounts_status"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "app_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=24), nullable=False),
        sa.Column("token_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_quota", sa.Integer(), nullable=False),
        sa.Column("used_quota", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')", name="ck_app_tokens_status"
        ),
        sa.CheckConstraint(
            "token_type IN ('trial', 'live')", name="ck_app_tokens_type"
        ),
        sa.CheckConstraint(
            "total_quota > 0", name="ck_app_tokens_total_quota"
        ),
        sa.CheckConstraint("used_quota >= 0", name="ck_app_tokens_used_quota"),
        sa.CheckConstraint(
            "used_quota <= total_quota", name="ck_app_tokens_quota_usage"
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_app_tokens_account_id", "app_tokens", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_app_tokens_account_id", table_name="app_tokens")
    op.drop_table("app_tokens")
    op.drop_table("accounts")
