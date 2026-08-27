from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.ai import get_model
from app.integrations.model import ModelResult
from app.main import app
from app.models import Account, AppToken, SearchDocument
from app.schemas.ai import Usage
from app.schemas.search import SearchModelOutput, SearchResultItem

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


class FakeSearchModel:
    provider_name = "fake"
    model_name = "fake-search-model"

    def __init__(self) -> None:
        self.calls = 0
        self.batch_sizes = []

    def search(self, request):
        self.calls += 1
        self.batch_sizes.append(len(request.documents))
        matches = [
            document
            for document in request.documents
            if "美甲" in document.title
            or "美甲" in document.summary
            or "美甲" in document.tags
        ][: request.limit]
        return ModelResult(
            output=SearchModelOutput(
                results=[
                    SearchResultItem(
                        item_id=document.item_id,
                        score=0.95,
                        reason="标题或整理信息与美甲款式相关",
                    )
                    for document in matches
                ]
            ),
            provider=self.provider_name,
            model=self.model_name,
            usage=Usage(input_tokens=10, output_tokens=5),
        )


def create_token(
    client: TestClient, *, email: str = "search-user@example.com", quota: int = 20
) -> str:
    response = client.post(
        "/v1/admin/accounts",
        headers=ADMIN_HEADERS,
        json={
            "email": email,
            "expires_in_days": 14,
            "total_quota": quota,
        },
    )
    assert response.status_code == 201
    return response.json()["app_token"]


def auth(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def index_items(client: TestClient, token: str, count: int = 2) -> None:
    items = [
        {
            "item_id": f"note:{index}",
            "source": "xiaohongshu",
            "title": "夏日美甲款式" if index == 0 else f"普通收藏 {index}",
            "summary": "适合短甲的清透配色" if index == 0 else "其他内容",
            "tags": ["美甲"] if index == 0 else ["其他"],
            "category_path": ["生活", "美妆"],
        }
        for index in range(count)
    ]
    response = client.put(
        "/v1/index/items", headers=auth(token), json={"items": items}
    )
    assert response.status_code == 200
    assert response.json() == {"indexed": count}


def test_search_replaces_index_and_deducts_two_credits_once(
    client: TestClient, db_session: Session
) -> None:
    token = create_token(client)
    model = FakeSearchModel()
    app.dependency_overrides[get_model] = lambda: model
    index_items(client, token)

    payload = {"query": "找出美甲款式的相关笔记", "limit": 10}
    first = client.post(
        "/v1/search", headers=auth(token, "search-request-1"), json=payload
    )
    replay = client.post(
        "/v1/search", headers=auth(token, "search-request-1"), json=payload
    )

    assert first.status_code == 200
    assert first.json()["provider"] == "fake"
    assert first.json()["credits"] == 2
    assert first.json()["results"][0]["item_id"] == "note:0"
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert model.calls == 1
    assert db_session.scalar(select(AppToken)).used_quota == 2


def test_search_chunks_entire_index(client: TestClient) -> None:
    token = create_token(client)
    model = FakeSearchModel()
    app.dependency_overrides[get_model] = lambda: model
    index_items(client, token, count=138)

    response = client.post(
        "/v1/search",
        headers=auth(token, "search-entire-index"),
        json={"query": "美甲相关内容", "limit": 10},
    )

    assert response.status_code == 200
    assert model.calls == 4
    assert model.batch_sizes == [40, 40, 40, 18]
    assert [item["item_id"] for item in response.json()["results"]] == ["note:0"]


def test_search_rejects_conflicting_key_and_insufficient_quota(
    client: TestClient, db_session: Session
) -> None:
    token = create_token(client, quota=2)
    model = FakeSearchModel()
    app.dependency_overrides[get_model] = lambda: model
    index_items(client, token)
    headers = auth(token, "search-conflict-key")

    assert client.post(
        "/v1/search", headers=headers, json={"query": "美甲笔记"}
    ).status_code == 200
    conflict = client.post(
        "/v1/search", headers=headers, json={"query": "编程笔记"}
    )
    exhausted = client.post(
        "/v1/search",
        headers=auth(token, "search-second-key"),
        json={"query": "编程笔记"},
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_key_conflict"
    assert exhausted.status_code == 402
    assert db_session.scalar(select(AppToken)).used_quota == 2


def test_search_index_is_account_isolated_and_empty_search_is_free(
    client: TestClient, db_session: Session
) -> None:
    first_token = create_token(client, email="first@example.com")
    second_token = create_token(client, email="second@example.com")
    app.dependency_overrides[get_model] = lambda: FakeSearchModel()
    index_items(client, first_token)

    response = client.post(
        "/v1/search",
        headers=auth(second_token, "search-empty-index"),
        json={"query": "美甲笔记"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "search_index_empty"
    tokens = list(db_session.scalars(select(AppToken)))
    assert [token.used_quota for token in tokens] == [0, 0]
    second_account = db_session.scalar(
        select(Account).where(Account.email == "second@example.com")
    )
    assert db_session.scalar(select(SearchDocument).where(
        SearchDocument.account_id == second_account.id
    )) is None
