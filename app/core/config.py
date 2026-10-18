"""Application settings, read from environment variables (or a .env file in development)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Safe by default: anything not explicitly marked development or test runs as production.
    environment: Literal["development", "test", "production"] = "production"
    app_name: str = "CIDMS"

    # The app connects as a role that can't bypass row-level security; migrations run as the tables' owner.
    database_url: str = "postgresql+psycopg://supreme_app:local-app-only@localhost:5433/supreme"
    migration_database_url: str = "postgresql+psycopg://supreme_owner:local-owner-only@localhost:5433/supreme"

    # Clients are reached at <slug>.<base_domain>; platform staff at <platform_subdomain>.<base_domain>.
    base_domain: str = "localhost"
    platform_subdomain: str = "admin"

    # Sessions
    session_secret: str = Field(default="dev-only-change-me-0123456789", min_length=16)
    session_idle_minutes: int = 8 * 60
    session_absolute_days: int = 30       # "Remember me": signed in on that computer for up to this long
    session_browser_hours: int = 12       # without it: until the browser closes, and at most this long
    password_reset_minutes: int = 30

    # Email (password reset links). Any SMTP service works, e.g. Gmail with an app password.
    # Not set in development: the reset link is written to the app's log instead.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    mail_from: str = "CIDMS <no-reply@localhost>"

    # Sign-in protection: lock an account for a while after repeated wrong passwords.
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    min_password_length: int = 10

    # First sign-in details used by "python -m app.seed" (each person must change the password at first sign-in).
    seed_platform_owner_email: str = "owner@supremedms.local"
    seed_platform_owner_password: str = "Change-me-now-1"  # noqa: S105 (local default; app.seed refuses it in production)
    seed_supreme_owner_email: str = "owner@supreme.local"
    seed_supreme_owner_password: str = "Change-me-now-1"  # noqa: S105 (local default; app.seed refuses it in production)

    # Files the app keeps (logos now; signatures, reports and uploads later), outside the web folder.
    storage_dir: str = "storage"
    # The server's backup folder (deploy/backup.sh), mounted read-only into the app for downloads.
    backup_dir: str = "backups"

    # Medical images: the Orthanc image server (only the app talks to it, with these credentials) and the
    # OHIF viewer, both reached through the app at /api/dicom-web and /viewer so they share its sign-in.
    orthanc_url: str = "http://127.0.0.1:8042"
    orthanc_user: str = "supreme"
    orthanc_password: str = "local-orthanc-only"  # noqa: S105 (local default, like the database's)
    ohif_url: str = "http://127.0.0.1:3005"
    imaging_max_upload_mb: int = 500

    # Sending signed reports to patients on WhatsApp. "" = off; "meta" = WhatsApp Business Cloud API, sending
    # the approved template `whatsapp_template` (document header; body {{1}} patient name, {{2}} centre name,
    # {{3}} the patient's link to view the report online).
    whatsapp_provider: str = ""
    whatsapp_token: str = Field(default="", repr=False)
    whatsapp_phone_number_id: str = ""
    whatsapp_template: str = "report_ready"
    whatsapp_template_lang: str = "en"
    whatsapp_api_version: str = "v21.0"
    whatsapp_verify_token: str = Field(default="", repr=False)  # the webhook's subscribe check
    whatsapp_app_secret: str = Field(default="", repr=False)    # checks X-Hub-Signature-256 on webhook calls

    # The web app's database limits (seconds): the longest a statement may run, and the longest a transaction
    # may sit idle. Exports too big for this go to the background worker.
    db_statement_timeout_s: int = 30
    db_idle_in_transaction_timeout_s: int = 60

    # Signs the links printed on reports (QR codes). Unset: SESSION_SECRET (as before). Set it to the current
    # SESSION_SECRET before ever changing that, so printed reports keep working.
    report_link_secret: str = Field(default="", repr=False)

    # Request and response bodies encrypted between the browser and the app (AES-GCM, key agreed by ECDH), so they
    # can't be read in the browser's network tools or by anything in between. "optional": the app's own pages always
    # encrypt, other callers may send plain JSON; "required": plain JSON to /api is refused (except the integration
    # API, webhooks and health checks); "off": never.
    payload_encryption: Literal["off", "optional", "required"] = "optional"

    # The patient's link to a signed report (the QR code on it): how long it works.
    report_link_days: int = 90
    # The reporting dashboard: how long a test may wait for its signed report before it counts as overdue.
    report_target_hours_imaging: int = 24
    report_target_hours_other: int = 48

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
