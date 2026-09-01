from enum import StrEnum
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SETTINGS_FILE = ".env"
TEST_SETTINGS_FILE = ".env.test"


class Environment(StrEnum):
    """Runtime environments supported by V0."""

    DEVELOPMENT = "development"
    TEST = "test"


class Settings(BaseSettings):
    """Environment-backed settings shared by later V0 tasks."""

    model_config = SettingsConfigDict(
        env_file=DEFAULT_SETTINGS_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Smart Device Cloud & Automation Platform"
    app_version: str = "0.1.0"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    database_url: SecretStr


@lru_cache
def get_settings(env_file: str = DEFAULT_SETTINGS_FILE) -> Settings:
    return Settings(_env_file=env_file)
