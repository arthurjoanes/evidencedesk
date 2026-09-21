"""Bound JSON before FastAPI deserializes it; file uploads have their own manifest limit."""

import asyncio
import re
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class JsonBodyLimit:
    def __init__(self, app: ASGIApp, maximum_bytes: int = 512 * 1024, timeout_seconds: float = 15):
        self.app = app
        self.maximum_bytes = maximum_bytes
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        file_upload = scope["method"] == "PUT" and re.fullmatch(
            r"/api/v1/imports/[^/]+/files/[^/]+", scope["path"]
        )
        if scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"} or file_upload:
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex

        async def reject(status: int, code: str, message: str) -> None:
            response = JSONResponse(
                {
                    "error": {
                        "code": code,
                        "message": message,
                        "request_id": request_id,
                        "retryable": False,
                    }
                },
                status_code=status,
                headers={"Cache-Control": "no-store", "X-Request-ID": request_id},
            )
            await response(scope, receive, send)

        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            await reject(400, "invalid_content_length", "Tamanho do corpo inválido.")
            return
        if declared < 0 or declared > self.maximum_bytes:
            await reject(413, "request_too_large", "O pedido excede o limite de 512 KiB.")
            return
        body = bytearray()
        try:
            async with asyncio.timeout(self.timeout_seconds):
                while True:
                    event = await receive()
                    if event["type"] == "http.disconnect":
                        return
                    chunk = event.get("body", b"")
                    if len(body) + len(chunk) > self.maximum_bytes:
                        await reject(
                            413, "request_too_large", "O pedido excede o limite de 512 KiB."
                        )
                        return
                    body.extend(chunk)
                    if not event.get("more_body", False):
                        break
        except TimeoutError:
            await reject(408, "request_body_timeout", "O envio do pedido excedeu o prazo.")
            return
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
