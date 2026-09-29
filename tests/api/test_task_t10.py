"""Real-application T10 routes, schema wiring, error envelopes and OpenAPI."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from app.devices.service import DeviceNotFoundError
from app.test_tasks.service import InactiveDeviceError, InvalidTestTaskStateError
from app.test_tasks.service import TestTaskNotFoundError as TaskNotFoundError
from tests.api.test_devices import client as client
from tests.unit.test_task_t10 import stored_task


def test_create_returns_201(client: TestClient) -> None:
    row = stored_task()
    with patch("app.test_tasks.router.create_test_task", return_value=row) as service:
        response = client.post(
            "/api/v1/test-tasks",
            json={"device_id": str(row.device_id), "name": " Task "},
        )
    assert response.status_code == 201
    assert response.json()["id"] == str(row.id)
    assert service.call_args.kwargs["data"].name == "Task"


def test_patch_status_only(client: TestClient) -> None:
    with patch(
        "app.test_tasks.router.update_test_task", return_value=stored_task()
    ) as service:
        response = client.patch(
            f"/api/v1/test-tasks/{uuid4()}", json={"status": "running"}
        )
    assert response.status_code == 200
    assert service.call_args.kwargs["data"].model_fields_set == {"status"}


@pytest.mark.parametrize(
    "operation,error,code",
    [
        ("create", DeviceNotFoundError("PRIVATE_SECRET"), 404),
        ("create", InactiveDeviceError("PRIVATE_SECRET"), 409),
        ("create", RuntimeError("PRIVATE_SECRET"), 500),
        ("get", TaskNotFoundError("PRIVATE_SECRET"), 404),
        ("get", RuntimeError("PRIVATE_SECRET"), 500),
        ("update", TaskNotFoundError("PRIVATE_SECRET"), 404),
        ("update", InvalidTestTaskStateError("PRIVATE_SECRET"), 409),
        ("update", RuntimeError("PRIVATE_SECRET"), 500),
    ],
)
def test_error_mapping(
    client: TestClient, operation: str, error: Exception, code: int
) -> None:
    with patch(f"app.test_tasks.router.{operation}_test_task", side_effect=error):
        if operation == "create":
            response = client.post(
                "/api/v1/test-tasks", json={"device_id": str(uuid4()), "name": "Task"}
            )
        elif operation == "get":
            response = client.get(f"/api/v1/test-tasks/{uuid4()}")
        else:
            response = client.patch(
                f"/api/v1/test-tasks/{uuid4()}", json={"summary": None}
            )
    assert response.status_code == code and "PRIVATE_SECRET" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_invalid_inputs_never_call_services(client: TestClient) -> None:
    with patch("app.test_tasks.router.create_test_task") as create:
        response = client.post(
            "/api/v1/test-tasks", json={"device_id": "bad", "name": " "}
        )
        assert response.status_code == 422
        create.assert_not_called()
    with patch("app.test_tasks.router.update_test_task") as update:
        for body in ({}, {"status": None}, {"name": "Rename"}, {"summary": " "}):
            assert (
                client.patch(f"/api/v1/test-tasks/{uuid4()}", json=body).status_code
                == 422
            )
        assert (
            client.patch("/api/v1/test-tasks/bad", json={"summary": None}).status_code
            == 422
        )
        update.assert_not_called()
    assert client.get("/api/v1/test-tasks/bad").status_code == 422


def test_openapi_responses(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for operation, codes in [
        (paths["/api/v1/test-tasks"]["post"], ["404", "409", "422"]),
        (paths["/api/v1/test-tasks/{task_id}"]["get"], ["404", "422"]),
        (paths["/api/v1/test-tasks/{task_id}"]["patch"], ["404", "409", "422"]),
    ]:
        for code in codes:
            assert operation["responses"][code]["content"]["application/json"][
                "schema"
            ]["$ref"].endswith("/ErrorResponse")
    assert "201" in paths["/api/v1/test-tasks"]["post"]["responses"]


@pytest.mark.parametrize("name", ["TestTaskCreate", "TestTaskUpdate"])
def test_openapi_examples(client: TestClient, name: str) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["components"]["schemas"][name].get("examples"), (
        "Provide Task contract examples"
    )
