"""Acceptance tests for typed application configuration."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import TEST_SETTINGS_FILE, Environment, get_settings


@pytest.fixture(autouse=True)
def isolate_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    get_settings.cache_clear()
    monkeypatch.chdir(tmp_path)

    yield

    get_settings.cache_clear()


def test_settings_loads_required_values_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment variables should populate the typed settings object."""
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://test_user:test_password@localhost:5432/test_db"
    )
    monkeypatch.setenv("ENVIRONMENT", "development")

    settings = get_settings(TEST_SETTINGS_FILE)

    assert (
        settings.database_url.get_secret_value()
        == "postgresql://test_user:test_password@localhost:5432/test_db"
    )
    assert settings.environment is Environment.DEVELOPMENT


def test_settings_rejects_a_missing_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database URL must not have an in-repository default."""

    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        get_settings(TEST_SETTINGS_FILE)


def test_test_environment_can_be_selected_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests should be able to select their environment
    without reading developer state."""

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://test_user:test_password@localhost:5432/test_db"
    )
    monkeypatch.setenv("ENVIRONMENT", "test")

    settings = get_settings(TEST_SETTINGS_FILE)

    assert settings.environment is Environment.TEST


def test_settings_rejects_invalid_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://test_user:test_password@localhost:5432/invalid_env_db",
    )
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(ValidationError):
        get_settings(TEST_SETTINGS_FILE)


def test_get_settings_returns_cached_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:password@localhost:5432/cache_db",
    )

    first = get_settings(TEST_SETTINGS_FILE)
    second = get_settings(TEST_SETTINGS_FILE)

    assert second is first


def test_get_settings_reloads_after_cache_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_url = "postgresql://user:password@localhost:5432/first_db"
    second_url = "postgresql://user:password@localhost:5432/second_db"

    monkeypatch.setenv("DATABASE_URL", first_url)

    first = get_settings(TEST_SETTINGS_FILE)

    monkeypatch.setenv("DATABASE_URL", second_url)

    cached = get_settings(TEST_SETTINGS_FILE)

    assert cached is first
    assert cached.database_url.get_secret_value() == first_url

    get_settings.cache_clear()

    reloaded = get_settings(TEST_SETTINGS_FILE)

    assert reloaded is not first
    assert reloaded.database_url.get_secret_value() == second_url


def test_database_url_is_redacted_from_settings_representation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = (
        "postgresql://secret_user:super_secret_password@localhost:5432/secret_db"
    )

    monkeypatch.setenv("DATABASE_URL", database_url)

    settings = get_settings(TEST_SETTINGS_FILE)

    assert database_url not in str(settings)
    assert database_url not in repr(settings)
    assert "super_secret_password" not in str(settings)
    assert "super_secret_password" not in repr(settings)
