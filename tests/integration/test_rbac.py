"""V2-T6 real JWT/permission/transaction acceptance on guarded PostgreSQL."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import cast
from unittest.mock import patch
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, Table, select
from sqlalchemy.orm import Session

from app.alerts.model import Alert
from app.audit.model import AuditLog
from app.auth.security import AuthConfig, create_access_token
from app.core.config import Settings
from app.devices.model import Device
from app.devices.repository import DeviceRepository
from app.main import create_app
from app.telemetry.model import Telemetry
from app.telemetry.schema import TelemetryCreate
from app.telemetry.service import ingest_telemetry
from app.test_tasks.model import TestTask as Task
from app.users.model import User, UserRole
from app.users.repository import UserRepository
from tests.api.test_rbac import CASES, request_case
from tests.conftest import TEST_SIGNING_KEY
from tests.integration.test_devices import device_engine as device_engine
from tests.integration.test_migrations import validate_test_database
from tests.integration.test_task_t10 import seed
from tests.rbac_support import business_actor_id as business_actor_id
from tests.rbac_support import legacy_admin_hash


@pytest.fixture
def rbac_client(
    device_engine: Engine, business_actor_id: UUID
) -> Iterator[tuple[TestClient, User, dict[str, str]]]:
    device_id, task_id = seed(device_engine)
    with Session(device_engine, expire_on_commit=False) as session:
        user = User(
            email="rbac@example.test",
            password_hash=legacy_admin_hash(),
            role=UserRole.VIEWER,
        )
        session.add(user)
        session.commit()
    with Session(device_engine) as session:
        ingest_telemetry(
            session,
            device_id,
            TelemetryCreate.model_validate(
                {
                    "metric": "temperature",
                    "value": 90.0,
                    "unit": "°C",
                    "recorded_at": "2026-01-01T00:00:00Z",
                }
            ),
            actor_id=business_actor_id,
        )
        alert_id = session.scalar(select(Alert.id))
        assert alert_id is not None
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=device_engine.url.render_as_string(hide_password=False),
    )
    validate_test_database(settings)
    app = create_app(settings)
    ids = {
        "device_id": str(device_id),
        "task_id": str(task_id),
        "alert_id": str(alert_id),
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        token = create_access_token(
            user.id, config=cast(AuthConfig, app.state.auth_config)
        )
        client.headers["Authorization"] = f"Bearer {token}"
        yield client, user, ids


def snapshot(engine: Engine) -> dict[str, list[tuple[object, ...]]]:
    tables = [
        cast(Table, model.__table__)
        for model in (Device, Telemetry, Alert, Task, User, AuditLog)
    ]
    with engine.connect() as connection:
        return {
            table.name: [
                tuple(row)
                for row in connection.execute(select(table).order_by(table.c.id))
            ]
            for table in tables
        }


def change_role(engine: Engine, user: User, role: UserRole) -> None:
    with Session(engine) as session:
        current = session.get(User, user.id)
        assert current is not None
        current.role = role
        session.commit()


@pytest.mark.parametrize("role", list(UserRole))
def test_all_actual_business_operations_by_persisted_role(
    device_engine: Engine,
    rbac_client: tuple[TestClient, User, dict[str, str]],
    role: UserRole,
) -> None:
    client, user, ids = rbac_client
    change_role(device_engine, user, role)
    for case in CASES:
        before = snapshot(device_engine)
        response = request_case(client, case, ids=ids)
        if role in case.roles:
            assert response.status_code == case.success, (
                case.method,
                case.path,
                response.status_code,
            )
        else:
            assert response.status_code == 403
            assert "WWW-Authenticate" not in response.headers
            assert snapshot(device_engine) == before


def test_committed_role_and_active_changes_affect_next_request(
    device_engine: Engine,
    rbac_client: tuple[TestClient, User, dict[str, str]],
) -> None:
    client, user, ids = rbac_client
    path = f"/api/v1/devices/{ids['device_id']}"
    body = {"name": "Updated"}
    assert client.patch(path, json=body).status_code == 403
    change_role(device_engine, user, UserRole.ADMIN)
    assert client.patch(path, json=body).status_code == 200
    change_role(device_engine, user, UserRole.OPERATOR)
    assert client.patch(path, json=body).status_code == 403
    assert client.get(path).status_code == 200
    with Session(device_engine) as session:
        current = session.get(User, user.id)
        assert current is not None
        current.is_active = False
        session.commit()
    before = snapshot(device_engine)
    denied = client.patch(path, json=body)
    assert denied.status_code == 401 and denied.headers["WWW-Authenticate"] == "Bearer"
    assert snapshot(device_engine) == before


@pytest.mark.parametrize("role", [UserRole.VIEWER, UserRole.OPERATOR])
def test_denied_missing_and_existing_targets_do_not_change_rows(
    device_engine: Engine,
    rbac_client: tuple[TestClient, User, dict[str, str]],
    role: UserRole,
) -> None:
    client, user, ids = rbac_client
    change_role(device_engine, user, role)
    before = snapshot(device_engine)
    for device_id in (ids["device_id"], str(uuid4())):
        response = client.patch(f"/api/v1/devices/{device_id}", json={"name": "Denied"})
        assert response.status_code == 403
    assert snapshot(device_engine) == before


def test_token_role_claim_never_grants_privilege(
    device_engine: Engine,
    rbac_client: tuple[TestClient, User, dict[str, str]],
) -> None:
    client, user, ids = rbac_client
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {
            "sub": str(user.id),
            "iat": now,
            "exp": now + 900,
            "token_type": "access",
            "role": "admin",
        },
        TEST_SIGNING_KEY,
        algorithm="HS256",
    )
    before = snapshot(device_engine)
    response = client.patch(
        f"/api/v1/devices/{ids['device_id']}",
        json={"name": "Denied"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403 and snapshot(device_engine) == before


def test_authentication_and_business_share_session_and_finalization(
    device_engine: Engine,
    rbac_client: tuple[TestClient, User, dict[str, str]],
) -> None:
    client, user, ids = rbac_client
    change_role(device_engine, user, UserRole.ADMIN)
    real_commit, real_rollback = Session.commit, Session.rollback
    with (
        patch("app.auth.service.UserRepository", wraps=UserRepository) as users,
        patch(
            "app.devices.service.DeviceRepository", wraps=DeviceRepository
        ) as devices,
        patch.object(
            Session, "commit", autospec=True, side_effect=real_commit
        ) as commits,
        patch.object(
            Session, "rollback", autospec=True, side_effect=real_rollback
        ) as rollbacks,
    ):
        success = client.patch(
            f"/api/v1/devices/{ids['device_id']}", json={"name": "Committed"}
        )
        assert success.status_code == 200
        assert users.call_args.args[0] is devices.call_args.args[0]
        assert commits.call_count == 1 and rollbacks.call_count == 0
        users.reset_mock()
        devices.reset_mock()
        missing = client.patch(f"/api/v1/devices/{uuid4()}", json={"name": "Missing"})
        assert missing.status_code == 404
        assert users.call_args.args[0] is devices.call_args.args[0]
        assert commits.call_count == 1 and rollbacks.call_count == 1
    with Session(device_engine) as observer:
        current = observer.get(Device, ids["device_id"])
        assert current is not None and current.name == "Committed"
