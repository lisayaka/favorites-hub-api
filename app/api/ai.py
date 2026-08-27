from functools import lru_cache
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.dependencies import CurrentAccountDependency, SessionDependency
from app.integrations.model import (
    AIModel,
    ModelConfigurationError,
    ModelInvocationError,
    create_model_from_env,
)
from app.schemas.ai import (
    ClassificationRequest,
    ClassificationResponse,
    EnrichmentRequest,
    EnrichmentResponse,
    OrganizationJobCreate,
    OrganizationJobResponse,
    TaxonomyMergeRequest,
    TaxonomyMergeResponse,
)
from app.services.ai import (
    AIJobLimitError,
    AIJobNotFoundError,
    AIJobService,
    AIQuotaExhaustedError,
    AIService,
    IdempotencyConflictError,
    RequestInProgressError,
)

router = APIRouter(prefix="/v1/ai", tags=["ai"])


@lru_cache
def get_model() -> AIModel:
    try:
        return create_model_from_env()
    except ModelConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "model_not_configured"},
        ) from None


ModelDependency = Annotated[AIModel, Depends(get_model)]
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=64)
]
AIJobId = Annotated[uuid.UUID, Header(alias="AI-Job-Id")]


@router.post("/jobs", response_model=OrganizationJobResponse)
def create_job(
    payload: OrganizationJobCreate,
    idempotency_key: IdempotencyKey,
    session: SessionDependency,
    current: CurrentAccountDependency,
) -> OrganizationJobResponse:
    return _call(
        lambda: AIJobService(session, current).create(payload, idempotency_key)
    )


@router.post("/classify", response_model=ClassificationResponse)
def classify(
    payload: ClassificationRequest,
    idempotency_key: IdempotencyKey,
    job_id: AIJobId,
    session: SessionDependency,
    current: CurrentAccountDependency,
    model: ModelDependency,
) -> ClassificationResponse:
    return _call(
        lambda: AIService(session, current, model, job_id).classify(
            payload, idempotency_key
        )
    )


@router.post("/classify/merge", response_model=TaxonomyMergeResponse)
def merge_taxonomies(
    payload: TaxonomyMergeRequest,
    idempotency_key: IdempotencyKey,
    job_id: AIJobId,
    session: SessionDependency,
    current: CurrentAccountDependency,
    model: ModelDependency,
) -> TaxonomyMergeResponse:
    return _call(
        lambda: AIService(session, current, model, job_id).merge_taxonomies(
            payload, idempotency_key
        )
    )


@router.post("/enrich", response_model=EnrichmentResponse)
def enrich(
    payload: EnrichmentRequest,
    idempotency_key: IdempotencyKey,
    job_id: AIJobId,
    session: SessionDependency,
    current: CurrentAccountDependency,
    model: ModelDependency,
) -> EnrichmentResponse:
    return _call(
        lambda: AIService(session, current, model, job_id).enrich(
            payload, idempotency_key
        )
    )


def _call(operation):
    try:
        return operation()
    except AIQuotaExhaustedError:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "quota_exhausted"},
        ) from None
    except IdempotencyConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "idempotency_key_conflict"},
        ) from None
    except RequestInProgressError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "request_in_progress"},
        ) from None
    except AIJobNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ai_job_not_found"},
        ) from None
    except AIJobLimitError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ai_job_limit_exceeded"},
        ) from None
    except ModelConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "model_not_configured"},
        ) from None
    except (ModelInvocationError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "model_response_invalid"},
        ) from None
