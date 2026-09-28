"""T5 schema boundaries and application route-registration acceptance."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from app.devices.service import DeviceNotFoundError
from app.telemetry.schema import TelemetryCreate, TelemetryListQuery
from app.telemetry.service import InactiveDeviceError
from tests.api.test_devices import client as client


def payload() -> dict[str, object]:
    return {
        "metric": "temperature",
        "value": 23.5,
        "unit": "°C",
        "recorded_at": "2026-09-26T10:00:00Z",
    }


@pytest.mark.parametrize("unit", ["", " ", "\t\n"])
def test_unit_rejects_empty_after_strip(unit: str) -> None:
    with pytest.raises(ValidationError):
        TelemetryCreate.model_validate({**payload(), "unit": unit})


def test_unit_strips_before_length_check() -> None:
    sample = TelemetryCreate.model_validate({**payload(), "unit": " " + "u" * 32 + " "})
    assert sample.unit == "u" * 32


@pytest.mark.parametrize(
    "stamp", ["1720000000", "-1720000000", "+1720000000", "1720000000.5"]
)
def test_recorded_time_rejects_numeric_strings(stamp: str) -> None:
    with pytest.raises(ValidationError):
        TelemetryCreate.model_validate({**payload(), "recorded_at": stamp})


@pytest.mark.parametrize("bound", ["from", "to"])
@pytest.mark.parametrize("stamp", ["1720000000", "-1720000000", "+1720000000", "-1.5"])
def test_query_rejects_numeric_strings(bound: str, stamp: str) -> None:
    with pytest.raises(ValidationError):
        TelemetryListQuery.model_validate({bound: stamp})


@pytest.mark.parametrize(
    "stamp", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"]
)
def test_unrepresentable_utc_is_validation_error(stamp: str) -> None:
    with pytest.raises(ValidationError):
        TelemetryCreate.model_validate({**payload(), "recorded_at": stamp})


@pytest.mark.parametrize("bound", ["from", "to"])
def test_query_unrepresentable_utc_is_validation_error(bound: str) -> None:
    with pytest.raises(ValidationError):
        TelemetryListQuery.model_validate({bound: "0001-01-01T00:00:00+01:00"})


def test_huge_integer_is_validation_error() -> None:
    with pytest.raises(ValidationError):
        TelemetryCreate.model_validate({**payload(), "value": 10**400})


@pytest.mark.parametrize("field", ["metric", "value", "unit", "recorded_at"])
@pytest.mark.parametrize("value", [None, True, [], {}])
def test_required_fields_reject_wrong_types(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        TelemetryCreate.model_validate({**payload(), field: value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "12"])
def test_value_rejects_nonfinite_or_string(value: object) -> None:
    with pytest.raises(ValidationError):
        TelemetryCreate.model_validate({**payload(), "value": value})


def test_valid_input_and_query_aliases() -> None:
    sample = TelemetryCreate.model_validate(payload())
    assert sample.value == 23.5
    query = TelemetryListQuery.model_validate(
        {
            "from": "2026-09-26T10:00:00+08:00",
            "to": "2026-09-26T02:00:00Z",
            "page": "2",
            "page_size": "1",
        }
    )
    assert query.from_time == query.to_time
    assert query.page == 2
    ignored = TelemetryListQuery.model_validate({"from_time": "bad"})
    assert ignored.from_time is None


def test_routes_are_mounted_in_application(client: TestClient) -> None:
    path = f"/api/v1/devices/{uuid4()}/telemetry"
    with patch("app.telemetry.router.list_telemetry", return_value=([], 0)):
        response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}
    schema = client.get("/openapi.json").json()
    operations = schema["paths"]["/api/v1/devices/{device_id}/telemetry"]
    assert {"get", "post"} <= operations.keys()
    assert "requestBody" not in operations["get"]
    assert {p["name"] for p in operations["get"]["parameters"]} == {
        "device_id",
        "metric",
        "from",
        "to",
        "page",
        "page_size",
        "sort_order",
    }
    for method, codes in [("get", ["404", "422"]), ("post", ["404", "409", "422"])]:
        for code in codes:
            reference = operations[method]["responses"][code]["content"][
                "application/json"
            ]["schema"]["$ref"]
            assert reference.endswith("/ErrorResponse")


def test_http_query_aliases_are_applied(client: TestClient) -> None:
    with patch("app.telemetry.router.list_telemetry", return_value=([], 0)) as service:
        response = client.get(
            f"/api/v1/devices/{uuid4()}/telemetry",
            params={
                "from": "2026-09-26T10:00:00+08:00",
                "to": "2026-09-26T02:00:00Z",
                "page": "2",
                "page_size": "1",
                "metric": "temperature",
                "from_time": "ignored",
                "unknown": "ignored",
            },
        )
    assert response.status_code == 200
    query = service.call_args.kwargs["query"]
    assert query.from_time == query.to_time
    assert query.from_time is not None and query.from_time.hour == 2
    assert response.json()["page"] == 2


@pytest.mark.parametrize(
    "query",
    [
        {"from": "-1"},
        {"to": ""},
        {"from": "2026-01-01"},
        {"to": "2026-01-01T00:00:00"},
        {"from": "2026-02-01T00:00:00Z", "to": "2026-01-01T00:00:00Z"},
        {"metric": ""},
        {"page": "0"},
        {"page_size": "101"},
    ],
)
def test_http_invalid_query_is_422(client: TestClient, query: dict[str, str]) -> None:
    with patch("app.telemetry.router.list_telemetry") as service:
        response = client.get(f"/api/v1/devices/{uuid4()}/telemetry", params=query)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    service.assert_not_called()


@pytest.mark.parametrize(
    "error,code",
    [
        (DeviceNotFoundError("PRIVATE_SECRET"), 404),
        (InactiveDeviceError("PRIVATE_SECRET"), 409),
        (RuntimeError("PRIVATE_SECRET"), 500),
    ],
)
def test_post_errors_are_private(
    client: TestClient, error: Exception, code: int
) -> None:
    with patch("app.telemetry.router.ingest_telemetry", side_effect=error):
        response = client.post(f"/api/v1/devices/{uuid4()}/telemetry", json=payload())
    assert response.status_code == code
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "PRIVATE_SECRET" not in response.text


@pytest.mark.parametrize("field", ["metric", "value", "unit", "recorded_at"])
def test_missing_required_field(field: str) -> None:
    body = payload()
    del body[field]
    with pytest.raises(ValidationError):
        TelemetryCreate.model_validate(body)


@pytest.mark.parametrize("field", ["id", "device_id", "received_at", "extra"])
def test_unknown_fields_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        TelemetryCreate.model_validate({**payload(), field: "client-value"})


@pytest.mark.parametrize("value", ["2026-01-01", "2026-01-01T00:00:00", 1720000000])
def test_recorded_time_requires_aware_date_and_time(value: object) -> None:
    with pytest.raises(ValidationError):
        TelemetryCreate.model_validate({**payload(), "recorded_at": value})
