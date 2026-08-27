import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AppToken, SearchDocument, SearchRequestRecord


class SearchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_documents(
        self, account_id: uuid.UUID, documents: list[SearchDocument]
    ) -> None:
        self.session.execute(
            delete(SearchDocument).where(SearchDocument.account_id == account_id)
        )
        self.session.add_all(documents)

    def delete_document(self, account_id: uuid.UUID, item_id: str) -> int:
        result = self.session.execute(
            delete(SearchDocument).where(
                SearchDocument.account_id == account_id,
                SearchDocument.item_id == item_id,
            )
        )
        return int(result.rowcount or 0)

    def list_documents(
        self, account_id: uuid.UUID, source: str | None
    ) -> list[SearchDocument]:
        query = select(SearchDocument).where(
            SearchDocument.account_id == account_id
        )
        if source:
            query = query.where(SearchDocument.source == source)
        return list(self.session.scalars(query.order_by(SearchDocument.item_id)))

    def get_request(
        self, token_id: uuid.UUID, idempotency_key: str
    ) -> SearchRequestRecord | None:
        return self.session.scalar(
            select(SearchRequestRecord).where(
                SearchRequestRecord.token_id == token_id,
                SearchRequestRecord.idempotency_key == idempotency_key,
            )
        )

    def lock_token(self, token_id: uuid.UUID) -> AppToken | None:
        return self.session.scalar(
            select(AppToken).where(AppToken.id == token_id).with_for_update()
        )

    def add_request(self, request: SearchRequestRecord) -> None:
        self.session.add(request)
