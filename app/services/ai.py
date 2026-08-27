import hashlib
import json
import math
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.model import AIModel, ModelResult
from app.models import AIJob, AIRequest
from app.repositories.ai_requests import AIRequestRepository
from app.schemas.ai import (
    ClassificationAssignmentOutput,
    ClassificationCandidateOutput,
    ClassificationRequest,
    ClassificationResponse,
    EnrichedItemResponse,
    EnrichmentModelOutput,
    EnrichmentRequest,
    EnrichmentResponse,
    OrganizationJobCreate,
    OrganizationJobResponse,
    TaxonomyMergeOutput,
    TaxonomyMergeRequest,
    TaxonomyMergeResponse,
    validate_classification_output,
    validate_enrichment_output,
    validate_taxonomy_merge_output,
)
from app.services.accounts import AuthenticatedAccount

ResponseT = TypeVar("ResponseT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)

CLASSIFICATION_PROMPT_VERSION = "classification-v3"
ENRICHMENT_PROMPT_VERSION = "enrichment-v2"
TAXONOMY_MERGE_PROMPT_VERSION = "taxonomy-merge-v2"
ORGANIZATION_JOB_CREDITS = 10


class AIQuotaExhaustedError(Exception):
    pass


class IdempotencyConflictError(Exception):
    pass


class RequestInProgressError(Exception):
    pass


class AIJobNotFoundError(Exception):
    pass


class AIJobLimitError(Exception):
    pass


class AIJobService:
    def __init__(self, session: Session, current: AuthenticatedAccount) -> None:
        self.session = session
        self.current = current
        self.repository = AIRequestRepository(session)

    def create(
        self, request: OrganizationJobCreate, idempotency_key: str
    ) -> OrganizationJobResponse:
        request_hash = _payload_hash(request)
        existing = self.repository.get_job_by_key(self.current.token.id, idempotency_key)
        if existing:
            if existing.request_hash != request_hash:
                raise IdempotencyConflictError
            return _job_response(existing)

        token = self.repository.lock_token(self.current.token.id)
        existing = self.repository.get_job_by_key(
            self.current.token.id, idempotency_key
        )
        if existing:
            if existing.request_hash != request_hash:
                self.session.rollback()
                raise IdempotencyConflictError
            self.session.rollback()
            return _job_response(existing)
        if token is None or token.total_quota - token.used_quota < ORGANIZATION_JOB_CREDITS:
            self.session.rollback()
            raise AIQuotaExhaustedError
        token.used_quota += ORGANIZATION_JOB_CREDITS
        token_id = token.id
        classification_limit = _classification_call_limit(
            len(request.classification_item_ids)
        )
        job = AIJob(
            token_id=token.id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            mode=request.mode,
            organization_instruction=request.organization_instruction,
            classification_item_ids=request.classification_item_ids,
            enrichment_item_ids=request.enrichment_item_ids,
            classification_call_limit=classification_limit,
            enrichment_call_limit=math.ceil(len(request.enrichment_item_ids) / 10),
            credits=ORGANIZATION_JOB_CREDITS,
        )
        self.repository.add_job(job)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self.repository.get_job_by_key(token_id, idempotency_key)
            if concurrent and concurrent.request_hash == request_hash:
                return _job_response(concurrent)
            raise IdempotencyConflictError from None
        return _job_response(job)


class AIService:
    def __init__(
        self,
        session: Session,
        current: AuthenticatedAccount,
        model: AIModel,
        job_id: uuid.UUID,
    ) -> None:
        self.session = session
        self.current = current
        self.model = model
        self.job_id = job_id
        self.repository = AIRequestRepository(session)

    def classify(
        self, request: ClassificationRequest, idempotency_key: str
    ) -> ClassificationResponse:
        return self._execute(
            operation="classify",
            idempotency_key=idempotency_key,
            payload=request,
            response_type=ClassificationResponse,
            invoke=lambda instruction: self.model.classify(request, instruction),
            build=lambda result, request_id: self._classification_response(
                request, result, request_id
            ),
            item_ids=[item.item_id for item in request.items],
        )

    def merge_taxonomies(
        self, request: TaxonomyMergeRequest, idempotency_key: str
    ) -> TaxonomyMergeResponse:
        return self._execute(
            operation="classify",
            idempotency_key=idempotency_key,
            payload=request,
            response_type=TaxonomyMergeResponse,
            invoke=lambda instruction: self.model.merge_taxonomies(request, instruction),
            build=lambda result, request_id: self._taxonomy_merge_response(
                request, result, request_id
            ),
            item_ids=[],
        )

    def enrich(
        self, request: EnrichmentRequest, idempotency_key: str
    ) -> EnrichmentResponse:
        return self._execute(
            operation="enrich",
            idempotency_key=idempotency_key,
            payload=request,
            response_type=EnrichmentResponse,
            invoke=lambda instruction: self.model.enrich(request, instruction),
            build=lambda result, request_id: self._enrichment_response(
                request, result, request_id
            ),
            item_ids=[item.item_id for item in request.items],
        )

    def _execute(
        self,
        *,
        operation: str,
        idempotency_key: str,
        payload: BaseModel,
        response_type: type[ResponseT],
        invoke: Callable[[str], ModelResult[OutputT]],
        build: Callable[[ModelResult[OutputT], uuid.UUID], ResponseT],
        item_ids: list[str],
    ) -> ResponseT:
        request_hash = _payload_hash(payload)
        existing = self.repository.get(
            self.current.token.id, operation, idempotency_key
        )
        if existing:
            cached = self._handle_existing(existing, request_hash, response_type)
            if cached is not None:
                return cached

        record, job = self._reserve(
            existing, operation, idempotency_key, request_hash, item_ids
        )
        started_at = perf_counter()
        try:
            result = invoke(job.organization_instruction)
            response = build(result, record.id)
        except Exception:
            self._release_failed(record.id, int((perf_counter() - started_at) * 1000))
            raise
        duration_ms = int((perf_counter() - started_at) * 1000)

        completed = self.repository.get(
            self.current.token.id, operation, idempotency_key
        )
        if completed is None:
            raise RuntimeError("AI 请求记录不存在")
        completed.status = "succeeded"
        completed.response_json = response.model_dump(mode="json")
        completed.provider = result.provider
        completed.model = result.model
        completed.input_tokens = result.usage.input_tokens
        completed.output_tokens = result.usage.output_tokens
        completed.duration_ms = duration_ms
        completed.error_code = None
        completed.completed_at = datetime.now(UTC)
        self.session.commit()
        return response

    def _handle_existing(
        self,
        record: AIRequest,
        request_hash: str,
        response_type: type[ResponseT],
    ) -> ResponseT | None:
        if record.request_hash != request_hash:
            raise IdempotencyConflictError
        if record.status == "succeeded" and record.response_json:
            return response_type.model_validate(record.response_json)
        if record.status == "pending":
            raise RequestInProgressError
        return None

    def _reserve(
        self,
        existing: AIRequest | None,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        item_ids: list[str],
    ) -> tuple[AIRequest, AIJob]:
        job = self.repository.get_job(self.job_id, self.current.token.id)
        if job is None:
            raise AIJobNotFoundError
        allowed_ids = set(
            job.classification_item_ids
            if operation == "classify"
            else job.enrichment_item_ids
        )
        if any(item_id not in allowed_ids for item_id in item_ids):
            raise AIJobLimitError
        if not existing:
            limit = (
                job.classification_call_limit
                if operation == "classify"
                else job.enrichment_call_limit
            )
            if self.repository.count_job_requests(job.id, operation) >= limit:
                raise AIJobLimitError

        if existing:
            existing.status = "pending"
            existing.error_code = None
            existing.completed_at = None
            existing.provider = self.model.provider_name
            existing.model = self.model.model_name
            record = existing
        else:
            record = AIRequest(
                token_id=self.current.token.id,
                job_id=job.id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                status="pending",
                provider=self.model.provider_name,
                model=self.model.model_name,
            )
            self.repository.add(record)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self.repository.get(self.current.token.id, operation, idempotency_key)
            if concurrent:
                if concurrent.request_hash != request_hash:
                    raise IdempotencyConflictError from None
                raise RequestInProgressError from None
            raise
        return record, job

    def _release_failed(self, request_id: uuid.UUID, duration_ms: int) -> None:
        self.session.rollback()
        record = self.session.get(AIRequest, request_id)
        if record:
            record.status = "failed"
            record.error_code = "model_request_failed"
            record.duration_ms = duration_ms
            record.completed_at = datetime.now(UTC)
        self.session.commit()

    @staticmethod
    def _classification_response(
        request: ClassificationRequest,
        result: ModelResult[
            ClassificationCandidateOutput | ClassificationAssignmentOutput
        ],
        request_id: uuid.UUID,
    ) -> ClassificationResponse:
        validate_classification_output(request, result.output)
        categories = (
            result.output.categories
            if isinstance(result.output, ClassificationCandidateOutput)
            else request.taxonomy or []
        )
        assignments = (
            result.output.assignments
            if isinstance(result.output, ClassificationAssignmentOutput)
            else []
        )
        return ClassificationResponse(
            categories=categories,
            assignments=assignments,
            mode="initial" if request.taxonomy is None else "incremental",
            phase=request.phase,
            provider=result.provider,
            model=result.model,
            prompt_version=CLASSIFICATION_PROMPT_VERSION,
            request_id=request_id,
            usage=result.usage,
        )

    @staticmethod
    def _taxonomy_merge_response(
        request: TaxonomyMergeRequest,
        result: ModelResult[TaxonomyMergeOutput],
        request_id: uuid.UUID,
    ) -> TaxonomyMergeResponse:
        validate_taxonomy_merge_output(request, result.output)
        return TaxonomyMergeResponse(
            categories=result.output.categories,
            provider=result.provider,
            model=result.model,
            prompt_version=TAXONOMY_MERGE_PROMPT_VERSION,
            request_id=request_id,
            usage=result.usage,
        )

    @staticmethod
    def _enrichment_response(
        request: EnrichmentRequest,
        result: ModelResult[EnrichmentModelOutput],
        request_id: uuid.UUID,
    ) -> EnrichmentResponse:
        validate_enrichment_output(request, result.output)
        requested = {item.item_id: item for item in request.items}
        order = {item.item_id: index for index, item in enumerate(request.items)}
        items = [
            EnrichedItemResponse(
                **item.model_dump(),
                content_fingerprint=requested[item.item_id].content_fingerprint,
                provider=result.provider,
                model=result.model,
                prompt_version=ENRICHMENT_PROMPT_VERSION,
                request_id=request_id,
            )
            for item in sorted(result.output.items, key=lambda item: order[item.item_id])
        ]
        return EnrichmentResponse(
            items=items,
            failures=sorted(result.output.failures, key=lambda item: order[item.item_id]),
            provider=result.provider,
            model=result.model,
            prompt_version=ENRICHMENT_PROMPT_VERSION,
            request_id=request_id,
            usage=result.usage,
        )


def _payload_hash(payload: BaseModel) -> str:
    serialized = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _classification_call_limit(item_count: int) -> int:
    chunks = math.ceil(item_count / 100)
    calls = chunks * 2
    while chunks > 1:
        chunks = math.ceil(chunks / 10)
        calls += chunks
    return calls


def _job_response(job: AIJob) -> OrganizationJobResponse:
    return OrganizationJobResponse(
        job_id=job.id,
        credits=job.credits,
        classification_call_limit=job.classification_call_limit,
        enrichment_call_limit=job.enrichment_call_limit,
    )
