"""Argon2id credentials and verified application access tokens."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import SecretStr


@dataclass(frozen=True, kw_only=True)
class AuthConfig:
    """Validated app-owned context; construct once from Settings during startup.

    Validate the configured signing key and TTL before serving requests.
    Generate one valid Argon2id dummy hash at startup, never per failed login.
    This context is not a separate environment-settings loader.
    """

    signing_key: SecretStr = field(repr=False)
    access_token_ttl_seconds: int
    dummy_password_hash: SecretStr = field(repr=False)

    def __post_init__(self) -> None:
        key = self.signing_key.get_secret_value()

        if not key.strip():
            raise ValueError("JWT signing key must not be blank")

        if len(key.encode("utf-8")) < 32:
            raise ValueError("JWT signing key must be at least 32 UTF-8 bytes")

        # Normalize only for screening; preserve the original signing bytes.
        normalized_key = key.strip().lower()

        placeholder_markers = (
            "change-me",
            "changeme",
            "replace-me",
            "your-secret",
            "your-secret-key",
            "example-secret",
            "dummy-secret",
        )

        if any(marker in normalized_key for marker in placeholder_markers):
            raise ValueError(
                "JWT signing key must not use an obvious placeholder value"
            )

        if not 60 <= self.access_token_ttl_seconds <= 3600:
            raise ValueError("Access token TTL must be between 60 and 3600 seconds")


@dataclass(frozen=True, kw_only=True)
class AccessTokenClaims:
    """Verified access-token identity and aware UTC lifetime."""

    subject: UUID
    issued_at: datetime
    expires_at: datetime


class InvalidAccessTokenError(Exception):
    """Expected malformed, unsupported, expired or unauthentic access token."""


_PASSWORD_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    """Produce an Argon2id encoded hash for users.password_hash."""
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify exactly; mismatch or invalid stored hash returns False.

    Catch expected verifier failures only; unexpected faults must propagate.
    Never normalize, truncate or log either credential value.
    """
    try:
        return _PASSWORD_HASHER.verify(encoded_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: UUID, *, config: AuthConfig) -> str:
    """Issue HS256 with UUID sub, UTC iat/exp and token_type=access."""
    issued_at = int(datetime.now(UTC).timestamp())
    expires_at = issued_at + config.access_token_ttl_seconds
    payload = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": expires_at,
        "token_type": "access",
    }

    return jwt.encode(
        payload,
        config.signing_key.get_secret_value(),
        algorithm="HS256",
    )


def decode_access_token(token: str, *, config: AuthConfig) -> AccessTokenClaims:
    """Verify fixed HS256/signature and strictly validate required claims.

    Reject invalid tokens with InvalidAccessTokenError. Never trust role/active
    claims, token-selected algorithms or an unverified payload.
    """
    try:
        payload = jwt.decode(
            token,
            config.signing_key.get_secret_value(),
            algorithms=["HS256"],
            options={
                "require": ["sub", "iat", "exp", "token_type"],
            },
        )
    except jwt.InvalidTokenError as exc:
        raise InvalidAccessTokenError("Invalid access token") from exc

    subject = payload["sub"]
    issued_at = payload["iat"]
    expires_at = payload["exp"]
    token_type = payload["token_type"]

    if (
        type(subject) is not str
        or type(issued_at) is not int
        or type(expires_at) is not int
        or token_type != "access"
    ):
        raise InvalidAccessTokenError("Invalid access token")

    try:
        subject_uuid = UUID(subject)
    except ValueError as exc:
        raise InvalidAccessTokenError("Invalid access token") from exc

    now = int(datetime.now(UTC).timestamp())

    if expires_at <= issued_at or issued_at > now or expires_at <= now:
        raise InvalidAccessTokenError("Invalid access token")

    try:
        issued_at_dt = datetime.fromtimestamp(issued_at, tz=UTC)
        expires_at_dt = datetime.fromtimestamp(expires_at, tz=UTC)
    except (ValueError, OverflowError, OSError) as exc:
        raise InvalidAccessTokenError("Invalid access token") from exc

    return AccessTokenClaims(
        subject=subject_uuid,
        issued_at=issued_at_dt,
        expires_at=expires_at_dt,
    )
