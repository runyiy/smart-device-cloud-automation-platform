"""V2-T4 migrated User constraints, ownership, concurrency and data preservation."""

from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Engine, Table, func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session

from alembic import command
from app.alerts.model import Alert, AlertSeverity
from app.db.base import Base
from app.db.transaction import transaction
from app.telemetry.model import Telemetry
from app.users.model import User, UserRole
from app.users.repository import UserRepository
from tests.integration.test_devices import device_engine as device_engine
from tests.integration.test_task_t10 import STAMP, seed

HEAD = "ba759824c979"
PARENT = "237c5f37c6c2"
CHECKS = {
    "ck_users_email_normalized",
    "ck_users_password_hash_non_empty",
    "ck_users_role_valid",
}
INSERT = text(
    "INSERT INTO users (id, email, password_hash, is_active, role, created_at) "
    "VALUES (:id, :email, :password_hash, :is_active, :role, :created_at)"
)


def test_migrated_schema_matches_user_metadata(device_engine: Engine) -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    # User revision/parent stay fixed while later additive revisions advance head.
    assert len(script.get_heads()) == 1
    assert HEAD in {r.revision for r in script.iterate_revisions("head", PARENT)}
    revision = script.get_revision(HEAD)
    assert revision is not None and revision.down_revision == PARENT
    with device_engine.connect() as connection:
        inspector = inspect(connection)
        assert inspector.has_table("users"), "Head migration must create users"
        assert {c["name"] for c in inspector.get_columns("users")} == {
            "id",
            "email",
            "password_hash",
            "is_active",
            "role",
            "created_at",
        }
        assert all(not c["nullable"] for c in inspector.get_columns("users"))
        assert {c["name"] for c in inspector.get_check_constraints("users")} == CHECKS
        unique = inspector.get_unique_constraints("users")
        assert len(unique) == 1 and unique[0]["name"] == "uq_users_email"
        assert unique[0]["column_names"] == ["email"]
        assert (
            compare_metadata(MigrationContext.configure(connection), Base.metadata)
            == []
        )


@pytest.mark.parametrize("role", list(UserRole))
def test_roles_defaults_and_exact_inactive_lookup(
    device_engine: Engine,
    role: UserRole,
) -> None:
    with Session(device_engine) as session:
        repo = UserRepository(session)
        with transaction(session):
            row = User(email="a@example.test", password_hash="opaque", role=role)
            repo.add(row)
        repo.refresh(row)
        assert row.role is role and row.is_active is True
        assert row.created_at.utcoffset() is not None
        assert repo.get(uuid4()) is None
        with transaction(session):
            row.is_active = False
        assert repo.get_by_email("a@example.test") is row
        assert repo.get_by_email("A@example.test") is None
        assert repo.get_by_email(" a@example.test ") is None
        assert repo.get_by_email("absent@example.test") is None
    with device_engine.begin() as connection:
        default_id = uuid4()
        connection.execute(
            text(
                "INSERT INTO users (id, email, password_hash) "
                "VALUES (:id, :email, :hash)"
            ),
            {"id": default_id, "email": "default@example.test", "hash": "opaque"},
        )
    with Session(device_engine) as observer:
        stored = observer.get(User, default_id)
        assert stored is not None and stored.role is UserRole.VIEWER
        assert stored.is_active is True and stored.created_at.utcoffset() is not None


def test_actual_not_null_lengths_checks_and_uniqueness(device_engine: Engine) -> None:
    base: dict[str, object] = {
        "id": uuid4(),
        "email": "a@example.test",
        "password_hash": "opaque",
        "is_active": True,
        "role": "viewer",
        "created_at": STAMP,
    }
    invalid: list[tuple[dict[str, object], str]] = [
        ({"email": ""}, "23514"),
        ({"email": " "}, "23514"),
        ({"email": "A@example.test"}, "23514"),
        ({"email": " a@example.test"}, "23514"),
        ({"email": "x" * 255}, "22001"),
        ({"password_hash": ""}, "23514"),
        ({"password_hash": " "}, "23514"),
        ({"password_hash": "\t\n"}, "23514"),
        ({"password_hash": "x" * 256}, "22001"),
        ({"role": "ADMIN"}, "23514"),
        ({"role": "unknown"}, "23514"),
    ]
    invalid.extend(({field: None}, "23502") for field in base)
    with device_engine.connect() as connection:
        for changes, expected in invalid:
            with pytest.raises(DBAPIError) as caught:
                connection.execute(INSERT, {**base, **changes})
            assert getattr(caught.value.orig, "sqlstate", None) == expected
            connection.rollback()
        connection.execute(INSERT, base)
        connection.commit()
        with pytest.raises(IntegrityError) as caught:
            connection.execute(INSERT, {**base, "id": uuid4()})
        assert getattr(caught.value.orig, "sqlstate", None) == "23505"
        assert (
            getattr(getattr(caught.value.orig, "diag", None), "constraint_name", None)
            == "uq_users_email"
        )
        connection.rollback()


def test_hash_constraint_rejects_all_ascii_whitespace(device_engine: Engine) -> None:
    table = User.__table__
    assert isinstance(table, Table)
    check = next(
        item
        for item in table.constraints
        if isinstance(item, CheckConstraint)
        and item.name == "ck_users_password_hash_non_empty"
    )
    # Evaluate the submitted CHECK directly on PG even if its migration is missing.
    query = text(
        f"SELECT {check.sqltext} FROM (VALUES (:value)) AS candidate(password_hash)"
    )
    with device_engine.connect() as connection:
        for value in ("", " ", "\t", "\n", "\r", "\v", "\f", " \t\n "):
            assert connection.scalar(query, {"value": value}) is False, repr(value)
        assert connection.scalar(query, {"value": "opaque"}) is True


def test_visibility_failed_flush_and_session_reuse(device_engine: Engine) -> None:
    with Session(device_engine) as owner:
        repo = UserRepository(owner)
        row = User(email="rollback@example.test", password_hash="opaque")
        repo.add(row)
        owner.flush()
        repo.refresh(row)
        with Session(device_engine) as observer:
            assert UserRepository(observer).get_by_email(row.email) is None
        owner.rollback()
        with Session(device_engine) as observer:
            assert (
                UserRepository(observer).get_by_email("rollback@example.test") is None
            )
        with transaction(owner):
            repo.add(User(email="a@example.test", password_hash="opaque"))
        assert repo.get_by_email("a@example.test") is not None
        with pytest.raises(IntegrityError):
            with transaction(owner):
                repo.add(User(email="a@example.test", password_hash="opaque"))
                owner.flush()
        assert not owner.in_transaction()
        with transaction(owner):
            repo.add(User(email="recovered@example.test", password_hash="opaque"))
        with Session(device_engine) as observer:
            assert observer.scalar(select(func.count()).select_from(User)) == 2


def test_lock_lifetime_and_cached_current_state(device_engine: Engine) -> None:
    with Session(device_engine) as initial:
        row = User(email="a@example.test", password_hash="opaque")
        initial.add(row)
        initial.commit()
        user_id = row.id
    with Session(device_engine) as owner, Session(device_engine) as competitor:
        repo = UserRepository(owner)
        cached = repo.get(user_id)
        assert cached is not None and cached.is_active
        with Session(device_engine) as winner:
            current = winner.get(User, user_id)
            assert current is not None
            current.is_active = False
            current.role = UserRole.ADMIN
            winner.commit()
        locked = repo.get(user_id, for_update=True)
        assert (
            locked is cached and not locked.is_active and locked.role is UserRole.ADMIN
        )
        assert UserRepository(competitor).get(user_id) is not None
        competitor.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(OperationalError) as caught:
            UserRepository(competitor).get(user_id, for_update=True)
        assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
        competitor.rollback()
        owner.rollback()
        assert UserRepository(competitor).get(user_id, for_update=True) is not None


def test_competing_duplicate_insert_has_one_durable_winner(
    device_engine: Engine,
) -> None:
    def compete() -> str:
        with Session(device_engine) as contender:
            try:
                with transaction(contender):
                    UserRepository(contender).add(
                        User(email="race@example.test", password_hash="opaque")
                    )
            except IntegrityError as error:
                assert not contender.in_transaction()
                assert (
                    getattr(getattr(error.orig, "diag", None), "constraint_name", None)
                    == "uq_users_email"
                )
                return str(getattr(error.orig, "sqlstate", None))
        return "committed"

    with Session(device_engine) as owner:
        UserRepository(owner).add(
            User(email="race@example.test", password_hash="opaque")
        )
        owner.flush()
        pid = owner.scalar(text("SELECT pg_backend_pid()"))
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(compete)
            try:
                blocked = False
                deadline = monotonic() + 3
                with device_engine.connect() as observer:
                    while monotonic() < deadline:
                        if future.done():
                            future.result()
                            break
                        blocked = bool(
                            observer.scalar(
                                text(
                                    "SELECT count(*) FROM pg_stat_activity "
                                    "WHERE datname=current_database() "
                                    "AND :pid = ANY(pg_blocking_pids(pid))"
                                ),
                                {"pid": pid},
                            )
                        )
                        if blocked:
                            break
                        sleep(0.01)
                assert blocked, "Duplicate insert must wait for the unique-index owner"
                owner.commit()
            finally:
                owner.rollback()
            assert future.result(timeout=6) == "23505"
    with Session(device_engine) as readback:
        assert readback.scalar(select(func.count()).select_from(User)) == 1


def test_users_migration_preserves_all_existing_business_data(
    device_engine: Engine,
) -> None:
    with device_engine.connect() as connection:
        assert inspect(connection).has_table("users"), (
            "Head migration must create users"
        )
    device_id, _ = seed(device_engine)
    with Session(device_engine) as session:
        session.add(
            Telemetry(
                device_id=device_id,
                metric="temperature",
                value=90,
                unit="°C",
                recorded_at=STAMP,
            )
        )
        session.add(
            Alert(
                device_id=device_id,
                type="temperature_high",
                severity=AlertSeverity.CRITICAL,
                message="Existing",
            )
        )
        session.commit()
    tables = ("devices", "telemetry", "alerts", "test_tasks")
    with device_engine.connect() as connection:
        before = {
            table: connection.execute(text(f"SELECT * FROM {table}")).all()
            for table in tables
        }
    config = Config("alembic.ini")
    device_engine.dispose()
    try:
        command.downgrade(config, PARENT)
        with device_engine.connect() as connection:
            assert not inspect(connection).has_table("users")
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == PARENT
            )
            for table in tables:
                assert (
                    connection.execute(text(f"SELECT * FROM {table}")).all()
                    == before[table]
                )
        device_engine.dispose()
    finally:
        command.upgrade(config, "head")
    with device_engine.connect() as connection:
        assert inspect(connection).has_table("users")
        assert connection.scalar(text("SELECT count(*) FROM users")) == 0
        for table in tables:
            assert (
                connection.execute(text(f"SELECT * FROM {table}")).all()
                == before[table]
            )
