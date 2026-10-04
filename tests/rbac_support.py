"""Explicit legacy business-test authentication; never globally override RBAC."""

from functools import lru_cache
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.auth.security import AuthConfig, create_access_token, hash_password
from app.core.config import Environment, Settings
from app.users.model import User, UserRole
from tests.integration.test_migrations import validate_test_database


@lru_cache
def legacy_admin_hash() -> str:
    return hash_password("legacy-test-only-password")


def admin_test_client(
    app: FastAPI,
    engine: Engine,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    """Use a real fixture admin and JWT for this explicit guarded database app."""
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=engine.url.render_as_string(hide_password=False),
    )
    validate_test_database(settings)
    with Session(engine) as session:
        user = session.scalar(
            select(User).where(User.email == "legacy-admin@example.test")
        )
        if user is None:
            user = User(
                email="legacy-admin@example.test",
                password_hash=legacy_admin_hash(),
                role=UserRole.ADMIN,
            )
            session.add(user)
            session.commit()
        assert user.role is UserRole.ADMIN and user.is_active
        user_id = user.id
    token = create_access_token(user_id, config=cast(AuthConfig, app.state.auth_config))
    return TestClient(
        app,
        headers={"Authorization": f"Bearer {token}"},
        raise_server_exceptions=raise_server_exceptions,
    )


@pytest.fixture
def business_actor_id(device_engine: Engine) -> UUID:
    """Persist one explicit actor for legacy direct-Service database tests.

    This fixture uses the requesting module's guarded migrated test Engine.
    It neither changes the caller's Session nor bypasses auth, audit or FK checks.
    """
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=device_engine.url.render_as_string(hide_password=False),
    )
    validate_test_database(settings)
    with Session(device_engine) as session:
        user = User(
            email="business-actor@example.test",
            password_hash=legacy_admin_hash(),
            role=UserRole.ADMIN,
        )
        session.add(user)
        session.commit()
        return user.id
