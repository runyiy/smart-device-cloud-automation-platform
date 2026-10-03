"""V2-T5 actual credential/JWT and authentication ownership acceptance."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import jwt
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth import security, service
from app.auth.schema import CurrentUserRead, LoginRequest
from app.auth.security import (
    AuthConfig,
    InvalidAccessTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.auth.service import AuthenticationError
from app.core.config import Settings
from app.main import create_app
from app.users.model import User, UserRole
from tests.conftest import TEST_SIGNING_KEY


@pytest.fixture(scope="module")
def encoded_password() -> str:
    return hash_password("  密码 pass  ")


@pytest.fixture
def config(encoded_password: str) -> AuthConfig:
    return AuthConfig(
        signing_key=SecretStr(TEST_SIGNING_KEY),
        access_token_ttl_seconds=900,
        dummy_password_hash=SecretStr(encoded_password),
    )


def test_schema_normalizes_only_identifier_and_allowlists_public_fields() -> None:
    data = LoginRequest.model_validate(
        {"email": " A@EXAMPLE.TEST ", "password": "  密码 pass  "}
    )
    assert data.email == "a@example.test"
    assert data.password.get_secret_value() == "  密码 pass  "
    assert (
        "  密码 pass  " not in repr(data)
        and "  密码 pass  " not in data.model_dump_json()
    )
    now = datetime.now(UTC).astimezone(timezone(timedelta(hours=8)))
    user = User(
        id=uuid4(),
        email=data.email,
        password_hash="never-expose-hash",
        role=UserRole.OPERATOR,
        is_active=True,
        created_at=now,
    )
    public = CurrentUserRead.model_validate(user).model_dump(mode="json")
    assert set(public) == {"id", "email", "role", "is_active", "created_at"}
    assert public["role"] == "operator"
    assert str(public["created_at"]).endswith("Z")
    assert "hash" not in str(public)


@pytest.mark.parametrize(
    "changes",
    [
        {"email": ""},
        {"email": " "},
        {"email": "x" * 255},
        {"email": None},
        {"email": 1},
        {"password": ""},
        {"password": "x" * 1025},
        {"password": None},
        {"password": 1},
        {"password": b"bytes"},
        {"role": "admin"},
    ],
)
def test_schema_rejects_invalid_input(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        LoginRequest.model_validate({"email": "a", "password": "p", **changes})


def test_actual_argon2_exact_password_salt_and_invalid_hashes(
    encoded_password: str,
) -> None:
    assert encoded_password.startswith("$argon2id$") and len(encoded_password) <= 255
    assert hash_password("  密码 pass  ") != encoded_password
    assert verify_password("  密码 pass  ", encoded_password)
    assert not verify_password("密码 pass", encoded_password)
    for malformed in ("", "opaque", "$argon2id$bad", "$2b$bad"):
        assert not verify_password("p", malformed)


def test_unexpected_verifier_failure_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = MagicMock()
    verifier.verify.side_effect = RuntimeError("unexpected")
    monkeypatch.setattr(security, "_PASSWORD_HASHER", verifier)
    with pytest.raises(RuntimeError, match="unexpected"):
        verify_password("p", "h")


@pytest.mark.parametrize(
    "key",
    [
        "",
        " " * 40,
        "short",
        "change-me-change-me-change-me-change-me",
        "your-secret-key-change-me-before-production",
    ],
)
def test_auth_config_rejects_weak_or_placeholder_key(key: str) -> None:
    with pytest.raises(ValueError):
        AuthConfig(
            signing_key=SecretStr(key),
            access_token_ttl_seconds=900,
            dummy_password_hash=SecretStr("unused"),
        )


@pytest.mark.parametrize(
    "key", ["", " " * 40, "short", "change-me-change-me-change-me-change-me"]
)
def test_startup_rejects_bad_key(key: str) -> None:
    with pytest.raises(ValueError):
        create_app(
            Settings(
                _env_file=None,
                database_url=SecretStr("unused"),
                jwt_secret_key=SecretStr(key),
            )
        )


def test_missing_secret_and_ttl_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=SecretStr("unused"))
    for ttl in (59, 3601):
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                database_url=SecretStr("unused"),
                jwt_secret_key=SecretStr(TEST_SIGNING_KEY),
                access_token_ttl_seconds=ttl,
            )


def test_actual_token_roundtrip_and_private_context(config: AuthConfig) -> None:
    subject = uuid4()
    token = create_access_token(subject, config=config)
    claims = decode_access_token(token, config=config)
    payload = jwt.decode(token, TEST_SIGNING_KEY, algorithms=["HS256"])
    assert set(payload) == {"sub", "iat", "exp", "token_type"}
    assert payload["token_type"] == "access"
    assert payload["exp"] - payload["iat"] == 900
    assert claims.subject == subject
    assert claims.issued_at.tzinfo is UTC and claims.expires_at.tzinfo is UTC
    assert TEST_SIGNING_KEY not in repr(config)


@pytest.mark.parametrize("missing", ["sub", "iat", "exp", "token_type"])
def test_missing_claims_reject(config: AuthConfig, missing: str) -> None:
    now = int(datetime.now(UTC).timestamp())
    payload = {
        "sub": str(uuid4()),
        "iat": now,
        "exp": now + 900,
        "token_type": "access",
    }
    del payload[missing]
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(
            jwt.encode(payload, TEST_SIGNING_KEY, algorithm="HS256"), config=config
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"sub": "not-uuid"},
        {"sub": 1},
        {"sub": []},
        {"sub": {}},
        {"iat": True},
        {"iat": "1"},
        {"iat": 1.5},
        {"iat": []},
        {"iat": {}},
        {"iat": float("inf")},
        {"exp": True},
        {"exp": "9999999999"},
        {"exp": 9999999999.5},
        {"exp": []},
        {"exp": {}},
        {"exp": float("inf")},
        {"token_type": "refresh"},
        {"token_type": ["access"]},
        {"iat": 9999999999},
        {"exp": 1},
        {"iat": 1, "exp": 1},
    ],
)
def test_invalid_claim_shapes_always_reject_as_expected(
    config: AuthConfig,
    changes: dict[str, Any],
) -> None:
    now = int(datetime.now(UTC).timestamp())
    payload = {
        "sub": str(uuid4()),
        "iat": now,
        "exp": now + 900,
        "token_type": "access",
        **changes,
    }
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(
            jwt.encode(payload, TEST_SIGNING_KEY, algorithm="HS256"), config=config
        )


@pytest.mark.parametrize(
    "algorithm,key",
    [
        ("HS384", TEST_SIGNING_KEY),
        ("HS256", "different-test-signing-key-" * 3),
        ("none", ""),
    ],
)
def test_algorithm_key_and_unsigned_tokens_reject(
    config: AuthConfig,
    algorithm: str,
    key: str,
) -> None:
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {"sub": str(uuid4()), "iat": now, "exp": now + 900, "token_type": "access"},
        key,
        algorithm=algorithm,
    )
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, config=config)


@pytest.mark.parametrize("token", ["", "garbage", "a.b.c"])
def test_malformed_tokens_reject(config: AuthConfig, token: str) -> None:
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, config=config)


@pytest.mark.parametrize("case", ["active", "missing", "wrong", "inactive", "db-error"])
def test_login_ownership_dummy_and_failure_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    config: AuthConfig,
    case: str,
) -> None:
    session = MagicMock(spec=Session)
    repo = MagicMock()
    constructor = MagicMock(return_value=repo)
    monkeypatch.setattr(service, "UserRepository", constructor)
    user = User(
        id=uuid4(), email="a", password_hash="real-hash", is_active=case != "inactive"
    )
    repo.get_by_email.return_value = None if case == "missing" else user
    if case == "db-error":
        repo.get_by_email.side_effect = OperationalError(
            "statement", {}, Exception("db")
        )
    verify = MagicMock(return_value=case != "wrong")
    issue = MagicMock(return_value="issued")
    monkeypatch.setattr(service, "verify_password", verify)
    monkeypatch.setattr(service, "create_access_token", issue)
    data = LoginRequest.model_validate({"email": " A ", "password": " p "})
    if case == "active":
        assert service.login(session, data, config=config).access_token == "issued"
        issue.assert_called_once_with(user.id, config=config)
    elif case == "db-error":
        with pytest.raises(OperationalError):
            service.login(session, data, config=config)
        verify.assert_not_called()
    else:
        with pytest.raises(AuthenticationError):
            service.login(session, data, config=config)
        issue.assert_not_called()
    constructor.assert_called_once_with(session)
    repo.get_by_email.assert_called_once_with("a")
    if case != "db-error":
        expected = (
            config.dummy_password_hash.get_secret_value()
            if case == "missing"
            else "real-hash"
        )
        verify.assert_called_once_with(password=" p ", encoded_hash=expected)
    for method in ("add", "flush", "commit", "rollback", "close"):
        getattr(session, method).assert_not_called()


def test_current_identity_reads_db_and_does_not_finalize(
    monkeypatch: pytest.MonkeyPatch,
    config: AuthConfig,
) -> None:
    session = MagicMock(spec=Session)
    repo = MagicMock()
    monkeypatch.setattr(service, "UserRepository", MagicMock(return_value=repo))
    user = User(id=uuid4(), is_active=True)
    token = create_access_token(user.id, config=config)
    repo.get.return_value = user
    assert service.resolve_current_user(session, token, config=config) is user
    repo.get.assert_called_once_with(user.id)
    for current in (None, User(is_active=False)):
        repo.get.return_value = current
        with pytest.raises(AuthenticationError):
            service.resolve_current_user(session, token, config=config)
    repo.get.side_effect = OperationalError("statement", {}, Exception("db"))
    with pytest.raises(OperationalError):
        service.resolve_current_user(session, token, config=config)
    for method in ("add", "flush", "commit", "rollback", "close"):
        getattr(session, method).assert_not_called()


def test_auth_libraries_are_declared_runtime_dependencies() -> None:
    import re
    import tomllib
    from pathlib import Path

    project = tomllib.loads(Path("pyproject.toml").read_text())
    dependencies = project["project"]["dependencies"]
    names = {
        re.split(r"[<>=!~\\[; ]", value, maxsplit=1)[0].lower()
        for value in dependencies
    }
    assert {"pyjwt", "argon2-cffi"} <= names, (
        "Both imported auth libraries must be declared"
    )
