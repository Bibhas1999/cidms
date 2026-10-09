"""Application settings, read from environment variables (or a .env file in development)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Safe by default: anything not explicitly marked development or test runs as production.
    environment: Literal["development", "test", "production"] = "production"
    app_name: str = "Supreme DMS"

    # The app connects as a role that can't bypass row-level security; migrations run as the tables' owner.
    database_url: str = "postgresql+psycopg://supreme_app:local-app-only@localhost:5433/supreme"
    migration_database_url: str = "postgresql+psycopg://supreme_owner:local-owner-only@localhost:5433/supreme"

    # Clients are reached at <slug>.<base_domain>; platform staff at <platform_subdomain>.<base_domain>.
    base_domain: str = "localhost"
    platform_subdomain: str = "admin"

    # Sessions
    session_secret: str = Field(default="dev-only-change-me-0123456789", min_length=16)
    session_idle_minutes: int = 8 * 60
    session_absolute_days: int = 7

    # Sign-in protection: lock an account for a while after repeated wrong passwords.
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    min_password_length: int = 10

    # First sign-in details used by "python -m app.seed" (each person must change the password at first sign-in).
    seed_platform_owner_email: str = "owner@supremedms.local"
    seed_platform_owner_password: str = "Change-me-now-1"  # noqa: S105 (local default; app.seed refuses it in production)
    seed_supreme_owner_email: str = "owner@supreme.local"
    seed_supreme_owner_password: str = "Change-me-now-1"  # noqa: S105 (local default; app.seed refuses it in production)

    log_level: str = "INFO"
    display_timezone: str = "Asia/Kolkata"  # dates are stored in UTC and shown in this time zone

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cookie_name(self) -> str:
        # The __Host- prefix makes browsers insist on Secure, Path=/ and no Domain attribute, so a session
        # cookie set for one client's subdomain is never sent to another's.
        return "__Host-sdms_session" if self.is_production else "sdms_session"

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if self.is_production:
            problems = []
            if "local-app-only" in self.database_url or "local-owner-only" in self.migration_database_url:
                problems.append("DATABASE_URL and MIGRATION_DATABASE_URL must not use the local development passwords")
            if self.session_secret.startswith("dev-only") or len(self.session_secret) < 32:
                problems.append("SESSION_SECRET must be a random value of at least 32 characters")
            if self.base_domain == "localhost":
                problems.append("BASE_DOMAIN must be the product's real domain")
            if problems:
                raise ValueError("Unsafe production settings: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
