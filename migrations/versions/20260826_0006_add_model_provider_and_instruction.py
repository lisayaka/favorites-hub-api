"""增加整理偏好与模型供应商审计字段。

Revision ID: 20260826_0006
Revises: 20260826_0005
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0006"
down_revision: str | None = "20260826_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_jobs",
        sa.Column(
            "organization_instruction",
            sa.String(length=300),
            server_default=sa.text("''"),
            nullable=False,
        ),
    )
    op.add_column("ai_requests", sa.Column("provider", sa.String(length=32)))
    op.add_column("search_requests", sa.Column("provider", sa.String(length=32)))


def downgrade() -> None:
    op.drop_column("search_requests", "provider")
    op.drop_column("ai_requests", "provider")
    op.drop_column("ai_jobs", "organization_instruction")
