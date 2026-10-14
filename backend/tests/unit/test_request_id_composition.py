import asyncio

import httpx
import pytest

import evidencedesk.app as application
from evidencedesk.body_limit import JsonBodyLimit


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["declared", "actual", "invalid", "timeout"])
async def test_early_body_rejection_keeps_one_id_in_body_header_and_log(monkeypatch, scenario):
    events = []
    monkeypatch.setattr(
        application, "log_event", lambda event, **fields: events.append((event, fields))
    )
    original = JsonBodyLimit.__init__
    monkeypatch.setattr(
        JsonBodyLimit,
        "__init__",
        lambda self, app: original(self, app, maximum_bytes=10, timeout_seconds=0.01),
    )
    headers = {"Content-Type": "application/json"}
    if scenario == "declared":
        headers["Content-Length"] = "11"
    elif scenario == "invalid":
        headers["Content-Length"] = "not-an-integer"

    async def content():
        if scenario == "timeout":
            await asyncio.sleep(1)
        yield b"x" * 11

    app = application.create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/auth/login", content=content(), headers=headers)
    assert (
        response.status_code
        == {"declared": 413, "actual": 413, "invalid": 400, "timeout": 408}[scenario]
    )
    identity = response.json()["error"]["request_id"]
    assert len(identity) == 32
    assert response.headers["X-Request-ID"] == identity
    assert events[-1][1]["request_id"] == identity
