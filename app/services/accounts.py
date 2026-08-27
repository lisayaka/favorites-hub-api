import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Account, AppToken, CreditRecharge
from app.repositories.accounts import AccountRepository


class AccountAlreadyExistsError(Exception):
    pass


class AccountNotFoundError(Exception):
    pass


class InvalidAppTokenError(Exception):
    pass


class AccountNotRechargeableError(Exception):
    pass


class CreditRechargeConflictError(Exception):
    pass


@dataclass(frozen=True)
class CreatedAccount:
    account: Account
    app_token: str


@dataclass(frozen=True)
class AuthenticatedAccount:
    account: Account
    token: AppToken


@dataclass(frozen=True)
class RechargedCredits:
    recharge: CreditRecharge
    token: AppToken


class AccountService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = AccountRepository(session)

    def create(
        self,
        *,
        email: str,
        token_type: str,
        expires_in_days: int,
        total_quota: int,
    ) -> CreatedAccount:
        normalized_email = email.strip().casefold()
        if self.repository.get_by_email(normalized_email):
            raise AccountAlreadyExistsError

        app_token = _generate_token(token_type)
        account = Account(email=normalized_email)
        account.tokens.append(
            AppToken(
                token_hash=_hash_token(app_token),
                prefix=app_token[:18],
                token_type=token_type,
                expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
                total_quota=total_quota,
            )
        )
        self.repository.add(account)

        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise AccountAlreadyExistsError from error

        return CreatedAccount(account=account, app_token=app_token)

    def list(self, *, offset: int, limit: int) -> list[Account]:
        return self.repository.list(offset=offset, limit=limit)

    def get(self, account_id: uuid.UUID) -> Account:
        account = self.repository.get(account_id)
        if not account:
            raise AccountNotFoundError
        return account

    def revoke(self, account_id: uuid.UUID) -> Account:
        account = self.get(account_id)
        if account.status != "revoked":
            now = datetime.now(UTC)
            account.status = "revoked"
            account.revoked_at = now
            for token in account.tokens:
                token.status = "revoked"
            self.session.commit()
        return account

    def recharge(
        self, account_id: uuid.UUID, *, credits: int, idempotency_key: str
    ) -> RechargedCredits:
        self.get(account_id)
        token = self.repository.lock_latest_token(account_id)
        if token is None or not _token_is_usable(token):
            self.session.rollback()
            raise AccountNotRechargeableError

        existing = self.repository.get_recharge(token.id, idempotency_key)
        if existing:
            self.session.rollback()
            if existing.credits != credits:
                raise CreditRechargeConflictError
            return RechargedCredits(recharge=existing, token=token)

        before = token.total_quota
        token.total_quota += credits
        recharge = CreditRecharge(
            token_id=token.id,
            idempotency_key=idempotency_key,
            credits=credits,
            total_quota_before=before,
            total_quota_after=token.total_quota,
        )
        self.repository.add_recharge(recharge)
        self.session.commit()
        return RechargedCredits(recharge=recharge, token=token)

    def authenticate(self, raw_token: str) -> AuthenticatedAccount:
        token = self.repository.get_token_by_hash(_hash_token(raw_token))
        if not token or not _token_is_usable(token):
            raise InvalidAppTokenError

        token.last_used_at = datetime.now(UTC)
        self.session.commit()
        return AuthenticatedAccount(account=token.account, token=token)


def _generate_token(token_type: str) -> str:
    return f"fh_{token_type}_{secrets.token_urlsafe(32)}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_is_usable(token: AppToken) -> bool:
    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return (
        token.status == "active"
        and token.account.status == "active"
        and expires_at > datetime.now(UTC)
    )
