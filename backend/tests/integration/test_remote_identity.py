import pytest
from conftest import PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import text

from evidencedesk.config import get_settings
from evidencedesk.identity.service import session_digest

pytestmark = pytest.mark.integration
REMOTE_ORIGIN = "https://desk.example"


def enable_remote_configuration(monkeypatch):
    monkeypatch.setenv("ED_ALLOWED_ORIGINS", REMOTE_ORIGIN)
    monkeypatch.setenv("ED_COOKIE_SECURE", "true")
    monkeypatch.setenv("ED_METRICS_TOKEN", "test-only-" * 4)
    monkeypatch.setenv("ED_CURSOR_SECRET", "test-only-" * 4)
    get_settings.cache_clear()


@pytest.mark.parametrize("domain", ["aurora.demo", "Aurora.DEMO"])
def test_switch_to_remote_rejects_existing_demo_identity_and_session(
    workspace, monkeypatch, domain
):
    client = workspace["client"]()
    user = workspace["tenants"][0] + "-author"
    email = user + "@" + domain
    with workspace["admin"].begin() as connection:
        connection.execute(
            text("UPDATE users SET email=:email WHERE id=:id"), {"email": email, "id": user}
        )
    # The same already-created account and session work in the local demo.
    assert client.get("/api/v1/auth/session").status_code == 200
    token = client.cookies.get("ed_session")
    enable_remote_configuration(monkeypatch)
    try:
        with TestClient(workspace["app"], base_url=REMOTE_ORIGIN) as remote:
            remote.headers["Origin"] = REMOTE_ORIGIN
            remote.cookies.set("ed_session", token)
            existing = remote.get("/api/v1/auth/session")
            assert existing.status_code == 401
            assert existing.json()["error"]["code"] == "session_expired"
            rejected = remote.post(
                "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
            )
            assert rejected.status_code == 401
            assert rejected.json()["error"]["code"] == "invalid_credentials"
        with workspace["admin"].connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM sessions WHERE user_id=:user"), {"user": user}
                ).scalar_one()
                == 1
            )
    finally:
        with workspace["admin"].begin() as connection:
            connection.execute(
                text("DELETE FROM login_limits WHERE key_hash=:key"),
                {"key": session_digest(email.casefold())},
            )


def test_remote_origin_accepts_non_demo_identity_and_secure_session(workspace, monkeypatch):
    workspace["client"]()
    email = workspace["tenants"][0] + "-author@fixture.invalid"
    enable_remote_configuration(monkeypatch)
    with TestClient(workspace["app"], base_url=REMOTE_ORIGIN) as remote:
        remote.headers["Origin"] = REMOTE_ORIGIN
        accepted = remote.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert accepted.status_code == 200
        assert "Secure" in accepted.headers["Set-Cookie"]
        assert remote.get("/api/v1/auth/session").status_code == 200
