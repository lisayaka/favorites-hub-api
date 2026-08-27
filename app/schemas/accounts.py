import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AccountCreate(BaseModel):
    email: EmailStr
    token_type: Literal["trial", "live"] = "trial"
    expires_in_days: int = Field(default=7, ge=1, le=3650)
    total_quota: int = Field(default=100, ge=1)


class TokenView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    prefix: str
    token_type: Literal["trial", "live"]
    status: Literal["active", "revoked"]
    expires_at: datetime
    total_quota: int
    used_quota: int
    last_used_at: datetime | None
    created_at: datetime


class AccountView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    status: Literal["active", "revoked"]
    created_at: datetime
    revoked_at: datetime | None
    tokens: list[TokenView]


class AccountCreated(BaseModel):
    account: AccountView
    app_token: str


class CreditRechargeCreate(BaseModel):
    credits: int = Field(ge=1, le=1_000_000)


class CreditRechargeView(BaseModel):
    id: uuid.UUID
    token_id: uuid.UUID
    credits: int
    total_quota: int
    used_quota: int
    remaining_quota: int
    created_at: datetime


class CurrentAccountView(BaseModel):
    account_id: uuid.UUID
    email: EmailStr
    account_status: Literal["active", "revoked"]
    token: TokenView
