import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.api.dependencies import (
    CurrentAccountDependency,
    SessionDependency,
    require_admin,
)
from app.schemas.accounts import (
    AccountCreate,
    AccountCreated,
    AccountView,
    CreditRechargeCreate,
    CreditRechargeView,
    CurrentAccountView,
    TokenView,
)
from app.services.accounts import (
    AccountAlreadyExistsError,
    AccountNotRechargeableError,
    AccountNotFoundError,
    AccountService,
    CreditRechargeConflictError,
)

admin_router = APIRouter(
    prefix="/v1/admin/accounts",
    tags=["admin-accounts"],
    dependencies=[Depends(require_admin)],
)
account_router = APIRouter(prefix="/v1/account", tags=["account"])
AdminIdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=64)
]


@admin_router.post("", response_model=AccountCreated, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate, session: SessionDependency) -> AccountCreated:
    try:
        created = AccountService(session).create(
            email=str(payload.email),
            token_type=payload.token_type,
            expires_in_days=payload.expires_in_days,
            total_quota=payload.total_quota,
        )
    except AccountAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "account_email_exists"},
        ) from None

    return AccountCreated(
        account=AccountView.model_validate(created.account),
        app_token=created.app_token,
    )


@admin_router.get("", response_model=list[AccountView])
def list_accounts(
    session: SessionDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AccountView]:
    accounts = AccountService(session).list(offset=offset, limit=limit)
    return [AccountView.model_validate(account) for account in accounts]


@admin_router.get("/{account_id}", response_model=AccountView)
def get_account(account_id: uuid.UUID, session: SessionDependency) -> AccountView:
    account = _get_account_or_404(AccountService(session), account_id)
    return AccountView.model_validate(account)


@admin_router.post("/{account_id}/revoke", response_model=AccountView)
def revoke_account(account_id: uuid.UUID, session: SessionDependency) -> AccountView:
    service = AccountService(session)
    try:
        account = service.revoke(account_id)
    except AccountNotFoundError:
        raise _account_not_found() from None
    return AccountView.model_validate(account)


@admin_router.post("/{account_id}/credits", response_model=CreditRechargeView)
def recharge_account(
    account_id: uuid.UUID,
    payload: CreditRechargeCreate,
    idempotency_key: AdminIdempotencyKey,
    session: SessionDependency,
) -> CreditRechargeView:
    service = AccountService(session)
    try:
        result = service.recharge(
            account_id,
            credits=payload.credits,
            idempotency_key=idempotency_key,
        )
    except AccountNotFoundError:
        raise _account_not_found() from None
    except AccountNotRechargeableError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "account_not_rechargeable"},
        ) from None
    except CreditRechargeConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "idempotency_key_conflict"},
        ) from None

    return CreditRechargeView(
        id=result.recharge.id,
        token_id=result.recharge.token_id,
        credits=result.recharge.credits,
        total_quota=result.token.total_quota,
        used_quota=result.token.used_quota,
        remaining_quota=result.token.total_quota - result.token.used_quota,
        created_at=result.recharge.created_at,
    )


@account_router.get("/me", response_model=CurrentAccountView)
def get_me(current: CurrentAccountDependency) -> CurrentAccountView:
    return CurrentAccountView(
        account_id=current.account.id,
        email=current.account.email,
        account_status=current.account.status,
        token=TokenView.model_validate(current.token),
    )


def _get_account_or_404(service: AccountService, account_id: uuid.UUID):
    try:
        return service.get(account_id)
    except AccountNotFoundError:
        raise _account_not_found() from None


def _account_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "account_not_found"},
    )
