"""V2-T7 mapped storage and caller-owned audit persistence contracts."""

from unittest.mock import MagicMock, call
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, DateTime, String, Table, inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.audit.model import AuditLog
from app.audit.repository import AuditLogRepository
from app.db.base import Base
from app.users.model import User


def test_audit_storage_mapping_and_reserved_metadata_contract() -> None:
    table = AuditLog.__table__
    assert isinstance(table, Table) and table.metadata is Base.metadata
    assert AuditLog.metadata is Base.metadata
    assert list(table.columns.keys()) == [
        "id",
        "actor_id",
        "action",
        "resource_type",
        "resource_id",
        "metadata",
        "created_at",
    ]
    assert all(not column.nullable for column in table.columns)
    assert all(column.onupdate is None for column in table.columns)
    assert table.primary_key.name == "pk_audit_logs"
    assert list(table.primary_key.columns.keys()) == ["id"]
    for name in ("id", "actor_id", "resource_id"):
        assert table.c[name].type.python_type is UUID
    assert table.c.id.default is not None and table.c.id.default.is_callable
    assert table.c.id.server_default is None
    for name in ("actor_id", "action", "resource_type", "resource_id"):
        assert table.c[name].default is None and table.c[name].server_default is None
    assert isinstance(table.c.action.type, String) and table.c.action.type.length == 64
    assert isinstance(table.c.resource_type.type, String)
    assert table.c.resource_type.type.length == 32
    assert isinstance(table.c.metadata.type, JSONB)
    assert table.c.metadata.default is not None and table.c.metadata.default.is_callable
    assert str(getattr(table.c.metadata.server_default, "arg", None)) == "'{}'::jsonb"
    assert inspect(AuditLog).attrs.event_metadata.columns[0] is table.c.metadata
    assert isinstance(table.c.created_at.type, DateTime)
    assert table.c.created_at.type.timezone and table.c.created_at.default is None
    assert str(getattr(table.c.created_at.server_default, "arg", None)) == (
        "CURRENT_TIMESTAMP"
    )
    assert {c.name for c in table.constraints if isinstance(c, CheckConstraint)} == {
        "ck_audit_logs_action_valid",
        "ck_audit_logs_resource_type_valid",
        "ck_audit_logs_metadata_object",
    }
    (foreign_key,) = table.foreign_keys
    assert foreign_key.parent is table.c.actor_id
    assert foreign_key.target_fullname == "users.id"
    assert foreign_key.name == "fk_audit_logs_actor_id_users"
    assert foreign_key.ondelete == "RESTRICT"
    (index,) = table.indexes
    assert index.name == "ix_audit_logs_actor_id" and not index.unique
    assert list(index.columns.keys()) == ["actor_id"]
    assert not inspect(AuditLog).relationships and not inspect(User).relationships


def test_audit_revision_is_the_single_additive_child() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["585f640ecf98"]
    revision = script.get_revision("585f640ecf98")
    assert revision is not None and revision.down_revision == "ba759824c979"


def test_repository_stages_exact_row_without_query_or_finalization() -> None:
    session = MagicMock(spec=Session)
    row = AuditLog(
        actor_id=uuid4(),
        action="Device.updated",
        resource_type="device",
        resource_id=uuid4(),
        event_metadata={"fields": ["name"]},
    )
    repo = AuditLogRepository(session)
    assert repo.session is session
    repo.add(row)
    assert session.method_calls == [call.add(row)]
    assert {name for name in vars(AuditLogRepository) if not name.startswith("_")} == {
        "add"
    }


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("injected"),
        OperationalError("injected", {}, RuntimeError("injected")),
    ],
)
def test_repository_propagates_original_errors(error: Exception) -> None:
    session = MagicMock(spec=Session)
    session.add.side_effect = error
    row = AuditLog(
        actor_id=uuid4(),
        action="device.updated",
        resource_type="device",
        resource_id=uuid4(),
    )
    with pytest.raises(type(error)) as caught:
        AuditLogRepository(session).add(row)
    assert caught.value is error
    assert session.method_calls == [call.add(row)]
