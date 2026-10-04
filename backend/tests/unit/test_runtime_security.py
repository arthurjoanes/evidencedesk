import pytest
from pydantic import SecretStr, ValidationError

from evidencedesk import seed
from evidencedesk.app import create_app
from evidencedesk.config import Settings, get_settings


def remote_settings(**changes):
    return Settings(
        **(
            {
                "allowed_origins": "https://desk.example",
                "cookie_secure": True,
                "metrics_token": SecretStr("fixture-metrics-secret-with-32-characters"),
                "cursor_secret": SecretStr("fixture-cursor-secret-with-32-characters"),
                "database_url": SecretStr("postgresql+psycopg://ed_app:fixture-password@db/desk"),
            }
            | changes
        )
    )


def test_loopback_demo_remains_available():
    settings = Settings()
    assert settings.local_origins_only
    assert not settings.cookie_secure


def test_https_runtime_accepts_explicit_secrets_and_secure_cookies():
    assert not remote_settings().local_origins_only


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed_origins": "http://desk.example"},
        {"cookie_secure": False},
        {"metrics_token": SecretStr("ed_metrics_local_demo")},
        {"cursor_secret": SecretStr("local-only-change-before-non-loopback")},
        {"metrics_token": SecretStr("short")},
        {"cursor_secret": SecretStr("short")},
        {"database_url": SecretStr("postgresql+psycopg://ed_app:ed_app_local_demo@db/desk")},
    ],
)
def test_remote_runtime_rejects_insecure_demo_configuration(changes):
    with pytest.raises(ValidationError):
        remote_settings(**changes)


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "*",
        "https://user:secret@desk.example",
        "https://desk.example/path",
        "https://desk.example?key=secret",
        "https://desk.example#fragment",
        "https://desk.example:bad",
        "https://localhost.evil.example",
    ],
)
def test_unusable_origins_are_rejected(origin):
    with pytest.raises(ValidationError):
        Settings(allowed_origins=origin)


def test_https_loopback_also_requires_secure_cookie():
    with pytest.raises(ValidationError):
        Settings(allowed_origins="https://localhost:3106", cookie_secure=False)


def test_public_demo_accounts_are_rejected_before_database_access(monkeypatch):
    monkeypatch.setattr(seed, "get_settings", remote_settings)
    with pytest.raises(RuntimeError, match="loopback"):
        seed.seed_identity()


def test_configuration_errors_do_not_echo_secrets():
    secret = "fixture-secret-not-for-error-output"
    with pytest.raises(ValidationError) as error:
        remote_settings(cookie_secure=False, metrics_token=secret)
    assert secret not in str(error.value)


def test_api_rejects_unsafe_origins_before_accepting_requests(monkeypatch):
    monkeypatch.setenv("ED_ALLOWED_ORIGINS", "http://desk.example")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        create_app()
