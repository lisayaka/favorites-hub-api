import os
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_session
from app.services.accounts import (
    AccountService,
    AuthenticatedAccount,
    InvalidAppTokenError,
)

_admin_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)

SessionDependency = Annotated[Session, Depends(get_session)]


def require_admin(
    supplied_key: Annotated[str | None, Security(_admin_key_header)],
) -> None:
    expected_key = os.getenv("ADMIN_API_KEY")
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "admin_api_key_not_configured"},
        )
    if not supplied_key or not secrets.compare_digest(supplied_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_admin_api_key"},
        )


def get_current_account(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
    session: SessionDependency,
) -> AuthenticatedAccount:
    if not credentials or credentials.scheme.casefold() != "bearer":
        raise _invalid_token_error()

    try:
        return AccountService(session).authenticate(credentials.credentials)
    except InvalidAppTokenError:
        raise _invalid_token_error() from None


def _invalid_token_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "invalid_app_token"},
        headers={"WWW-Authenticate": "Bearer"},
    )


CurrentAccountDependency = Annotated[AuthenticatedAccount, Depends(get_current_account)]
