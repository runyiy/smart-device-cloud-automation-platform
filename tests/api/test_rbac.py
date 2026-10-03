"""V2-T6 complete HTTP permission matrix with real tokens and service spies."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.auth import service
from app.auth.security import AuthConfig, create_access_token
from app.core.config import Settings
from app.main import create_app
from app.users.model import User, UserRole
from tests.conftest import TEST_SIGNING_KEY

ALL = frozenset(UserRole)
OPERATE = frozenset((UserRole.ADMIN, UserRole.OPERATOR))
ADMIN = frozenset((UserRole.ADMIN,))


@dataclass(frozen=True)
class Case:
    method: str
    path: str
    service: str
    roles: frozenset[UserRole]
    body: dict[str, object] | None = None
    success: int = 200


CASES = [
    Case("GET", "/devices", "app.devices.router.list_devices", ALL),
    Case("GET", "/devices/{device_id}", "app.devices.router.get_device", ALL),
    Case(
        "POST",
        "/devices",
        "app.devices.router.create_device",
        ADMIN,
        {
            "serial_number": "RBAC-NEW",
            "name": "Device",
            "model": "M1",
            "firmware_version": "v1",
        },
        201,
    ),
    Case(
        "PATCH",
        "/devices/{device_id}",
        "app.devices.router.update_device",
        ADMIN,
        {"name": "Updated"},
    ),
    Case(
        "GET",
        "/devices/{device_id}/telemetry",
        "app.telemetry.router.list_telemetry",
        ALL,
    ),
    Case(
        "POST",
        "/devices/{device_id}/telemetry",
        "app.telemetry.router.ingest_telemetry",
        OPERATE,
        {
            "metric": "temperature",
            "value": 90.0,
            "unit": "°C",
            "recorded_at": "2026-01-02T00:00:00Z",
        },
        201,
    ),
    Case("GET", "/alerts", "app.alerts.router.list_alerts_service", ALL),
    Case(
        "POST",
        "/alerts/{alert_id}/acknowledge",
        "app.alerts.router.acknowledge_alert_service",
        OPERATE,
    ),
    Case(
        "POST",
        "/alerts/{alert_id}/resolve",
        "app.alerts.router.resolve_alert_service",
        OPERATE,
    ),
    Case("GET", "/test-tasks/{task_id}", "app.test_tasks.router.get_test_task", ALL),
    Case(
        "POST",
        "/test-tasks",
        "app.test_tasks.router.create_test_task",
        OPERATE,
        {"device_id": "replace", "name": "RBAC task"},
        201,
    ),
    Case(
        "PATCH",
        "/test-tasks/{task_id}",
        "app.test_tasks.router.update_test_task",
        OPERATE,
        {"summary": "Updated"},
    ),
]
IDS = {
    "device_id": str(UUID(int=101)),
    "alert_id": str(UUID(int=102)),
    "task_id": str(UUID(int=103)),
}


def request_case(
    client: TestClient,
    case: Case,
    *,
    ids: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    values = IDS if ids is None else ids
    body = None if case.body is None else dict(case.body)
    if body is not None and "device_id" in body:
        body["device_id"] = values["device_id"]
    return client.request(
        case.method,
        "/api/v1" + case.path.format(**values),
        json=body,
        headers=headers,
    )


@pytest.fixture
def rbac_http(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, MagicMock, MagicMock, User, AuthConfig]]:
    config = AuthConfig(
        signing_key=SecretStr(TEST_SIGNING_KEY),
        access_token_ttl_seconds=900,
        dummy_password_hash=SecretStr("unused-no-login-here"),
    )
    app = create_app(
        Settings(_env_file=None, database_url=SecretStr("unused")), auth_config=config
    )
    session = MagicMock(spec=Session)

    def session_override() -> Iterator[Session]:
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = session_override
    repo = MagicMock()
    constructor = MagicMock(return_value=repo)
    monkeypatch.setattr(service, "UserRepository", constructor)
    user = User(id=uuid4(), role=UserRole.ADMIN, is_active=True)
    repo.get.return_value = user
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client, repo, session, user, config
    finally:
        client.close()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.method + case.path)
@pytest.mark.parametrize("role", list(UserRole))
def test_all_operations_roles_and_denial_before_business(
    rbac_http: tuple[TestClient, MagicMock, MagicMock, User, AuthConfig],
    case: Case,
    role: UserRole,
) -> None:
    client, repo, session, user, config = rbac_http
    user.role = role
    token = create_access_token(user.id, config=config)
    with patch(
        case.service, side_effect=RuntimeError("business-reached-private")
    ) as business:
        response = request_case(
            client, case, headers={"Authorization": f"Bearer {token}"}
        )
    if role in case.roles:
        assert response.status_code == 500
        business.assert_called_once()
        assert business.call_args.kwargs["session"] is session
    else:
        assert response.status_code == 403
        business.assert_not_called()
        assert "WWW-Authenticate" not in response.headers
    repo.get.assert_called_once_with(user.id)
    session.close.assert_called_once()
    for operation in ("add", "flush", "commit", "rollback"):
        getattr(session, operation).assert_not_called()
    assert "business-reached-private" not in response.text
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.method + case.path)
@pytest.mark.parametrize("mode", ["anonymous", "malformed", "expired", "wrong-scheme"])
def test_authentication_denials_keep_401(
    rbac_http: tuple[TestClient, MagicMock, MagicMock, User, AuthConfig],
    case: Case,
    mode: str,
) -> None:
    client, _, _, user, _ = rbac_http
    now = int(datetime.now(UTC).timestamp())
    expired = jwt.encode(
        {"sub": str(user.id), "iat": now - 100, "exp": now - 1, "token_type": "access"},
        TEST_SIGNING_KEY,
        algorithm="HS256",
    )
    headers = {
        "anonymous": {},
        "malformed": {"Authorization": "Bearer private-invalid"},
        "expired": {"Authorization": f"Bearer {expired}"},
        "wrong-scheme": {"Authorization": "Basic private-invalid"},
    }[mode]
    with patch(case.service) as business:
        response = request_case(client, case, headers=headers)
    assert (
        response.status_code == 401 and response.headers["WWW-Authenticate"] == "Bearer"
    )
    business.assert_not_called()
    assert "private-invalid" not in response.text


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.method + case.path)
def test_business_openapi_declares_security_and_errors(
    rbac_http: tuple[TestClient, MagicMock, MagicMock, User, AuthConfig],
    case: Case,
) -> None:
    client, _, _, _, _ = rbac_http
    operation = client.get("/openapi.json").json()["paths"]["/api/v1" + case.path][
        case.method.lower()
    ]
    assert operation["security"] == [{"HTTPBearer": []}]
    for code in ("401", "403"):
        assert code in operation["responses"]
        assert operation["responses"][code]["content"]["application/json"][
            "schema"
        ] == {"$ref": "#/components/schemas/ErrorResponse"}


@pytest.mark.parametrize("failure", ["missing", "inactive", "database"])
def test_bad_principals_and_db_faults_do_not_reach_business(
    rbac_http: tuple[TestClient, MagicMock, MagicMock, User, AuthConfig],
    failure: str,
) -> None:
    client, repo, _, user, config = rbac_http
    token = create_access_token(user.id, config=config)
    if failure == "missing":
        repo.get.return_value = None
    elif failure == "inactive":
        user.is_active = False
    else:
        repo.get.side_effect = OperationalError(
            "private-db", {}, Exception("private-db")
        )
    with patch(CASES[0].service) as business:
        response = request_case(
            client, CASES[0], headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == (500 if failure == "database" else 401)
    business.assert_not_called()
    assert "private-db" not in response.text


def test_public_system_login_and_me_contracts_remain(
    rbac_http: tuple[TestClient, MagicMock, MagicMock, User, AuthConfig],
) -> None:
    client, _, _, _, _ = rbac_http
    paths = client.get("/openapi.json").json()["paths"]
    for path, method in (
        ("/health", "get"),
        ("/ready", "get"),
        ("/api/v1/ping", "get"),
        ("/api/v1/auth/login", "post"),
    ):
        assert "security" not in paths[path][method]
    assert paths["/api/v1/auth/me"]["get"]["security"] == [{"HTTPBearer": []}]
    assert client.get("/docs").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/ping").status_code == 200
