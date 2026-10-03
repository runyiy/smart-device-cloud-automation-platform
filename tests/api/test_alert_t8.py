"""T8 HTTP contracts through the real application and isolated service results."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.alerts.model import AlertStatus
from app.alerts.service import AlertNotFoundError, InvalidAlertStateError
from app.api.dependencies import get_db_session
from app.auth.dependencies import get_current_user
from app.core.config import Settings
from app.main import create_app
from app.users.model import User, UserRole
from tests.unit.test_alert_t8 import stored_alert


@pytest.fixture
def alert_client() -> Iterator[TestClient]:
    app = create_app(
        Settings(_env_file=None, database_url="sqlite+pysqlite:///:memory:")
    )
    app.dependency_overrides[get_db_session] = lambda: MagicMock(spec=Session)
    # This fixture isolates business HTTP mapping; RBAC tests use real tokens.
    app.dependency_overrides[get_current_user] = lambda: User(role=UserRole.ADMIN)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_list_response_and_query_wiring(alert_client: TestClient) -> None:
    alert = stored_alert()
    with patch(
        "app.alerts.router.list_alerts_service", return_value=([alert], 4)
    ) as service:
        response = alert_client.get(
            "/api/v1/alerts",
            params={
                "page": "2",
                "page_size": "1",
                "device_id": str(alert.device_id),
                "status": "open",
                "severity": "critical",
                "type": alert.type,
                "sort_order": "asc",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["page"], body["page_size"]) == (4, 2, 1)
    assert body["items"][0]["id"] == str(alert.id)
    assert body["items"][0]["triggered_at"].endswith("Z")
    query = service.call_args.kwargs["query"]
    assert query.device_id == alert.device_id and query.status is AlertStatus.OPEN
    assert query.sort_order == "asc" and query.type == alert.type


@pytest.mark.parametrize(
    "key,value",
    [
        ("page", "0"),
        ("page_size", "101"),
        ("page", "x"),
        ("device_id", ""),
        ("device_id", "bad"),
        ("status", "OPEN"),
        ("severity", ""),
        ("type", ""),
        ("type", "a b"),
        ("type", "x" * 65),
        ("sort_order", "invalid"),
    ],
)
def test_bad_query_never_calls_service(
    alert_client: TestClient,
    key: str,
    value: str,
) -> None:
    with patch("app.alerts.router.list_alerts_service") as service:
        response = alert_client.get("/api/v1/alerts", params={key: value})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    service.assert_not_called()


@pytest.mark.parametrize("action", ["acknowledge", "resolve"])
def test_action_wiring_and_invalid_id(alert_client: TestClient, action: str) -> None:
    alert = stored_alert(
        AlertStatus.RESOLVED if action == "resolve" else AlertStatus.ACKNOWLEDGED
    )
    with patch(
        f"app.alerts.router.{action}_alert_service", return_value=alert
    ) as service:
        response = alert_client.post(f"/api/v1/alerts/{alert.id}/{action}")
        assert response.status_code == 200
        assert response.json()["status"] == alert.status.value
        assert service.call_args.kwargs["alert_id"] == alert.id
        service.reset_mock()
        assert alert_client.post(f"/api/v1/alerts/bad/{action}").status_code == 422
        service.assert_not_called()


@pytest.mark.parametrize(
    "action,error,code",
    [
        ("acknowledge", AlertNotFoundError("PRIVATE_SECRET"), 404),
        ("resolve", AlertNotFoundError("PRIVATE_SECRET"), 404),
        ("acknowledge", InvalidAlertStateError("PRIVATE_SECRET"), 409),
        ("acknowledge", RuntimeError("PRIVATE_SECRET"), 500),
        ("resolve", RuntimeError("PRIVATE_SECRET"), 500),
        ("list", RuntimeError("PRIVATE_SECRET"), 500),
    ],
)
def test_sanitized_errors(
    alert_client: TestClient,
    action: str,
    error: Exception,
    code: int,
) -> None:
    name = "list_alerts_service" if action == "list" else f"{action}_alert_service"
    with patch(f"app.alerts.router.{name}", side_effect=error):
        response = (
            alert_client.get("/api/v1/alerts")
            if action == "list"
            else alert_client.post(f"/api/v1/alerts/{uuid4()}/{action}")
        )
    assert response.status_code == code
    assert "PRIVATE_SECRET" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_openapi_contract(alert_client: TestClient) -> None:
    schema = alert_client.get("/openapi.json").json()
    operations = [
        (schema["paths"]["/api/v1/alerts"]["get"], ["422"]),
        (
            schema["paths"]["/api/v1/alerts/{alert_id}/acknowledge"]["post"],
            ["404", "409", "422"],
        ),
        (
            schema["paths"]["/api/v1/alerts/{alert_id}/resolve"]["post"],
            ["404", "409", "422"],
        ),
    ]
    for operation, codes in operations:
        assert "requestBody" not in operation and "200" in operation["responses"]
        for code in codes:
            assert operation["responses"][code]["content"]["application/json"][
                "schema"
            ]["$ref"].endswith("/ErrorResponse")
    assert set(schema["components"]["schemas"]["AlertRead"]["required"]) == {
        "id",
        "device_id",
        "type",
        "severity",
        "status",
        "message",
        "triggered_at",
        "resolved_at",
    }
