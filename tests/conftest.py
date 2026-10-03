"""Test-only signing configuration for the V2 authentication startup contract."""

import pytest

TEST_SIGNING_KEY = "v2-test-only-signing-key-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@pytest.fixture(autouse=True)
def test_signing_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supply a public fixture key without changing any database safety setting."""
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_SIGNING_KEY)
