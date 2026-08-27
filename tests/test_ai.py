from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.ai import get_model
from app.integrations.model import ModelResult
from app.main import app
from app.models import AIJob, AIRequest, AppToken
from app.schemas.ai import (
    Category,
    CategoryAssignment,
    ClassificationAssignmentOutput,
    ClassificationCandidateOutput,
    EnrichedItem,
    EnrichmentFailure,
    EnrichmentModelOutput,
    TaxonomyMergeOutput,
    Usage,
)

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


class FakeModel:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self) -> None:
        self.calls = 0
        self.organization_instructions = []

    def classify(self, request, organization_instruction=""):
        self.calls += 1
        self.organization_instructions.append(organization_instruction)
        categories = list(request.taxonomy or []) or [
            Category(category_id="tech", name="技术", level=1)
        ]
        if request.phase == "candidate" and request.taxonomy is not None:
            categories.append(
                Category(
                    category_id="tech-ai",
                    name="人工智能",
                    parent_id="tech",
                    level=2,
                )
            )
        output = (
            ClassificationAssignmentOutput(
                assignments=[
                    CategoryAssignment(
                        item_id=item.item_id,
                        category_id=categories[-1].category_id,
                    )
                    for item in request.items
                ]
            )
            if request.phase == "assign"
            else ClassificationCandidateOutput(categories=categories)
        )
        return ModelResult(
            output=output,
            provider=self.provider_name,
            model=self.model_name,
            usage=Usage(input_tokens=12, output_tokens=7),
        )

    def merge_taxonomies(self, request, organization_instruction=""):
        self.calls += 1
        self.organization_instructions.append(organization_instruction)
        categories = list(request.base_taxonomy or request.candidates[0])
        return ModelResult(
            output=TaxonomyMergeOutput(categories=categories),
            provider=self.provider_name,
            model=self.model_name,
            usage=Usage(input_tokens=15, output_tokens=5),
        )

    def enrich(self, request, organization_instruction=""):
        self.calls += 1
        self.organization_instructions.append(organization_instruction)
        first, *rest = request.items
        return ModelResult(
            output=EnrichmentModelOutput(
                items=[
                    EnrichedItem(
                        item_id=first.item_id,
                        summary="来自输入证据的摘要",
                        tags=["技术", "AI"],
                        category_id=first.assigned_category_id,
                    )
                ],
                failures=[
                    EnrichmentFailure(
                        item_id=item.item_id,
                        code="insufficient_evidence",
                        message="证据不足",
                    )
                    for item in rest
                ],
            ),
            provider=self.provider_name,
            model=self.model_name,
            usage=Usage(input_tokens=20, output_tokens=9),
        )


def create_token(client: TestClient, *, quota: int = 20) -> str:
    response = client.post(
        "/v1/admin/accounts",
        headers=ADMIN_HEADERS,
        json={
            "email": "ai-user@example.com",
            "expires_in_days": 14,
            "total_quota": quota,
        },
    )
    assert response.status_code == 201
    return response.json()["app_token"]


def classification_item(item_id: str = "bilibili:BV1") -> dict:
    return {
        "item_id": item_id,
        "source": "bilibili",
        "title": "LangChain 入门",
        "author": "作者",
        "content_type": "video",
        "source_text": "介绍结构化输出",
        "evidence_level": "metadata",
    }


def auth(token: str, key: str, job_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}
    if job_id:
        headers["AI-Job-Id"] = job_id
    return headers


def create_job(
    client: TestClient,
    token: str,
    *,
    classification_ids: list[str],
    enrichment_ids: list[str],
    organization_instruction: str = "",
    key: str = "organization-job-1",
) -> dict:
    response = client.post(
        "/v1/ai/jobs",
        headers=auth(token, key),
        json={
            "mode": "all",
            "organization_instruction": organization_instruction,
            "classification_item_ids": classification_ids,
            "enrichment_item_ids": enrichment_ids,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_job_deducts_ten_once_and_accepts_entire_collection(
    client: TestClient, db_session: Session
) -> None:
    token = create_token(client)
    item_ids = [f"item:{index}" for index in range(250)]
    first = create_job(
        client,
        token,
        classification_ids=item_ids,
        enrichment_ids=item_ids,
    )
    repeated = create_job(
        client,
        token,
        classification_ids=item_ids,
        enrichment_ids=item_ids,
    )

    assert repeated == first
    assert first["credits"] == 10
    assert first["classification_call_limit"] == 7
    assert first["enrichment_call_limit"] == 25
    stored_token = db_session.scalar(select(AppToken))
    assert stored_token is not None and stored_token.used_quota == 10
    assert len(list(db_session.scalars(select(AIJob)))) == 1


def test_classify_assign_and_enrich_do_not_charge_again(
    client: TestClient, db_session: Session
) -> None:
    token = create_token(client)
    fake = FakeModel()
    app.dependency_overrides[get_model] = lambda: fake
    item_id = "bilibili:BV1"
    job = create_job(
        client,
        token,
        classification_ids=[item_id],
        enrichment_ids=[item_id],
        organization_instruction="风格活泼，可适量添加颜文字",
    )
    job_id = job["job_id"]

    candidate_payload = {
        "phase": "candidate",
        "taxonomy": None,
        "items": [classification_item(item_id)],
    }
    candidate = client.post(
        "/v1/ai/classify",
        headers=auth(token, "candidate-call-1", job_id),
        json=candidate_payload,
    )
    repeated = client.post(
        "/v1/ai/classify",
        headers=auth(token, "candidate-call-1", job_id),
        json=candidate_payload,
    )
    assert candidate.status_code == 200
    assert repeated.json() == candidate.json()
    assert candidate.json()["assignments"] == []

    taxonomy = candidate.json()["categories"]
    assigned = client.post(
        "/v1/ai/classify",
        headers=auth(token, "assign-call-1", job_id),
        json={
            "phase": "assign",
            "taxonomy": taxonomy,
            "items": [classification_item(item_id)],
        },
    )
    assert assigned.status_code == 200
    assert assigned.json()["categories"] == taxonomy

    enriched = client.post(
        "/v1/ai/enrich",
        headers=auth(token, "enrich-call-1", job_id),
        json={
            "taxonomy": taxonomy,
            "items": [
                {
                    **classification_item(item_id),
                    "assigned_category_id": "tech",
                    "content_fingerprint": "a" * 64,
                }
            ],
        },
    )
    assert enriched.status_code == 200
    assert enriched.json()["provider"] == "fake"
    assert enriched.json()["items"][0]["category_id"] == "tech"
    assert fake.calls == 3
    assert fake.organization_instructions == ["风格活泼，可适量添加颜文字"] * 3
    stored_token = db_session.scalar(select(AppToken))
    assert stored_token is not None and stored_token.used_quota == 10
    assert all(
        request.quota_units == 0
        for request in db_session.scalars(select(AIRequest))
    )


def test_recursive_merge_uses_classification_job_budget(client: TestClient) -> None:
    token = create_token(client)
    fake = FakeModel()
    app.dependency_overrides[get_model] = lambda: fake
    item_ids = [f"item:{index}" for index in range(101)]
    job = create_job(
        client,
        token,
        classification_ids=item_ids,
        enrichment_ids=[item_ids[0]],
    )
    response = client.post(
        "/v1/ai/classify/merge",
        headers=auth(token, "merge-call-1", job["job_id"]),
        json={
            "base_taxonomy": None,
            "candidates": [
                [{"category_id": "tech", "name": "技术", "level": 1}],
                [{"category_id": "life", "name": "生活", "level": 1}],
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["categories"][0]["category_id"] == "tech"


def test_job_rejects_unregistered_items_and_excess_calls(client: TestClient) -> None:
    token = create_token(client)
    fake = FakeModel()
    app.dependency_overrides[get_model] = lambda: fake
    job = create_job(
        client,
        token,
        classification_ids=["bilibili:BV1"],
        enrichment_ids=["bilibili:BV1"],
    )
    unknown = client.post(
        "/v1/ai/classify",
        headers=auth(token, "unknown-item-call", job["job_id"]),
        json={"items": [classification_item("douyin:unknown")]},
    )
    assert unknown.status_code == 409
    assert unknown.json()["detail"]["code"] == "ai_job_limit_exceeded"

    payload = {"items": [classification_item()]}
    assert client.post(
        "/v1/ai/classify",
        headers=auth(token, "within-limit-one", job["job_id"]),
        json=payload,
    ).status_code == 200
    assert client.post(
        "/v1/ai/classify",
        headers=auth(token, "within-limit-two", job["job_id"]),
        json=payload,
    ).status_code == 200
    exceeded = client.post(
        "/v1/ai/classify",
        headers=auth(token, "over-limit-three", job["job_id"]),
        json=payload,
    )
    assert exceeded.status_code == 409


def test_idempotency_conflict_keeps_job_charge(
    client: TestClient, db_session: Session
) -> None:
    token = create_token(client)
    create_job(
        client,
        token,
        classification_ids=["item:1"],
        enrichment_ids=["item:1"],
        key="shared-job-key",
    )
    conflict = client.post(
        "/v1/ai/jobs",
        headers=auth(token, "shared-job-key"),
        json={
            "mode": "selected",
            "classification_item_ids": ["item:2"],
            "enrichment_item_ids": ["item:2"],
        },
    )
    assert conflict.status_code == 409
    stored_token = db_session.scalar(select(AppToken))
    assert stored_token is not None and stored_token.used_quota == 10


def test_quota_exhaustion_happens_when_creating_job(client: TestClient) -> None:
    token = create_token(client, quota=9)
    exhausted = client.post(
        "/v1/ai/jobs",
        headers=auth(token, "insufficient-job"),
        json={
            "mode": "all",
            "classification_item_ids": ["item:1"],
            "enrichment_item_ids": ["item:1"],
        },
    )
    assert exhausted.status_code == 402
    assert exhausted.json()["detail"]["code"] == "quota_exhausted"

    current = client.get(
        "/v1/account/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert current.status_code == 200
    assert current.json()["token"]["used_quota"] == 0
