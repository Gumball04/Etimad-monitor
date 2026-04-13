from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Etimad Tender Monitor", validation_alias=AliasChoices("APP_NAME"))
    app_env: str = Field(default="development", validation_alias=AliasChoices("APP_ENV"))
    api_prefix: str = Field(default="/api", validation_alias=AliasChoices("API_PREFIX"))
    frontend_url: str = Field(default="http://localhost:5173", validation_alias=AliasChoices("FRONTEND_URL"))
    app_timezone: str = Field(default="Asia/Amman", validation_alias=AliasChoices("APP_TIMEZONE", "TZ"))
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/etimad_monitor",
        validation_alias=AliasChoices("DATABASE_URL"),
    )

    smtp_host: str = Field(default="smtp.gmail.com", validation_alias=AliasChoices("SMTP_HOST"))
    smtp_port: int = Field(default=587, validation_alias=AliasChoices("SMTP_PORT"))
    smtp_username: str | None = Field(default=None, validation_alias=AliasChoices("SMTP_USERNAME"))
    smtp_password: str | None = Field(default=None, validation_alias=AliasChoices("SMTP_PASSWORD"))
    smtp_from: str | None = Field(default=None, validation_alias=AliasChoices("SMTP_FROM"))
    smtp_use_tls: bool = Field(default=True, validation_alias=AliasChoices("SMTP_USE_TLS"))
    smtp_use_ssl: bool = Field(default=False, validation_alias=AliasChoices("SMTP_USE_SSL"))
    smtp_ssl_port: int = Field(default=465, validation_alias=AliasChoices("SMTP_SSL_PORT"))
    smtp_ssl_fallback: bool = Field(default=True, validation_alias=AliasChoices("SMTP_SSL_FALLBACK"))
    smtp_timeout_seconds: int = Field(default=30, validation_alias=AliasChoices("SMTP_TIMEOUT_SECONDS"))
    fixed_email_recipient: str | None = Field(default=None, validation_alias=AliasChoices("FIXED_EMAIL_RECIPIENT"))
    email_copy_fixed_recipient: bool = Field(
        default=True,
        validation_alias=AliasChoices("EMAIL_COPY_FIXED_RECIPIENT"),
    )

    playwright_headless: bool = Field(default=True, validation_alias=AliasChoices("PLAYWRIGHT_HEADLESS"))
    playwright_timeout_ms: int = Field(default=45000, validation_alias=AliasChoices("PLAYWRIGHT_TIMEOUT_MS"))
    playwright_max_pages: int = Field(default=10, validation_alias=AliasChoices("PLAYWRIGHT_MAX_PAGES"))
    playwright_page_size: int = Field(default=6, validation_alias=AliasChoices("PLAYWRIGHT_PAGE_SIZE"))
    playwright_concurrency: int = Field(default=3, validation_alias=AliasChoices("PLAYWRIGHT_CONCURRENCY"))
    playwright_user_data_dir: str = Field(
        default=str(BACKEND_DIR / ".playwright-profile"),
        validation_alias=AliasChoices("PLAYWRIGHT_USER_DATA_DIR"),
    )

    export_dir: Path = Field(default=BACKEND_DIR / "exports", validation_alias=AliasChoices("EXPORT_DIR"))
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL"))

    @field_validator(
        "app_name",
        "app_env",
        "api_prefix",
        "frontend_url",
        "app_timezone",
        "database_url",
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "smtp_from",
        "fixed_email_recipient",
        "playwright_user_data_dir",
        "log_level",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: str | None):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql://", 1)
        return value

    @field_validator("export_dir", mode="before")
    @classmethod
    def _normalize_export_dir(cls, value: str | Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        return path

    @property
    def timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.app_timezone or "Asia/Amman")
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    @property
    def smtp_enabled(self) -> bool:
        return bool(
            self.smtp_host
            and self.smtp_from
            and self.smtp_username
            and self.smtp_password
        )

    @property
    def fixed_email_enabled(self) -> bool:
        return bool(self.smtp_enabled and self.fixed_email_recipient)


settings = Settings()
