"""T3 HTTP contracts with isolated service results."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from app.devices.service import DeviceNotFoundError, InvalidDeviceStateError
from tests.api.test_devices import client as client
from tests.api.test_devices import stored_device


def test_list_query_and_response(client: TestClient) -> None:
    with patch("app.devices.router.list_devices", return_value=([], 3)) as service:
        response = client.get(
            "/api/v1/devices?page=2&page_size=1&model=%20M1%20&unknown=x"
        )
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 3, "page": 2, "page_size": 1}
    query = service.call_args.kwargs["query"]
    assert query.model == "M1"
    assert query.serial_number is None
    with patch("app.devices.router.list_devices", return_value=([stored_device()], 1)):
        response = client.get("/api/v1/devices")
    assert response.status_code == 200
    assert response.json()["page_size"] == 20
    assert len(response.json()["items"]) == 1


@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "page_size=101",
        "page=no",
        "status=",
        "model=%20",
        "serial_number=bad%20id",
        "sort_by=name",
        "sort_order=bad",
    ],
)
def test_invalid_query_never_calls_service(client: TestClient, query: str) -> None:
    with patch("app.devices.router.list_devices") as service:
        response = client.get("/api/v1/devices?" + query)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    service.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": None},
        {"name": 1},
        {"name": " "},
        {"name": "x" * 101},
        {"serial_number": "immutable"},
        {"status": "ACTIVE"},
    ],
)
def test_bad_patch_never_calls_service(client: TestClient, body: dict) -> None:
    with patch("app.devices.router.update_device") as service:
        response = client.patch(f"/api/v1/devices/{uuid4()}", json=body)
    assert response.status_code == 422
    service.assert_not_called()


@pytest.mark.parametrize(
    "error,code",
    [
        (DeviceNotFoundError("PRIVATE_SECRET"), 404),
        (InvalidDeviceStateError("PRIVATE_SECRET"), 409),
        (RuntimeError("PRIVATE_SECRET"), 500),
    ],
)
def test_patch_errors_are_sanitized(
    client: TestClient, error: Exception, code: int
) -> None:
    with patch("app.devices.router.update_device", side_effect=error):
        response = client.patch(f"/api/v1/devices/{uuid4()}", json={"name": "new"})
    assert response.status_code == code
    assert "PRIVATE_SECRET" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_patch_routes_and_normalizes(client: TestClient) -> None:
    device = stored_device()
    with patch("app.devices.router.update_device", return_value=device) as service:
        response = client.patch(f"/api/v1/devices/{device.id}", json={"name": " New "})
    assert response.status_code == 200
    assert response.json()["id"] == str(device.id)
    assert service.call_args.kwargs["data"].model_dump(exclude_unset=True) == {
        "name": "New"
    }
    assert (
        client.patch("/api/v1/devices/bad-id", json={"name": "New"}).status_code == 422
    )


def test_t3_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    listing = schema["paths"]["/api/v1/devices"]["get"]
    update = schema["paths"]["/api/v1/devices/{device_id}"]["patch"]
    assert "requestBody" not in listing
    assert {p["name"] for p in listing["parameters"] if p["in"] == "query"} == {
        "page",
        "page_size",
        "status",
        "model",
        "serial_number",
        "sort_by",
        "sort_order",
    }
    for operation, codes in [(listing, ["422"]), (update, ["404", "409", "422"])]:
        for code in codes:
            assert operation["responses"][code]["content"]["application/json"][
                "schema"
            ]["$ref"].endswith("/ErrorResponse")
    examples = schema["components"]["schemas"]["DeviceUpdate"]["examples"]
    assert {"status": "inactive"} in examples
    assert any("name" in example for example in examples)
