from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from app.api.ai import get_model
from app.api.dependencies import CurrentAccountDependency, SessionDependency
from app.integrations.model import (
    AIModel,
    ModelConfigurationError,
    ModelInvocationError,
)
from app.schemas.search import (
    SearchIndexReplace,
    SearchIndexResponse,
    SearchRequest,
    SearchResponse,
)
from app.services.ai import (
    AIQuotaExhaustedError,
    IdempotencyConflictError,
    RequestInProgressError,
)
from app.services.search import (
    SearchIndexEmptyError,
    SearchIndexService,
    SearchService,
)

index_router = APIRouter(prefix="/v1/index", tags=["search"])
router = APIRouter(prefix="/v1", tags=["search"])
ModelDependency = Annotated[AIModel, Depends(get_model)]
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=64)
]


@index_router.put("/items", response_model=SearchIndexResponse)
def replace_index(
    payload: SearchIndexReplace,
    session: SessionDependency,
    current: CurrentAccountDependency,
) -> SearchIndexResponse:
    return SearchIndexService(session, current).replace(payload)


@index_router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_index_item(
    item_id: str,
    session: SessionDependency,
    current: CurrentAccountDependency,
) -> Response:
    SearchIndexService(session, current).delete(item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/search", response_model=SearchResponse)
def search(
    payload: SearchRequest,
    idempotency_key: IdempotencyKey,
    session: SessionDependency,
    current: CurrentAccountDependency,
    model: ModelDependency,
) -> SearchResponse:
    try:
        return SearchService(session, current, model).search(payload, idempotency_key)
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
    except SearchIndexEmptyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "search_index_empty"},
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
