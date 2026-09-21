from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ED_", extra="ignore")

    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://ed_app:ed_app_local_demo@127.0.0.1:5546/evidencedesk"
    )
    migration_database_url: SecretStr | None = None
    storage_root: Path = Path("runtime/private")
    deletion_ledger_root: Path = Path("runtime/deletions")
    allowed_origins: str = "http://localhost:3106,http://127.0.0.1:3106"
    cookie_secure: bool = False
    session_hours: int = Field(default=8, ge=1, le=24)
    login_global_per_minute: int = Field(default=120, ge=1, le=10000)
    login_max_email_keys: int = Field(default=10000, ge=10, le=100000)
    login_cleanup_batch: int = Field(default=100, ge=1, le=1000)
    login_password_concurrency: int = Field(default=2, ge=1, le=16)
    pool_size: int = Field(default=4, ge=1, le=12)
    metrics_token: SecretStr = SecretStr("ed_metrics_local_demo")
    ai_provider: str = "azure_openai"
    azure_openai_base_url: str = Field(
        default="https://agentes-sol-foundry.openai.azure.com/openai/v1/",
        validation_alias="AZURE_OPENAI_BASE_URL",
    )
    azure_openai_deployment: str = Field(
        default="gpt-5.6-luna", validation_alias="AZURE_OPENAI_DEPLOYMENT"
    )
    azure_openai_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="AZURE_OPENAI_API_KEY"
    )
    max_file_bytes: int = 10 * 1024 * 1024
    max_batch_bytes: int = 40 * 1024 * 1024
    max_tenant_storage_bytes: int = 512 * 1024 * 1024
    max_queued_jobs: int = 30
    max_active_jobs_per_tenant: int = 2
    job_lease_seconds: int = 90
    worker_poll_seconds: float = 1.0
    ai_max_input_tokens: int = 10000
    ai_max_output_tokens: int = 2400
    ai_period_token_budget: int = Field(default=100000, ge=1, le=1_000_000_000)
    ai_budget_period: Literal["calendar_month_utc"] = "calendar_month_utc"
    cursor_secret: SecretStr = SecretStr("local-only-change-before-non-loopback")
    retrieval_mode: Literal["lexical", "hybrid", "hybrid_reranked"] = "lexical"
    model_service_token: SecretStr = SecretStr("")

    @property
    def origins(self) -> set[str]:
        return {origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()}

    @property
    def generation_enabled(self) -> bool:
        return self.ai_provider == "azure_openai" and bool(
            self.azure_openai_api_key.get_secret_value()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
