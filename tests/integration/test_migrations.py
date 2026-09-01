"""PostgreSQL integration tests for the Alembic migration baseline."""

import os
from collections.abc import Iterator

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from app.core.config import TEST_SETTINGS_FILE, Environment, Settings, get_settings

MIGRATION_TEST_OPT_IN = "RUN_MIGRATION_TESTS"


def validate_test_database(settings: Settings) -> str:
    """Return the URL only when the target is explicitly disposable and local."""
    if os.getenv(MIGRATION_TEST_OPT_IN) != "1":
        raise RuntimeError("migration tests require explicit opt-in")

    if settings.environment is not Environment.TEST:
        raise RuntimeError("migration tests require the test environment")

    database_url = settings.database_url.get_secret_value()
    parsed_url = make_url(database_url)

    if parsed_url.host not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("migration tests require a localhost database")

    if parsed_url.database is None or not parsed_url.database.endswith("_test"):
        raise RuntimeError("migration database name must end with _test")

    return database_url


def reset_test_database(settings: Settings) -> str:
    """Reset a validated disposable database to an empty public schema."""
    database_url = validate_test_database(settings)
    engine = create_engine(database_url)

    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()

    return database_url


def read_database_state(database_url: str) -> tuple[str | None, set[str]]:
    """Read the current Alembic revision and public table names."""
    engine = create_engine(database_url)

    try:
        with engine.connect() as connection:
            migration_context = MigrationContext.configure(connection)
            current_revision = migration_context.get_current_revision()
            table_names = set(inspect(connection).get_table_names(schema="public"))

        return current_revision, table_names
    finally:
        engine.dispose()


@pytest.fixture
def migration_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Load destructive-test settings only after the caller explicitly opts in."""
    if os.getenv(MIGRATION_TEST_OPT_IN) != "1":
        pytest.skip(f"set {MIGRATION_TEST_OPT_IN}=1 to run migration tests")

    monkeypatch.setenv("SETTINGS_FILE", TEST_SETTINGS_FILE)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings(TEST_SETTINGS_FILE)
        validate_test_database(settings)
        yield settings
    finally:
        get_settings.cache_clear()


def test_database_reset_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The destructive helper should reject a run without explicit opt-in."""
    monkeypatch.delenv(MIGRATION_TEST_OPT_IN, raising=False)
    settings = Settings(
        environment=Environment.TEST,
        database_url=(
            "postgresql+psycopg://smart_device_user:unit-test-only@localhost/"
            "smart_device_cloud_test"
        ),
    )

    with pytest.raises(RuntimeError, match="explicit opt-in"):
        reset_test_database(settings)


@pytest.mark.parametrize(
    ("environment", "database_url", "expected_message"),
    [
        (
            Environment.DEVELOPMENT,
            "postgresql+psycopg://smart_device_user:unit-test-only@localhost/"
            "smart_device_cloud_test",
            "test environment",
        ),
        (
            Environment.TEST,
            "postgresql+psycopg://smart_device_user:unit-test-only@"
            "database.internal/smart_device_cloud_test",
            "localhost",
        ),
        (
            Environment.TEST,
            "postgresql+psycopg://smart_device_user:unit-test-only@localhost/"
            "smart_device_cloud",
            "must end with _test",
        ),
    ],
)
def test_database_reset_rejects_unsafe_targets(
    monkeypatch: pytest.MonkeyPatch,
    environment: Environment,
    database_url: str,
    expected_message: str,
) -> None:
    """The destructive helper should reject every unsafe target category."""
    monkeypatch.setenv(MIGRATION_TEST_OPT_IN, "1")
    settings = Settings(environment=environment, database_url=database_url)

    with pytest.raises(RuntimeError, match=expected_message):
        reset_test_database(settings)


def test_migrations_upgrade_empty_database_to_head(
    migration_settings: Settings,
) -> None:
    """An empty PostgreSQL database should migrate to the table-free baseline."""
    database_url = reset_test_database(migration_settings)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")

    script = ScriptDirectory.from_config(alembic_config)
    expected_head = script.get_current_head()
    current_revision, table_names = read_database_state(database_url)

    assert current_revision == expected_head
    assert table_names == {"alembic_version"}


def test_latest_migration_downgrades_and_upgrades_again(
    migration_settings: Settings,
) -> None:
    """The baseline should downgrade to base and upgrade again without extra tables."""
    database_url = reset_test_database(migration_settings)
    alembic_config = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_config)
    expected_head = script.get_current_head()

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    current_revision, table_names = read_database_state(database_url)

    assert current_revision is None
    assert table_names <= {"alembic_version"}

    command.upgrade(alembic_config, "head")

    current_revision, table_names = read_database_state(database_url)

    assert current_revision == expected_head
    assert table_names == {"alembic_version"}
