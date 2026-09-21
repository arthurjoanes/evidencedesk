import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from evidencedesk.app import create_app
from evidencedesk.config import get_settings
from evidencedesk.database import get_engine
from evidencedesk.identity import admission
from evidencedesk.identity.service import PASSWORDS, session_digest

ORIGIN = "http://localhost:3106"
PASSWORD = "Fixture-only-password!"


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    app_url = os.environ.get("ED_TEST_DATABASE_URL")
    admin_url = os.environ.get("ED_TEST_ADMIN_DATABASE_URL")
    if not app_url or not admin_url:
        pytest.skip("Configure explicit disposable ED_TEST_DATABASE_URL and admin URL.")
    monkeypatch.setenv("ED_DATABASE_URL", app_url)
    monkeypatch.setenv("ED_STORAGE_ROOT", str(tmp_path / "private"))
    monkeypatch.setenv("ED_DELETION_LEDGER_ROOT", str(tmp_path / "ledger"))
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
    get_engine.cache_clear()
    get_settings.cache_clear()
    admin = create_engine(admin_url, pool_size=1, max_overflow=0)
    tag = "api-test-" + uuid4().hex
    monkeypatch.setattr(admission, "GLOBAL_LOGIN_KEY", "global:" + tag)
    tenants = [tag + "-a", tag + "-b"]
    password_hash = PASSWORDS.hash(PASSWORD)
    with admin.begin() as connection:
        for tenant in tenants:
            connection.execute(
                text("INSERT INTO tenants(id,name) VALUES(:id,'API test')"), {"id": tenant}
            )
            connection.execute(
                text("INSERT INTO tenant_policy(tenant_id) VALUES(:tenant)"), {"tenant": tenant}
            )
            connection.execute(
                text(
                    "INSERT INTO collections(tenant_id,id,name) VALUES(:tenant,'collection','Test collection')"
                ),
                {"tenant": tenant},
            )
            for suffix in ("author", "reviewer", "admin"):
                user = tenant + "-" + suffix
                connection.execute(
                    text(
                        "INSERT INTO users(id,tenant_id,email,name,password_hash,role) VALUES(:id,:tenant,:email,:name,:hash,:role)"
                    ),
                    {
                        "id": user,
                        "tenant": tenant,
                        "email": user + "@fixture.invalid",
                        "name": suffix,
                        "hash": password_hash,
                        "role": "tenant_admin" if suffix == "admin" else "reviewer",
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO collection_grants(tenant_id,collection_id,user_id) VALUES(:tenant,'collection',:user)"
                    ),
                    {"tenant": tenant, "user": user},
                )
    app = create_app()
    clients = []

    def client(tenant_index=0, role="author"):
        current = TestClient(app, base_url=ORIGIN, raise_server_exceptions=True)
        current.headers["Origin"] = ORIGIN
        response = current.post(
            "/api/v1/auth/login",
            json={
                "email": tenants[tenant_index] + "-" + role + "@fixture.invalid",
                "password": PASSWORD,
            },
        )
        assert response.status_code == 200, response.text
        current.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        clients.append(current)
        return current

    yield {"client": client, "tenants": tenants, "admin": admin, "app": app}
    for current in clients:
        current.close()
    with admin.begin() as connection:
        connection.execute(
            text("DELETE FROM login_limits WHERE key_hash=:key"),
            {"key": admission.GLOBAL_LOGIN_KEY},
        )
        for tenant in tenants:
            connection.execute(
                text("""
                    UPDATE provider_control SET call_id=NULL,lease_until=NULL,open_until=NULL,failures=0
                    WHERE id=1 AND call_id IN(SELECT id FROM provider_calls WHERE tenant_id=:tenant)
                """),
                {"tenant": tenant},
            )
            connection.execute(
                text(
                    "DELETE FROM sessions WHERE user_id IN(SELECT id FROM users WHERE tenant_id=:tenant)"
                ),
                {"tenant": tenant},
            )
            connection.execute(
                text(
                    "DELETE FROM stream_leases WHERE user_id IN(SELECT id FROM users WHERE tenant_id=:tenant)"
                ),
                {"tenant": tenant},
            )
            for role in ("author", "reviewer", "admin"):
                connection.execute(
                    text("DELETE FROM login_limits WHERE key_hash=:key"),
                    {"key": session_digest(tenant + "-" + role + "@fixture.invalid")},
                )
            for table in (
                "storage_cleanup",
                "audit_events",
                "deletion_requests",
                "result_artifacts",
                "run_events",
                "provider_calls",
                "exports",
                "idempotency_keys",
                "revision_decisions",
                "dossier_revisions",
                "dossiers",
                "investigation_runs",
                "jobs",
                "incident_members",
                "incidents",
                "snapshot_members",
                "snapshot_mappings",
                "evidence",
                "evidence_snapshots",
                "import_entries",
                "import_batches",
                "collection_grants",
                "collections",
                "tenant_policy",
                "users",
            ):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id=:tenant"), {"tenant": tenant}
                )
            connection.execute(text("DELETE FROM tenants WHERE id=:tenant"), {"tenant": tenant})
    admin.dispose()
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()
