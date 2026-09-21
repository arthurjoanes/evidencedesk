import asyncio

import pytest

from evidencedesk.body_limit import JsonBodyLimit


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers", [[], [(b"content-type", b"application/json")], [(b"content-length", b"1")]]
)
async def test_untrusted_header_cannot_bypass_actual_stream_limit(headers):
    called = False
    output = []
    chunks = iter(
        [
            {"type": "http.request", "body": b"x" * 8, "more_body": True},
            {"type": "http.request", "body": b"y" * 8, "more_body": False},
        ]
    )

    async def app(scope, receive, send):
        nonlocal called
        called = True

    async def receive():
        return next(chunks)

    async def send(message):
        output.append(message)

    middleware = JsonBodyLimit(app, maximum_bytes=10)
    await middleware(
        {"type": "http", "method": "POST", "path": "/api/v1/imports", "headers": headers},
        receive,
        send,
    )
    assert not called
    assert output[0]["status"] == 413


@pytest.mark.asyncio
async def test_slow_body_is_terminated_before_handler():
    output = []

    async def app(scope, receive, send):
        pytest.fail("Timed out body reached handler")

    async def receive():
        await asyncio.sleep(1)

    async def send(message):
        output.append(message)

    await JsonBodyLimit(app, timeout_seconds=0.01)(
        {"type": "http", "method": "POST", "path": "/api/v1/imports", "headers": []}, receive, send
    )
    assert output[0]["status"] == 408


@pytest.mark.asyncio
async def test_split_body_is_delivered_once_without_changing_bytes():
    received = []
    chunks = iter(
        [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
            {"type": "http.disconnect"},
        ]
    )

    async def app(scope, receive, send):
        received.append(await receive())
        received.append(await receive())

    async def receive():
        return next(chunks)

    async def send(message):
        pass

    await JsonBodyLimit(app)(
        {"type": "http", "method": "POST", "path": "/api/v1/imports", "headers": []}, receive, send
    )
    assert received == [
        {"type": "http.request", "body": b"abcdef", "more_body": False},
        {"type": "http.disconnect"},
    ]
