"""Responsabilidade: implementa o modulo app/config.py."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Moodle Sheets Bridge"
    app_env: str = "dev"
    app_debug: bool = False
    log_level: str = "INFO"
    log_file: str = "logs/middleware.log"
    api_host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("API_HOST", "APP_HOST"))
    api_port: int = Field(default=8000, validation_alias=AliasChoices("API_PORT", "APP_PORT"))
    api_rate_limit_per_minute: int = Field(
        default=60,
        validation_alias=AliasChoices("API_RATE_LIMIT_PER_MINUTE"),
    )
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        validation_alias=AliasChoices("CORS_ALLOWED_ORIGINS"),
    )
    trust_proxy_headers: bool = Field(
        default=False,
        validation_alias=AliasChoices("TRUST_PROXY_HEADERS"),
    )

    moodle_base_url: str = Field(
        validation_alias=AliasChoices("MOODLE_BASE_URL", "MOODLE_URL"),
    )
    moodle_token: str
    moodle_ws_format: str = Field(
        default="json",
        validation_alias=AliasChoices("MOODLE_WSFORMAT", "MOODLE_WS_FORMAT"),
    )
    moodle_rest_endpoint: str = "/webservice/rest/server.php"
    moodle_timeout_seconds: float = Field(
        default=10.0,
        validation_alias=AliasChoices("MOODLE_TIMEOUT_SECONDS", "MOODLE_TIMEOUT"),
    )
    moodle_max_retries: int = Field(
        default=3,
        validation_alias=AliasChoices("MOODLE_MAX_RETRIES", "REQUEST_MAX_RETRIES"),
    )
    moodle_batch_size: int = 100
    moodle_max_concurrency: int = Field(
        default=20,
        validation_alias=AliasChoices("MOODLE_MAX_CONCURRENCY", "SYNC_BATCH_SIZE"),
    )
    moodle_default_role_id: int = 5
    moodle_default_new_user_password: str = Field(
        default="Temp@12345",
        validation_alias=AliasChoices("MOODLE_DEFAULT_NEW_USER_PASSWORD"),
    )
    moodle_default_course_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    moodle_custom_metrics_functions: Annotated[list[str], NoDecode] = Field(default_factory=list)

    google_service_account_file: str = Field(
        validation_alias=AliasChoices("GOOGLE_SERVICE_ACCOUNT_FILE", "GOOGLE_CREDENTIALS_FILE"),
    )
    google_spreadsheet_id: str = Field(
        validation_alias=AliasChoices("GOOGLE_SPREADSHEET_ID", "SPREADSHEET_ID"),
    )
    google_oauth_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_OAUTH_CLIENT_ID"),
    )
    google_oauth_client_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_OAUTH_CLIENT_SECRET"),
    )
    google_oauth_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/google-sheets/oauth/callback",
        validation_alias=AliasChoices("GOOGLE_OAUTH_REDIRECT_URI"),
    )
    google_oauth_refresh_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_OAUTH_REFRESH_TOKEN"),
    )
    google_students_sheet: str = "students"
    google_courses_sheet: str = "courses"
    google_categories_sheet: str = "categories"
    google_course_contents_sheet: str = "course_contents"
    google_enrollments_sheet: str = "enrollments"
    google_grades_sheet: str = "grades"
    google_completion_sheet: str = "completion"
    google_progress_sheet: str = "progress"
    google_logs_sheet: str = "logs"
    google_badges_sheet: str = "badges"
    google_competencies_sheet: str = "competencies"
    google_groups_sheet: str = "groups"
    google_group_members_sheet: str = "group_members"
    google_groupings_sheet: str = "groupings"
    google_custom_metrics_sheet: str = "custom_metrics"
    google_students_input_sheet: str = "students_input"
    google_enrollments_input_sheet: str = "Inscrever Novos Alunos"
    google_sync_events_sheet: str = "Log de Sincronização"

    sync_interval_minutes: int = 0
    sync_auto_direction: str = "moodle_to_sheets"
    sync_state_db_path: str = "sync_state.db"
    sync_batch_size: int = Field(default=50, validation_alias=AliasChoices("SYNC_BATCH_SIZE"))

    middleware_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MIDDLEWARE_API_KEY", "API_SECRET_KEY"),
    )
    auth_username: str = Field(
        default="admin",
        validation_alias=AliasChoices("AUTH_USERNAME", "API_AUTH_USERNAME"),
    )
    auth_password: str = Field(
        default="",
        validation_alias=AliasChoices("AUTH_PASSWORD", "API_AUTH_PASSWORD"),
    )
    auth_jwt_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("AUTH_JWT_SECRET_KEY", "JWT_SECRET_KEY"),
    )
    auth_jwt_algorithm: str = Field(
        default="HS256",
        validation_alias=AliasChoices("AUTH_JWT_ALGORITHM"),
    )
    auth_access_token_minutes: int = Field(
        default=60,
        validation_alias=AliasChoices("AUTH_ACCESS_TOKEN_MINUTES"),
    )
    security_content_security_policy: str = Field(
        default=(
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "script-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        ),
        validation_alias=AliasChoices("SECURITY_CONTENT_SECURITY_POLICY", "SECURITY_CSP"),
    )
    security_permissions_policy: str = Field(
        default="camera=(), microphone=(), geolocation=()",
        validation_alias=AliasChoices("SECURITY_PERMISSIONS_POLICY"),
    )
    security_referrer_policy: str = Field(
        default="strict-origin-when-cross-origin",
        validation_alias=AliasChoices("SECURITY_REFERRER_POLICY"),
    )
    security_hsts_seconds: int = Field(
        default=31536000,
        validation_alias=AliasChoices("SECURITY_HSTS_SECONDS"),
    )
    security_enable_headers: bool = Field(
        default=True,
        validation_alias=AliasChoices("SECURITY_ENABLE_HEADERS"),
    )

    @field_validator("moodle_rest_endpoint")
    @classmethod
    def normalize_rest_endpoint(cls, value: str) -> str:
        if value.startswith("http://") or value.startswith("https://"):
            return value
        if not value.startswith("/"):
            return f"/{value}"
        return value

    @field_validator("moodle_ws_format", mode="before")
    @classmethod
    def normalize_moodle_ws_format(cls, value: Any) -> str:
        raw = str(value or "json").strip().lower()
        if not raw:
            return "json"
        return raw

    @field_validator("moodle_default_course_ids", mode="before")
    @classmethod
    def parse_course_ids(cls, value: Any) -> list[int]:
        if value is None:
            return []
        if isinstance(value, list):
            return [int(item) for item in value if str(item).strip()]
        if isinstance(value, str):
            if not value.strip():
                return []
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        raise TypeError("moodle_default_course_ids must be list or comma-separated string")

    @field_validator("moodle_custom_metrics_functions", mode="before")
    @classmethod
    def parse_custom_metrics(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            if not value.strip():
                return []
            return [item.strip() for item in value.split(",") if item.strip()]
        raise TypeError(
            "moodle_custom_metrics_functions must be list or comma-separated string",
        )

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_allowed_origins(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            if not value.strip():
                return []
            return [item.strip() for item in value.split(",") if item.strip()]
        raise TypeError("cors_allowed_origins must be list or comma-separated string")

    @model_validator(mode="after")
    def normalize_limits(self) -> "Settings":
        self.sync_batch_size = max(1, min(int(self.sync_batch_size), 50))
        self.api_rate_limit_per_minute = max(1, int(self.api_rate_limit_per_minute))
        self.moodle_max_concurrency = max(
            1,
            min(int(self.moodle_max_concurrency or self.sync_batch_size), 50),
        )
        self.moodle_max_retries = max(1, int(self.moodle_max_retries))
        self.auth_access_token_minutes = max(5, int(self.auth_access_token_minutes))
        if not self.auth_jwt_secret_key:
            self.auth_jwt_secret_key = self.middleware_api_key or "change-this-secret"
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


