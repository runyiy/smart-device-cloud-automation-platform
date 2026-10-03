"""V2-T5 fresh-request identity acceptance on guarded migrated PostgreSQL."""

from collections.abc import Iterator
from datetime import UTC

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.auth.security import AuthConfig, hash_password
from app.core.config import Environment, Settings
from app.main import create_app
from app.users.model import User, UserRole
from tests.conftest import TEST_SIGNING_KEY
from tests.integration.test_devices import device_engine as device_engine
from tests.integration.test_migrations import validate_test_database


@pytest.fixture(scope="module")
def password_hash() -> str:
    return hash_password("  trusted test 密码  ")


@pytest.fixture
def auth_client(
    device_engine: Engine,
    password_hash: str,
) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(device_engine.url.render_as_string(hide_password=False)),
        jwt_secret_key=SecretStr(TEST_SIGNING_KEY),
    )
    validate_test_database(settings)
    app = create_app(
        settings,
        auth_config=AuthConfig(
            signing_key=SecretStr(TEST_SIGNING_KEY),
            access_token_ttl_seconds=900,
            dummy_password_hash=SecretStr(password_hash),
        ),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def seed_user(engine: Engine, password_hash: str, role: UserRole) -> User:
    with Session(engine, expire_on_commit=False) as session:
        user = User(email="a@example.test", password_hash=password_hash, role=role)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def login_token(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": " A@EXAMPLE.TEST ",
            "password": "  trusted test 密码  ",
        },
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert isinstance(token, str)
    return token


@pytest.mark.parametrize("role", list(UserRole))
def test_real_persisted_users_login_and_me_without_writes(
    device_engine: Engine,
    password_hash: str,
    auth_client: TestClient,
    role: UserRole,
) -> None:
    user = seed_user(device_engine, password_hash, role)
    with Session(device_engine) as observer:
        before = observer.execute(select(User.__table__)).one()
    token = login_token(auth_client)
    me = auth_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200
    assert me.json() == {
        "id": str(user.id),
        "email": user.email,
        "role": role.value,
        "is_active": True,
        "created_at": user.created_at.astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    with Session(device_engine) as observer:
        assert observer.execute(select(User.__table__)).one() == before


def test_committed_role_deactivation_and_deletion_apply_to_fresh_requests(
    device_engine: Engine,
    password_hash: str,
    auth_client: TestClient,
) -> None:
    user = seed_user(device_engine, password_hash, UserRole.VIEWER)
    token = login_token(auth_client)
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        auth_client.get("/api/v1/auth/me", headers=headers).json()["role"] == "viewer"
    )
    with Session(device_engine) as writer:
        current = writer.get(User, user.id)
        assert current is not None
        current.role = UserRole.ADMIN
        writer.commit()
    assert auth_client.get("/api/v1/auth/me", headers=headers).json()["role"] == "admin"
    with Session(device_engine) as writer:
        current = writer.get(User, user.id)
        assert current is not None
        current.is_active = False
        writer.commit()
    denied = auth_client.get("/api/v1/auth/me", headers=headers)
    assert denied.status_code == 401 and denied.headers["WWW-Authenticate"] == "Bearer"
    with Session(device_engine) as writer:
        current = writer.get(User, user.id)
        assert current is not None
        writer.delete(current)
        writer.commit()
    assert auth_client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_persisted_login_denials_are_uniform(
    device_engine: Engine,
    password_hash: str,
    auth_client: TestClient,
) -> None:
    user = seed_user(device_engine, password_hash, UserRole.VIEWER)
    messages = []
    for email, password in (("missing", "wrong"), (user.email, "wrong")):
        response = auth_client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        messages.append(
            (response.json()["error"]["code"], response.json()["error"]["message"])
        )
    with Session(device_engine) as writer:
        current = writer.get(User, user.id)
        assert current is not None
        current.is_active = False
        writer.commit()
    response = auth_client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "  trusted test 密码  ",
        },
    )
    assert response.status_code == 401
    messages.append(
        (response.json()["error"]["code"], response.json()["error"]["message"])
    )
    assert len(set(messages)) == 1
