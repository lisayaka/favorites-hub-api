import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Account, AppToken, CreditRecharge


class AccountRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, account: Account) -> None:
        self.session.add(account)

    def get_by_email(self, email: str) -> Account | None:
        return self.session.scalar(select(Account).where(Account.email == email))

    def get(self, account_id: uuid.UUID) -> Account | None:
        return self.session.scalar(
            select(Account)
            .options(selectinload(Account.tokens))
            .where(Account.id == account_id)
        )

    def list(self, *, offset: int, limit: int) -> list[Account]:
        return list(
            self.session.scalars(
                select(Account)
                .options(selectinload(Account.tokens))
                .order_by(Account.created_at.desc(), Account.id)
                .offset(offset)
                .limit(limit)
            )
        )

    def get_token_by_hash(self, token_hash: str) -> AppToken | None:
        return self.session.scalar(
            select(AppToken)
            .options(selectinload(AppToken.account))
            .where(AppToken.token_hash == token_hash)
        )

    def lock_latest_token(self, account_id: uuid.UUID) -> AppToken | None:
        return self.session.scalar(
            select(AppToken)
            .options(selectinload(AppToken.account))
            .where(AppToken.account_id == account_id)
            .order_by(AppToken.created_at.desc(), AppToken.id)
            .limit(1)
            .with_for_update()
        )

    def get_recharge(
        self, token_id: uuid.UUID, idempotency_key: str
    ) -> CreditRecharge | None:
        return self.session.scalar(
            select(CreditRecharge).where(
                CreditRecharge.token_id == token_id,
                CreditRecharge.idempotency_key == idempotency_key,
            )
        )

    def add_recharge(self, recharge: CreditRecharge) -> None:
        self.session.add(recharge)
