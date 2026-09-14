from __future__ import annotations

import pytest

from morning.config import ConfigError, Settings


def test_development_can_boot_without_database_or_session_secret() -> None:
    settings = Settings.from_env({})
    assert settings.environment == "development"
    assert settings.database_url is None
    assert settings.session_secret is None


def test_production_requires_database_and_session_secret() -> None:
    with pytest.raises(ConfigError, match="MORNING_DATABASE_URL, MORNING_SESSION_SECRET"):
        Settings.from_env({"MORNING_ENV": "production"})


def test_production_accepts_explicit_morning_owned_configuration() -> None:
    settings = Settings.from_env(
        {
            "MORNING_ENV": "production",
            "MORNING_DATABASE_URL": "postgresql://morning@example/morning",
            "MORNING_SESSION_SECRET": "a-real-morning-session-secret-0123456789",
        }
    )
    assert settings.production is True
    assert settings.database_url == "postgresql://morning@example/morning"


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ConfigError, match="MORNING_ENV"):
        Settings.from_env({"MORNING_ENV": "staging-ish"})


def test_production_rejects_placeholder_or_short_secrets() -> None:
    with pytest.raises(ConfigError, match="placeholder"):
        Settings.from_env({
            "MORNING_ENV": "production",
            "MORNING_DATABASE_URL": "postgresql://morning:real-password@db/morning",
            "MORNING_SESSION_SECRET": "replace-with-at-least-32-random-bytes",
        })
    with pytest.raises(ConfigError, match="at least 32"):
        Settings.from_env({
            "MORNING_ENV": "production",
            "MORNING_DATABASE_URL": "postgresql://morning:real-password@db/morning",
            "MORNING_SESSION_SECRET": "too-short",
        })


def test_production_rejects_placeholder_database_credentials() -> None:
    with pytest.raises(ConfigError, match="MORNING_DATABASE_URL contains placeholder"):
        Settings.from_env({
            "MORNING_ENV": "production",
            "MORNING_DATABASE_URL": "postgresql://morning:replace-with-a-password@db/morning",
            "MORNING_SESSION_SECRET": "a-real-morning-session-secret-0123456789",
        })
