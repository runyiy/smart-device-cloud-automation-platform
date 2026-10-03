"""Authentication decisions over the accepted caller-owned UserRepository."""

from sqlalchemy.orm import Session

from app.auth.schema import LoginRequest, TokenResponse
from app.auth.security import (
    AuthConfig,
    InvalidAccessTokenError,
    create_access_token,
    decode_access_token,
    verify_password,
)
from app.users.model import User
from app.users.repository import UserRepository


class AuthenticationError(Exception):
    """Uniform denial; do not distinguish account existence or active state."""


def login(
    session: Session,
    data: LoginRequest,
    *,
    config: AuthConfig,
) -> TokenResponse:
    """Look up an exact email, verify credentials and issue for an active User.

    No writes, lock, commit/rollback/close or automatic credential rehash.
    SQLAlchemy and unexpected errors propagate to sanitized HTTP handling.
    """
    repo_user = UserRepository(session)
    user = repo_user.get_by_email(data.email)

    password = data.password.get_secret_value()

    if user is None:
        # Verify the startup dummy hash before the uniform missing-user denial.
        verify_password(
            password=password,
            encoded_hash=config.dummy_password_hash.get_secret_value(),
        )
        raise AuthenticationError("authentication error")

    if not verify_password(
        password=password,
        encoded_hash=user.password_hash,
    ):
        raise AuthenticationError("authentication error")

    if not user.is_active:
        raise AuthenticationError("authentication error")

    access_token = create_access_token(
        user.id,
        config=config,
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
    )


def resolve_current_user(
    session: Session,
    token: str,
    *,
    config: AuthConfig,
) -> User:
    """Decode and read the current User; reject missing or inactive accounts.

    Use a fresh request Session and an ordinary Repository read, not token roles.
    Map only expected token failures to AuthenticationError; do not hide DB faults.
    """

    try:
        claims = decode_access_token(
            token,
            config=config,
        )
    except InvalidAccessTokenError as exc:
        raise AuthenticationError("authentication error") from exc

    repo_user = UserRepository(session)

    user = repo_user.get(claims.subject)

    if user is None:
        raise AuthenticationError("authentication error")

    if not user.is_active:
        raise AuthenticationError("authentication error")

    return user
