import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.model import AIModel
from app.models import SearchDocument, SearchRequestRecord
from app.repositories.search import SearchRepository
from app.schemas.ai import Usage
from app.schemas.search import (
    SearchDocumentInput,
    SearchIndexReplace,
    SearchIndexResponse,
    SearchModelRequest,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from app.services.accounts import AuthenticatedAccount
from app.services.ai import (
    AIQuotaExhaustedError,
    IdempotencyConflictError,
    RequestInProgressError,
)

SEARCH_CREDITS = 2
SEARCH_PROMPT_VERSION = "search-v2"
SEARCH_BATCH_SIZE = int(os.getenv("AI_SEARCH_BATCH_SIZE", "40"))
if not 1 <= SEARCH_BATCH_SIZE <= 100:
    raise RuntimeError("AI_SEARCH_BATCH_SIZE 必须为 1～100")


class SearchIndexEmptyError(Exception):
    pass


class SearchIndexService:
    def __init__(self, session: Session, current: AuthenticatedAccount) -> None:
        self.session = session
        self.current = current
        self.repository = SearchRepository(session)

    def replace(self, request: SearchIndexReplace) -> SearchIndexResponse:
        documents = [
            SearchDocument(
                account_id=self.current.account.id,
                **item.model_dump(mode="python"),
            )
            for item in request.items
        ]
        self.repository.replace_documents(self.current.account.id, documents)
        self.session.commit()
        return SearchIndexResponse(indexed=len(documents))

    def delete(self, item_id: str) -> None:
        self.repository.delete_document(self.current.account.id, item_id)
        self.session.commit()


class SearchService:
    def __init__(
        self,
        session: Session,
        current: AuthenticatedAccount,
        model: AIModel,
    ) -> None:
        self.session = session
        self.current = current
        self.model = model
        self.repository = SearchRepository(session)

    def search(
        self, request: SearchRequest, idempotency_key: str
    ) -> SearchResponse:
        request_hash = _payload_hash(request)
        existing = self.repository.get_request(
            self.current.token.id, idempotency_key
        )
        cached = _handle_existing(existing, request_hash)
        if cached is not None:
            return cached

        documents = self.repository.list_documents(
            self.current.account.id, request.source
        )
        if not documents:
            raise SearchIndexEmptyError

        record, concurrent_response = self._reserve(idempotency_key, request_hash)
        if concurrent_response is not None:
            return concurrent_response
        started_at = perf_counter()
        try:
            response, provider_name, model_name, usage = self._invoke_batches(
                request, documents, record.id
            )
        except Exception:
            self._release_failed(record.id, int((perf_counter() - started_at) * 1000))
            raise

        completed = self.repository.get_request(
            self.current.token.id, idempotency_key
        )
        if completed is None:
            raise RuntimeError("搜索请求记录不存在")
        completed.status = "succeeded"
        completed.response_json = response.model_dump(mode="json")
        completed.provider = provider_name
        completed.model = model_name
        completed.input_tokens = usage.input_tokens
        completed.output_tokens = usage.output_tokens
        completed.duration_ms = int((perf_counter() - started_at) * 1000)
        completed.error_code = None
        completed.completed_at = datetime.now(UTC)
        self.session.commit()
        return response

    def _reserve(
        self,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[SearchRequestRecord, SearchResponse | None]:
        token = self.repository.lock_token(self.current.token.id)
        existing = self.repository.get_request(
            self.current.token.id, idempotency_key
        )
        cached = _handle_existing(existing, request_hash)
        if cached is not None:
            self.session.rollback()
            return existing, cached

        if existing:
            existing.status = "pending"
            existing.error_code = None
            existing.completed_at = None
            existing.provider = self.model.provider_name
            existing.model = self.model.model_name
            record = existing
        else:
            if token is None or token.total_quota - token.used_quota < SEARCH_CREDITS:
                self.session.rollback()
                raise AIQuotaExhaustedError
            token.used_quota += SEARCH_CREDITS
            record = SearchRequestRecord(
                token_id=self.current.token.id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                status="pending",
                provider=self.model.provider_name,
                model=self.model.model_name,
                credits=SEARCH_CREDITS,
            )
            self.repository.add_request(record)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self.repository.get_request(
                self.current.token.id, idempotency_key
            )
            if concurrent and concurrent.request_hash != request_hash:
                raise IdempotencyConflictError from None
            raise RequestInProgressError from None
        return record, None

    def _invoke_batches(
        self,
        request: SearchRequest,
        documents: list[SearchDocument],
        request_id: uuid.UUID,
    ) -> tuple[SearchResponse, str, str, Usage]:
        best_by_id: dict[str, SearchResultItem] = {}
        input_tokens = 0
        output_tokens = 0
        provider_name = self.model.provider_name
        model_name = self.model.model_name

        for start in range(0, len(documents), SEARCH_BATCH_SIZE):
            batch = documents[start : start + SEARCH_BATCH_SIZE]
            model_request = SearchModelRequest(
                query=request.query,
                limit=request.limit,
                documents=[_document_input(document) for document in batch],
            )
            result = self.model.search(model_request)
            _validate_model_results(model_request, result.output.results)
            provider_name = result.provider
            model_name = result.model
            input_tokens += result.usage.input_tokens
            output_tokens += result.usage.output_tokens
            for item in result.output.results:
                existing = best_by_id.get(item.item_id)
                if existing is None or item.score > existing.score:
                    best_by_id[item.item_id] = item

        usage = Usage(input_tokens=input_tokens, output_tokens=output_tokens)
        results = sorted(
            best_by_id.values(), key=lambda item: item.score, reverse=True
        )[: request.limit]
        return (
            SearchResponse(
                results=results,
                provider=provider_name,
                model=model_name,
                prompt_version=SEARCH_PROMPT_VERSION,
                request_id=request_id,
                usage=usage,
                credits=SEARCH_CREDITS,
            ),
            provider_name,
            model_name,
            usage,
        )

    def _release_failed(self, request_id: uuid.UUID, duration_ms: int) -> None:
        self.session.rollback()
        record = self.session.get(SearchRequestRecord, request_id)
        if record:
            record.status = "failed"
            record.error_code = "model_request_failed"
            record.duration_ms = duration_ms
            record.completed_at = datetime.now(UTC)
        self.session.commit()


def _handle_existing(
    record: SearchRequestRecord | None, request_hash: str
) -> SearchResponse | None:
    if record is None:
        return None
    if record.request_hash != request_hash:
        raise IdempotencyConflictError
    if record.status == "succeeded" and record.response_json:
        return SearchResponse.model_validate(record.response_json)
    if record.status == "pending":
        raise RequestInProgressError
    return None


def _document_input(document: SearchDocument) -> SearchDocumentInput:
    return SearchDocumentInput(
        item_id=document.item_id,
        source=document.source,
        title=document.title,
        summary=document.summary,
        tags=document.tags,
        category_path=document.category_path,
        content_fingerprint=document.content_fingerprint,
    )


def _validate_model_results(
    request: SearchModelRequest, results: list[SearchResultItem]
) -> None:
    allowed_ids = {document.item_id for document in request.documents}
    item_ids = [item.item_id for item in results]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("搜索结果 item_id 不得重复")
    if any(item_id not in allowed_ids for item_id in item_ids):
        raise ValueError("搜索结果引用了不存在的 item_id")


def _payload_hash(payload: SearchRequest) -> str:
    serialized = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
