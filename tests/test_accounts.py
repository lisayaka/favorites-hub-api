from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import AppToken, CreditRecharge

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


def create_account(client: TestClient, email: str = "User@Example.com") -> dict:
    response = client.post(
        "/v1/admin/accounts",
        headers=ADMIN_HEADERS,
        json={
            "email": email,
            "expires_in_days": 14,
            "total_quota": 200,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_admin_can_create_and_list_account(
    client: TestClient, db_session: Session
) -> None:
    unauthorized = client.get("/v1/admin/accounts")
    assert unauthorized.status_code == 401

    created = create_account(client)
    assert created["account"]["email"] == "user@example.com"
    assert created["app_token"].startswith("fh_trial_")
    assert created["account"]["tokens"][0]["total_quota"] == 200

    stored_token = db_session.scalar(select(AppToken))
    assert stored_token is not None
    assert stored_token.token_hash != created["app_token"]
    assert stored_token.prefix in created["app_token"]

    listed = client.get("/v1/admin/accounts", headers=ADMIN_HEADERS)
    assert listed.status_code == 200
    assert [account["email"] for account in listed.json()] == ["user@example.com"]


def test_duplicate_email_is_rejected_case_insensitively(client: TestClient) -> None:
    create_account(client)

    response = client.post(
        "/v1/admin/accounts",
        headers=ADMIN_HEADERS,
        json={"email": "user@example.COM"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "account_email_exists"


def test_app_token_can_read_account_then_stops_after_revoke(client: TestClient) -> None:
    created = create_account(client)
    account_id = created["account"]["id"]
    token = created["app_token"]

    current = client.get(
        "/v1/account/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert current.status_code == 200
    assert current.json()["email"] == "user@example.com"
    assert current.json()["token"]["last_used_at"] is not None

    revoked = client.post(
        f"/v1/admin/accounts/{account_id}/revoke", headers=ADMIN_HEADERS
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["tokens"][0]["status"] == "revoked"

    rejected = client.get(
        "/v1/account/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert rejected.status_code == 401
    assert rejected.json()["detail"]["code"] == "invalid_app_token"


def test_expired_app_token_is_rejected(
    client: TestClient, db_session: Session
) -> None:
    created = create_account(client)
    token = db_session.scalar(select(AppToken))
    assert token is not None
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    response = client.get(
        "/v1/account/me",
        headers={"Authorization": f"Bearer {created['app_token']}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_app_token"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic credentials"},
        {"Authorization": "Bearer invalid-token"},
    ],
)
def test_missing_or_invalid_app_token_is_rejected(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.get("/v1/account/me", headers=headers)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_app_token"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_exhausted_app_token_can_read_account_state(
    client: TestClient, db_session: Session
) -> None:
    created = create_account(client)
    token = db_session.scalar(select(AppToken))
    assert token is not None
    token.used_quota = token.total_quota
    db_session.commit()

    response = client.get(
        "/v1/account/me",
        headers={"Authorization": f"Bearer {created['app_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["token"]["used_quota"] == token.total_quota


def test_admin_can_recharge_exhausted_account_idempotently(
    client: TestClient, db_session: Session
) -> None:
    created = create_account(client)
    account_id = created["account"]["id"]
    token = db_session.scalar(select(AppToken))
    assert token is not None
    token.used_quota = token.total_quota
    db_session.commit()
    headers = {**ADMIN_HEADERS, "Idempotency-Key": "recharge-001"}

    charged = client.post(
        f"/v1/admin/accounts/{account_id}/credits",
        headers=headers,
        json={"credits": 25},
    )
    replayed = client.post(
        f"/v1/admin/accounts/{account_id}/credits",
        headers=headers,
        json={"credits": 25},
    )

    assert charged.status_code == 200
    assert replayed.status_code == 200
    assert charged.json()["total_quota"] == 225
    assert charged.json()["used_quota"] == 200
    assert charged.json()["remaining_quota"] == 25
    assert replayed.json()["id"] == charged.json()["id"]
    assert token.total_quota == 225
    assert len(list(db_session.scalars(select(CreditRecharge)))) == 1

    conflict = client.post(
        f"/v1/admin/accounts/{account_id}/credits",
        headers=headers,
        json={"credits": 30},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_key_conflict"


def test_admin_cannot_recharge_expired_account(
    client: TestClient, db_session: Session
) -> None:
    created = create_account(client)
    token = db_session.scalar(select(AppToken))
    assert token is not None
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    response = client.post(
        f"/v1/admin/accounts/{created['account']['id']}/credits",
        headers={**ADMIN_HEADERS, "Idempotency-Key": "recharge-expired"},
        json={"credits": 25},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "account_not_rechargeable"


def test_admin_api_is_unavailable_without_configured_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ADMIN_API_KEY")

    response = client.get("/v1/admin/accounts", headers=ADMIN_HEADERS)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "admin_api_key_not_configured"


def test_configured_extension_origin_can_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = "chrome-extension://abcdefghijklmnop"
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", f"{origin}/,{origin}")

    with TestClient(create_app()) as cors_client:
        allowed = cors_client.options(
            "/v1/account/me",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        denied = cors_client.options(
            "/v1/account/me",
            headers={
                "Origin": "chrome-extension://untrusted",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == origin
    assert "Access-Control-Allow-Origin" not in denied.headers


def test_cors_origin_wildcard_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")

    with pytest.raises(RuntimeError, match="禁止使用通配符"):
        create_app()
