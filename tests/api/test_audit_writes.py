"""V2-T8 actor forwarding with real JWTs and existing RBAC test seams."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.alerts.router import router as alert_router
from app.auth.security import AuthConfig, create_access_token
from app.devices.router import router as device_router
from app.telemetry.router import router as telemetry_router
from app.test_tasks.router import router as task_router
from app.users.model import User, UserRole
from tests.api.test_rbac import CASES, Case, request_case
from tests.api.test_rbac import rbac_http as rbac_http

WRITES = [case for case in CASES if case.method != "GET"]


@pytest.mark.parametrize("case", WRITES, ids=lambda case: case.method + case.path)
def test_write_forwards_only_authenticated_actor(
    rbac_http: tuple[TestClient, MagicMock, MagicMock, User, AuthConfig],
    case: Case,
) -> None:
    client, _, session, user, config = rbac_http
    user.role = UserRole.ADMIN
    token = create_access_token(user.id, config=config)
    with patch(case.service, side_effect=RuntimeError("private sentinel")) as business:
        response = request_case(
            client,
            case,
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 500
    business.assert_called_once()
    assert business.call_args.kwargs["actor_id"] == user.id
    assert business.call_args.kwargs["session"] is session


@pytest.mark.parametrize("case", WRITES, ids=lambda case: case.method + case.path)
def test_actor_is_not_a_public_input_or_duplicate_guard(
    rbac_http: tuple[TestClient, MagicMock, MagicMock, User, AuthConfig],
    case: Case,
) -> None:
    client, _, _, _, _ = rbac_http
    operation = client.get("/openapi.json").json()["paths"]["/api/v1" + case.path][
        case.method.lower()
    ]
    assert all(
        p["name"] not in {"actor", "actor_id"} for p in operation.get("parameters", [])
    )
    route = next(
        r
        for r in [
            *device_router.routes,
            *telemetry_router.routes,
            *alert_router.routes,
            *task_router.routes,
        ]
        if isinstance(r, APIRoute)
        and r.path == case.path
        and case.method in (r.methods or set())
    )
    assert route.dependencies == [], "Bind the existing role guard once as actor"
