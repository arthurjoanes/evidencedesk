"""Private inference process. Only preauthorized text crosses this narrow boundary."""

from __future__ import annotations

import hmac
import os
import threading
import time
from collections.abc import Sequence
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from .http_contracts import EmbeddingRequest, EmbeddingResponse, RerankRequest, RerankResponse
from .local_models import (
    EMBEDDING_REVISION,
    RERANKER_REVISION,
    E5Encoder,
    LocalReranker,
    ModelTokenLimitError,
)


class Encoder(Protocol):
    def encode_query(self, query: str) -> list[float]: ...
    def encode_passages(self, passages: Sequence[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    def score_passages(self, query: str, passages: Sequence[str]) -> list[float]: ...


def error(code: str, status: int, *, retryable: bool = False) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "retryable": retryable}}, status_code=status)


class PrivateBoundary:
    """Authenticate before parsing input; bound streamed bodies as well as Content-Length."""

    def __init__(self, app: ASGIApp, *, token: str) -> None:
        self.app = app
        self.authorization = ("Bearer " + token).encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/healthz":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        if not hmac.compare_digest(headers.get(b"authorization", b""), self.authorization):
            await error("model_service_unauthorized", 401)(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 128_000:
                await error("model_input_too_large", 413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        async def bounded_receive():
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, bounded_receive, send)


def create_app(
    *,
    token: str,
    device: str = "cpu",
    encoder: Encoder | None = None,
    reranker: Reranker | None = None,
) -> FastAPI:
    if len(token) < 24 or device not in {"cpu", "cuda"}:
        raise ValueError("Configuração do serviço ML inválida.")
    if (encoder is None) != (reranker is None):
        raise ValueError("Injete ambos os modelos ou use o carregamento local.")
    gate = threading.BoundedSemaphore(1)
    registry = CollectorRegistry()
    requests = Counter(
        "ed_local_model_requests_total",
        "Bounded local inference outcomes",
        ["operation", "outcome"],
        registry=registry,
    )
    latency = Histogram(
        "ed_local_model_duration_seconds",
        "Inference latency including validation",
        ["operation"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15),
        registry=registry,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        def load():
            return (encoder or E5Encoder(device=device), reranker or LocalReranker(device=device))

        app.state.encoder, app.state.reranker = await run_in_threadpool(load)
        app.state.ready = True
        yield
        app.state.ready = False

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ready = False
    app.add_middleware(PrivateBoundary, token=token)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exception: RequestValidationError):
        return error("model_input_invalid", 422)

    @app.get("/healthz")
    async def health():
        if not app.state.ready:
            return error("model_service_not_ready", 503, retryable=True)
        return {
            "status": "ready",
            "embedding_revision": EMBEDDING_REVISION,
            "reranker_revision": RERANKER_REVISION,
            "device": device,
            "concurrency": 1,
        }

    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(registry), media_type="text/plain; version=0.0.4")

    async def execute(operation: str, function):
        if not gate.acquire(blocking=False):
            requests.labels(operation, "busy").inc()
            return error("model_service_busy", 503, retryable=True)

        def bounded_inference():
            started = time.monotonic()
            try:
                result = function()
                requests.labels(operation, "completed").inc()
                return result
            except ModelTokenLimitError as failure:
                requests.labels(operation, "token_limit").inc()
                return error(failure.code, 422)
            except ValueError:
                requests.labels(operation, "invalid_input").inc()
                return error("model_input_invalid", 422)
            except Exception:
                # No input, model exception text or tensor content is logged or returned.
                requests.labels(operation, "failed").inc()
                return error("model_inference_failed", 503, retryable=True)
            finally:
                latency.labels(operation).observe(time.monotonic() - started)
                gate.release()

        return await run_in_threadpool(bounded_inference)

    @app.post("/v1/embeddings")
    async def embeddings(payload: EmbeddingRequest):
        if payload.revision != EMBEDDING_REVISION:
            return error("model_revision_mismatch", 409)
        if payload.task == "query" and len(payload.texts) != 1:
            return error("model_input_invalid", 422)

        def compute():
            vectors = (
                [app.state.encoder.encode_query(payload.texts[0])]
                if payload.task == "query"
                else app.state.encoder.encode_passages(payload.texts)
            )
            return EmbeddingResponse(revision=EMBEDDING_REVISION, vectors=vectors)

        return await execute("embeddings", compute)

    @app.post("/v1/rerank")
    async def rerank(payload: RerankRequest):
        if payload.revision != RERANKER_REVISION:
            return error("model_revision_mismatch", 409)

        def compute():
            return RerankResponse(
                revision=RERANKER_REVISION,
                scores=app.state.reranker.score_passages(payload.query, payload.passages),
            )

        return await execute("rerank", compute)

    return app


def application() -> FastAPI:
    """Uvicorn factory; no Azure, database credentials or implicit remote downloads."""
    return create_app(
        token=os.environ.get("ED_MODEL_SERVICE_TOKEN", ""),
        device=os.environ.get("ED_MODEL_DEVICE", "cpu"),
    )
