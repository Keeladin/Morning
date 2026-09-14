from __future__ import annotations

from dataclasses import dataclass
from os import environ
from typing import Mapping


class ConfigError(RuntimeError):
    """Raised when deployment configuration is invalid or incomplete."""


_PLACEHOLDER_MARKERS = ("replace-with", "replace_me", "change-me", "changeme", "placeholder")


def _looks_placeholder(value: str) -> bool:
    lowered = value.strip().casefold()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str | None
    session_secret: str | None

    @property
    def production(self) -> bool:
        return self.environment == "production"

    @classmethod
    def from_env(cls, source: Mapping[str, str] | None = None) -> "Settings":
        values = environ if source is None else source
        environment = str(values.get("MORNING_ENV", "development")).strip().lower() or "development"
        if environment not in {"development", "test", "production"}:
            raise ConfigError("MORNING_ENV must be one of: development, test, production")

        database_url = str(values.get("MORNING_DATABASE_URL", "")).strip() or None
        session_secret = str(values.get("MORNING_SESSION_SECRET", "")).strip() or None

        if environment == "production":
            missing: list[str] = []
            if database_url is None:
                missing.append("MORNING_DATABASE_URL")
            if session_secret is None:
                missing.append("MORNING_SESSION_SECRET")
            if missing:
                raise ConfigError(f"missing required production configuration: {', '.join(missing)}")
            assert database_url is not None and session_secret is not None
            if _looks_placeholder(database_url):
                raise ConfigError("MORNING_DATABASE_URL contains placeholder credentials")
            if len(session_secret) < 32:
                raise ConfigError("MORNING_SESSION_SECRET must be at least 32 characters in production")
            if _looks_placeholder(session_secret):
                raise ConfigError("MORNING_SESSION_SECRET must not use placeholder material")

        return cls(
            environment=environment,
            database_url=database_url,
            session_secret=session_secret,
        )
