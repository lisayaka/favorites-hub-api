import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked')", name="ck_accounts_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tokens: Mapped[list["AppToken"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class AppToken(Base):
    __tablename__ = "app_tokens"
    __table_args__ = (
        CheckConstraint("token_type IN ('trial', 'live')", name="ck_app_tokens_type"),
        CheckConstraint("status IN ('active', 'revoked')", name="ck_app_tokens_status"),
        CheckConstraint("total_quota > 0", name="ck_app_tokens_total_quota"),
        CheckConstraint("used_quota >= 0", name="ck_app_tokens_used_quota"),
        CheckConstraint("used_quota <= total_quota", name="ck_app_tokens_quota_usage"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    token_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_quota: Mapped[int] = mapped_column(nullable=False)
    used_quota: Mapped[int] = mapped_column(default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    account: Mapped[Account] = relationship(back_populates="tokens")


class CreditRecharge(Base):
    __tablename__ = "credit_recharges"
    __table_args__ = (
        CheckConstraint("credits > 0", name="ck_credit_recharges_credits"),
        UniqueConstraint(
            "token_id", "idempotency_key", name="uq_credit_recharges_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    token_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_tokens.id", ondelete="CASCADE"), index=True, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    credits: Mapped[int] = mapped_column(nullable=False)
    total_quota_before: Mapped[int] = mapped_column(nullable=False)
    total_quota_after: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIJob(Base):
    __tablename__ = "ai_jobs"
    __table_args__ = (
        CheckConstraint("mode IN ('all', 'selected')", name="ck_ai_jobs_mode"),
        UniqueConstraint("token_id", "idempotency_key", name="uq_ai_jobs_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    token_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_tokens.id", ondelete="CASCADE"), index=True, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    organization_instruction: Mapped[str] = mapped_column(
        String(300), default="", server_default="", nullable=False
    )
    classification_item_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    enrichment_item_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    classification_call_limit: Mapped[int] = mapped_column(nullable=False)
    enrichment_call_limit: Mapped[int] = mapped_column(nullable=False)
    credits: Mapped[int] = mapped_column(default=10, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIRequest(Base):
    __tablename__ = "ai_requests"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('classify', 'enrich')", name="ck_ai_requests_operation"
        ),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_ai_requests_status",
        ),
        UniqueConstraint(
            "token_id", "operation", "idempotency_key", name="uq_ai_requests_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_jobs.id", ondelete="CASCADE"), index=True
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_tokens.id", ondelete="CASCADE"), index=True, nullable=False
    )
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_json: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    duration_ms: Mapped[int] = mapped_column(default=0, nullable=False)
    quota_units: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SearchDocument(Base):
    __tablename__ = "search_documents"
    __table_args__ = (
        UniqueConstraint("account_id", "item_id", name="uq_search_documents_item"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    item_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    category_path: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SearchRequestRecord(Base):
    __tablename__ = "search_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_search_requests_status",
        ),
        CheckConstraint("credits = 2", name="ck_search_requests_credits"),
        UniqueConstraint(
            "token_id", "idempotency_key", name="uq_search_requests_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    token_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_tokens.id", ondelete="CASCADE"), index=True, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_json: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    duration_ms: Mapped[int] = mapped_column(default=0, nullable=False)
    credits: Mapped[int] = mapped_column(default=2, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
