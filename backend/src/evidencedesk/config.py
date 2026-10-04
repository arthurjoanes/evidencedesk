import re
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

AZURE_HOST_PATTERN = (
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.(?:openai\.azure\.com|services\.ai\.azure\.com)"
)
AZURE_URL = re.compile(
    rf"https://(?P<host>{AZURE_HOST_PATTERN})(?::443)?/openai/v1/?", re.IGNORECASE | re.ASCII
)


def normalize_azure_base_url(value: str) -> str:
    """Accept only the public Azure resource inference route, never arbitrary URLs."""
    match = AZURE_URL.fullmatch(value)
    if match is None:
        raise ValueError("Use um endpoint HTTPS de recurso Azure com o caminho /openai/v1/.")
    return f"https://{match['host'].lower()}/openai/v1/"


def authorize_azure_base_url(value: str, allowed_hosts: str) -> str:
    normalized = normalize_azure_base_url(value)
    hosts = {host.strip().lower() for host in allowed_hosts.split(",")}
    if not hosts or any(
        re.fullmatch(AZURE_HOST_PATTERN, host, flags=re.ASCII) is None for host in hosts
    ):
        raise ValueError("Configure uma allowlist explícita de hosts de recurso Azure.")
    if normalized.split("/")[2] not in hosts:
        raise ValueError("Endpoint Azure fora da allowlist de runtime.")
    return normalized


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ED_", extra="ignore", hide_input_in_errors=True)

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
        default="",
        validation_alias="AZURE_OPENAI_BASE_URL",
    )
    azure_openai_deployment: str = Field(default="", validation_alias="AZURE_OPENAI_DEPLOYMENT")
    azure_openai_allowed_hosts: str = ""
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

    @model_validator(mode="after")
    def secure_remote_runtime(self) -> "Settings":
        if not self.origins:
            raise ValueError("Configure ao menos uma origem explícita.")
        remote = False
        for origin in self.origins:
            parsed = urlsplit(origin)
            # An Origin contains only scheme, host and optional port.
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Configure origens HTTP ou HTTPS sem caminho ou credenciais.")
            _ = parsed.port  # Reject malformed ports before any service starts.
            if not self.loopback_host(parsed.hostname):
                remote = True
                if parsed.scheme != "https":
                    raise ValueError("Origens fora de loopback exigem HTTPS.")
            if parsed.scheme == "https" and not self.cookie_secure:
                raise ValueError("Origens HTTPS exigem ED_COOKIE_SECURE=true.")
        if remote:
            for value, default in (
                (self.metrics_token.get_secret_value(), "ed_metrics_local_demo"),
                (self.cursor_secret.get_secret_value(), "local-only-change-before-non-loopback"),
            ):
                if value == default or len(value.strip()) < 32:
                    raise ValueError(
                        "Fora de loopback, configure segredos próprios de 32 caracteres ou mais."
                    )
            if make_url(self.database_url.get_secret_value()).password == "ed_app_local_demo":
                raise ValueError("Fora de loopback, substitua a senha de demonstração do banco.")
        return self

    @staticmethod
    def loopback_host(host: str) -> bool:
        if host == "localhost":
            return True
        try:
            return ip_address(host).is_loopback
        except ValueError:
            return False

    @property
    def local_origins_only(self) -> bool:
        return all(self.loopback_host(urlsplit(origin).hostname or "") for origin in self.origins)

    @property
    def origins(self) -> set[str]:
        return {origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()}

    @property
    def generation_enabled(self) -> bool:
        if (
            self.ai_provider != "azure_openai"
            or not self.azure_openai_api_key.get_secret_value().strip()
            or re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", self.azure_openai_deployment) is None
        ):
            return False
        try:
            authorize_azure_base_url(self.azure_openai_base_url, self.azure_openai_allowed_hosts)
        except ValueError:
            return False
        return True


@lru_cache
def get_settings() -> Settings:
    return Settings()
