from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from evidencedesk.config import get_settings
from evidencedesk.database import get_engine, transaction
from evidencedesk.errors import Problem
from evidencedesk.identity import admission, service

pytestmark = pytest.mark.integration
ORIGIN = "http://localhost:3106"


def own_keys(workspace, count):
    return [
        service.session_digest(f"{workspace['tenants'][0]}-{index}@fixture.invalid")
        for index in range(count)
    ]


def remove_keys(workspace, keys):
    with workspace["admin"].begin() as connection:
        connection.execute(
            text("DELETE FROM login_limits WHERE key_hash=ANY(:keys)"), {"keys": keys}
        )


def test_global_admission_is_atomic_saturated_and_precedes_new_email_rows(workspace, monkeypatch):
    monkeypatch.setenv("ED_LOGIN_GLOBAL_PER_MINUTE", "3")
    get_settings.cache_clear()
    keys = own_keys(workspace, 8)

    def attempt(key):
        try:
            admission.reserve_password_attempt(key)
            return "accepted"
        except Problem as error:
            return error.code

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(attempt, keys))
        assert outcomes.count("accepted") == 3
        assert outcomes.count("login_global_limited") == 5
        with transaction() as connection:
            assert (
                connection.execute(
                    text("SELECT failures FROM login_limits WHERE key_hash=:key"),
                    {"key": admission.GLOBAL_LOGIN_KEY},
                ).scalar_one()
                == 3
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM login_limits WHERE key_hash=ANY(:keys)"),
                    {"keys": keys},
                ).scalar_one()
                == 3
            )
        with workspace["admin"].begin() as connection:
            connection.execute(
                text(
                    "UPDATE login_limits SET window_start=now()-interval '61 seconds' WHERE key_hash=:key"
                ),
                {"key": admission.GLOBAL_LOGIN_KEY},
            )
        rejected = keys[outcomes.index("login_global_limited")]
        admission.reserve_password_attempt(rejected)
        with transaction() as connection:
            assert (
                connection.execute(
                    text("SELECT failures FROM login_limits WHERE key_hash=:key"),
                    {"key": admission.GLOBAL_LOGIN_KEY},
                ).scalar_one()
                == 1
            )
    finally:
        remove_keys(workspace, keys)


def test_cardinality_cap_and_bounded_expiration_preserve_existing_email_window(
    workspace, monkeypatch
):
    keys = own_keys(workspace, 11)
    with transaction() as connection:
        existing = connection.execute(
            text(f"SELECT count(*) FROM login_limits WHERE {admission.EMAIL_KEY_SQL}")
        ).scalar_one()
    monkeypatch.setenv("ED_LOGIN_MAX_EMAIL_KEYS", str(existing + 10))
    monkeypatch.setenv("ED_LOGIN_CLEANUP_BATCH", "2")
    get_settings.cache_clear()
    try:
        for key in keys[:10]:
            admission.reserve_password_attempt(key)
        with pytest.raises(Problem) as rejected:
            admission.reserve_password_attempt(keys[10])
        assert rejected.value.code == "login_capacity"
        # Known buckets still use their original 10/15min policy at the global cap.
        for _ in range(9):
            admission.reserve_password_attempt(keys[0])
        with pytest.raises(Problem) as rejected:
            admission.reserve_password_attempt(keys[0])
        assert rejected.value.code == "login_limited"
        with workspace["admin"].begin() as connection:
            connection.execute(
                text(
                    "UPDATE login_limits SET window_start=now()-interval '16 minutes' WHERE key_hash=ANY(:keys)"
                ),
                {"keys": keys[1:6]},
            )
        admission.reserve_password_attempt(keys[10])
        with transaction() as connection:
            remaining = connection.execute(
                text("SELECT count(*) FROM login_limits WHERE key_hash=ANY(:keys)"),
                {"keys": keys[1:6]},
            ).scalar_one()
            assert remaining == 3
            assert (
                connection.execute(
                    text("SELECT failures FROM login_limits WHERE key_hash=:key"),
                    {"key": admission.GLOBAL_LOGIN_KEY},
                ).scalar_one()
                == 21
            )
    finally:
        remove_keys(workspace, keys)


def test_argon2_capacity_fails_fast_without_holding_database_connections(workspace, monkeypatch):
    entered, release = Event(), Event()
    guard = Lock()
    running = 0

    def verify(_hash, _password):
        nonlocal running
        with guard:
            running += 1
            if running == 2:
                entered.set()
        assert release.wait(5)
        return False

    monkeypatch.setattr(service, "PASSWORDS", SimpleNamespace(verify=verify))
    email = workspace["tenants"][0] + "-author@fixture.invalid"

    def attempt():
        client = TestClient(workspace["app"], base_url=ORIGIN)
        try:
            return client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "incorrect"},
                headers={"Origin": ORIGIN},
            )
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(attempt) for _ in range(2)]
        try:
            assert entered.wait(5)
            assert get_engine().pool.checkedout() == 0
            busy = attempt()
            assert busy.status_code == 503
            assert busy.json()["error"]["code"] == "login_capacity"
            assert busy.json()["error"]["retryable"] is True
        finally:
            release.set()
        assert [future.result().status_code for future in pending] == [401, 401]
    monkeypatch.setattr(service, "PASSWORDS", SimpleNamespace(verify=lambda *_: False))
    assert attempt().status_code == 401  # all permits were released


def test_blocked_email_retries_leave_global_capacity_for_another_tenant(workspace, monkeypatch):
    monkeypatch.setenv("ED_LOGIN_GLOBAL_PER_MINUTE", "120")
    get_settings.cache_clear()
    email = workspace["tenants"][0] + "-unknown@fixture.invalid"
    key = service.session_digest(email)
    password_checks = 0
    original_verify = service.PASSWORDS.verify

    def verify(password_hash, password):
        nonlocal password_checks
        password_checks += 1
        return original_verify(password_hash, password)

    monkeypatch.setattr(service, "PASSWORDS", SimpleNamespace(verify=verify))
    client = TestClient(workspace["app"], base_url=ORIGIN)
    try:
        for _ in range(10):
            response = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "incorrect"},
                headers={"Origin": ORIGIN},
            )
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "invalid_credentials"
        for _ in range(129):
            response = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "incorrect"},
                headers={"Origin": ORIGIN},
            )
            assert response.status_code == 429
            assert response.json()["error"]["code"] == "login_limited"
        assert password_checks == 10
        with transaction() as connection:
            counts = dict(
                connection.execute(
                    text("SELECT key_hash,failures FROM login_limits WHERE key_hash=ANY(:keys)"),
                    {"keys": [key, admission.GLOBAL_LOGIN_KEY]},
                ).all()
            )
            assert counts == {key: 10, admission.GLOBAL_LOGIN_KEY: 10}

        other = workspace["client"](tenant_index=1)
        session = other.get("/api/v1/auth/session")
        assert session.status_code == 200
        assert session.json()["tenant"]["id"] == workspace["tenants"][1]
        assert password_checks == 11
        with transaction() as connection:
            assert (
                connection.execute(
                    text("SELECT failures FROM login_limits WHERE key_hash=:key"),
                    {"key": admission.GLOBAL_LOGIN_KEY},
                ).scalar_one()
                == 11
            )
    finally:
        client.close()
        remove_keys(workspace, [key])


def test_concurrent_email_rejections_reserve_only_one_remaining_global_attempt(workspace):
    key = own_keys(workspace, 1)[0]

    def attempt(_):
        try:
            admission.reserve_password_attempt(key)
            return "accepted"
        except Problem as error:
            return error.code

    try:
        for _ in range(9):
            admission.reserve_password_attempt(key)
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(attempt, range(8)))
        assert outcomes.count("accepted") == 1
        assert outcomes.count("login_limited") == 7
        with transaction() as connection:
            counts = dict(
                connection.execute(
                    text("SELECT key_hash,failures FROM login_limits WHERE key_hash=ANY(:keys)"),
                    {"keys": [key, admission.GLOBAL_LOGIN_KEY]},
                ).all()
            )
            assert counts == {key: 10, admission.GLOBAL_LOGIN_KEY: 10}
    finally:
        remove_keys(workspace, [key])
