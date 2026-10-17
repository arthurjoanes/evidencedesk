from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from evidencedesk.app import create_app
from evidencedesk.config import get_settings
from evidencedesk.errors import Problem
from evidencedesk.identity import service


@pytest.mark.parametrize(
    "token,accepted",
    [(b"\xff", False), (b"incorrect", False), (b"", False), (b"expected-token", True)],
)
def test_csrf_header_validation(monkeypatch, token, accepted):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "headers": [
                (b"origin", next(iter(get_settings().origins)).encode()),
                (b"cookie", b"ed_session=synthetic-session"),
                (b"x-csrf-token", token),
            ],
        }
    )
    connection = Mock()
    connection.execute.return_value.mappings.return_value.first.return_value = {
        "id": "user",
        "tenant_id": "tenant",
        "name": "User",
        "tenant_name": "Tenant",
        "role": "reviewer",
        "csrf_token": "expected-token",
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
    }

    @contextmanager
    def transaction():
        yield connection

    monkeypatch.setattr(service, "transaction", transaction)

    if accepted:
        assert service.authenticate(request).id == "user"
    else:
        with pytest.raises(Problem) as failure:
            service.authenticate(request)
        assert failure.value.status == 403
        assert failure.value.code == "invalid_csrf"


@pytest.mark.parametrize("authorization", [b"Bearer \xff", b"Bearer incorrect", b""])
def test_malformed_metrics_authorization_is_forbidden(authorization):
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.get("/metrics", headers=[(b"authorization", authorization)])

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "metrics_access_denied"
