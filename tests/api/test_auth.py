"""V2-T5 real HTTP credential/privacy and invalid bearer acceptance."""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.auth import service
from app.auth.security import AuthConfig, hash_password
from app.core.config import Settings
from app.main import create_app
from app.users.model import User, UserRole
from tests.conftest import TEST_SIGNING_KEY


@pytest.fixture(scope="module")
def auth_config() -> AuthConfig:
    return AuthConfig(
        signing_key=SecretStr(TEST_SIGNING_KEY),
        access_token_ttl_seconds=900,
        dummy_password_hash=SecretStr(hash_password(" private 密码 ")),
    )


@pytest.fixture
def http_auth(
    monkeypatch: pytest.MonkeyPatch,
    auth_config: AuthConfig,
) -> Iterator[tuple[TestClient, MagicMock, MagicMock, User]]:
    app = create_app(
        Settings(_env_file=None, database_url=SecretStr("unused")),
        auth_config=auth_config,
    )
    session = MagicMock(spec=Session)

    def override_session() -> Iterator[Session]:
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_session
    repo = MagicMock()
    monkeypatch.setattr(service, "UserRepository", MagicMock(return_value=repo))
    user = User(
        id=uuid4(),
        email="user@example.test",
        role=UserRole.VIEWER,
        is_active=True,
        password_hash=auth_config.dummy_password_hash.get_secret_value(),
        created_at=datetime.now(UTC),
    )
    repo.get_by_email.return_value = user
    repo.get.return_value = user
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client, repo, session, user
    finally:
        client.close()


def assert_private_error(response: Response, status_code: int) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "request_id"}
    assert response.headers["X-Request-ID"] == body["error"]["request_id"]
    if status_code == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_real_login_me_openapi_and_session_ownership(
    http_auth: tuple[TestClient, MagicMock, MagicMock, User],
) -> None:
    client, repo, session, user = http_auth
    result = client.post(
        "/api/v1/auth/login",
        json={
            "email": " USER@EXAMPLE.TEST ",
            "password": " private 密码 ",
        },
    )
    assert result.status_code == 200
    body = result.json()
    assert (
        set(body) == {"access_token", "token_type"} and body["token_type"] == "bearer"
    )
    repo.get_by_email.assert_called_once_with(user.email)
    token = body["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert set(me.json()) == {"id", "email", "role", "is_active", "created_at"}
    assert me.json()["id"] == str(user.id)
    assert "password_hash" not in me.text and me.json()["created_at"].endswith("Z")
    repo.get.assert_called_once_with(user.id)
    for method in ("add", "flush", "commit", "rollback"):
        getattr(session, method).assert_not_called()
    assert session.close.call_count == 2
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/api/v1/auth/me"]["get"]["security"] == [{"HTTPBearer": []}]
    assert "security" not in paths["/api/v1/auth/login"]["post"]


@pytest.mark.parametrize("case", ["missing", "wrong", "inactive", "malformed-hash"])
def test_login_denials_are_uniform(
    http_auth: tuple[TestClient, MagicMock, MagicMock, User],
    case: str,
) -> None:
    client, repo, _, user = http_auth
    if case == "missing":
        repo.get_by_email.return_value = None
    elif case == "inactive":
        user.is_active = False
    elif case == "malformed-hash":
        user.password_hash = "opaque"
    password = "wrong" if case == "wrong" else " private 密码 "
    response = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": password}
    )
    assert_private_error(response, 401)
    assert response.json()["error"]["message"] == "Unauthorized"


@pytest.mark.parametrize(
    "authorization", [None, "", "Basic abc", "Bearer", "Bearer ", "Bearer garbage"]
)
def test_missing_wrong_or_malformed_bearer_is_401(
    http_auth: tuple[TestClient, MagicMock, MagicMock, User],
    authorization: str | None,
) -> None:
    client, _, _, _ = http_auth
    headers = {} if authorization is None else {"Authorization": authorization}
    assert_private_error(client.get("/api/v1/auth/me", headers=headers), 401)


@pytest.mark.parametrize(
    "field,value", [("iat", []), ("exp", {}), ("iat", float("inf"))]
)
def test_ill_typed_signed_token_is_401_not_500(
    http_auth: tuple[TestClient, MagicMock, MagicMock, User],
    field: str,
    value: object,
) -> None:
    client, _, _, user = http_auth
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {
            "sub": str(user.id),
            "iat": now,
            "exp": now + 900,
            "token_type": "access",
            field: value,
        },
        TEST_SIGNING_KEY,
        algorithm="HS256",
    )
    assert_private_error(
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}), 401
    )


def test_validation_database_errors_and_logs_never_echo_secrets(
    http_auth: tuple[TestClient, MagicMock, MagicMock, User],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, repo, _, user = http_auth
    sentinel = "private-review-password-sentinel"
    logger = logging.getLogger("app.requests")
    logger.addHandler(caplog.handler)
    try:
        invalid = client.post(
            "/api/v1/auth/login",
            json={
                "email": user.email,
                "password": sentinel,
                "unexpected": sentinel,
            },
            headers={"X-Request-ID": "auth-private-review"},
        )
        assert_private_error(invalid, 422)
        repo.get_by_email.side_effect = OperationalError(
            sentinel, {}, Exception(sentinel)
        )
        failed = client.post(
            "/api/v1/auth/login",
            json={
                "email": user.email,
                "password": sentinel,
            },
            headers={"X-Request-ID": "auth-private-review"},
        )
        assert_private_error(failed, 500)
        assert sentinel not in invalid.text + failed.text + caplog.text
        assert TEST_SIGNING_KEY not in caplog.text
        assert user.password_hash not in invalid.text + failed.text + caplog.text
    finally:
        logger.removeHandler(caplog.handler)
