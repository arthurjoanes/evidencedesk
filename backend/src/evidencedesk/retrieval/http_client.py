"""Synchronous model client for indexing/jobs; it never loads Torch or reads secrets."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from urllib.parse import urlsplit

import httpx
from opentelemetry import trace
from pydantic import ValidationError

from .http_contracts import (
    EmbeddingRequest,
    EmbeddingResponse,
    ModelServiceError,
    RerankRequest,
    RerankResponse,
)
from .local_models import EMBEDDING_REVISION, RERANKER_REVISION

MODEL_SERVICE_URL = "http://models:8090"
TIMEOUT = httpx.Timeout(connect=2, read=15, write=2, pool=1)
tracer = trace.get_tracer(__name__)


class RemoteModels:
    batch_size = 8
    dimensions = 384

    def __init__(self, client: httpx.Client, *, token: str) -> None:
        endpoint = urlsplit(str(client.base_url))
        if (
            endpoint.scheme != "http"
            or endpoint.hostname != "models"
            or endpoint.port != 8090
            or endpoint.path not in {"", "/"}
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError("Cliente ML requer o endereço interno fixo http://models:8090.")
        if len(token) < 24:
            raise ValueError("Token interno ML deve ter ao menos 24 caracteres.")
        self._client = client
        self._token = token

    def _post(self, operation: str, payload: dict) -> bytes:
        with tracer.start_as_current_span(
            "retrieval.model." + operation, record_exception=False, set_status_on_exception=False
        ) as span:
            span.set_attribute("model.revision", payload["revision"])
            try:
                with self._client.stream(
                    "POST",
                    "/v1/" + operation,
                    json=payload,
                    timeout=TIMEOUT,
                    headers={"Authorization": "Bearer " + self._token},
                    follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        if response.status_code == 422:
                            rejected = bytearray()
                            for block in response.iter_bytes():
                                rejected.extend(block)
                                if len(rejected) > 2048:
                                    raise ModelServiceError("model_service_invalid_response")
                            try:
                                detail = json.loads(rejected)
                                reason = detail["error"]["code"]
                            except (ValueError, KeyError, TypeError):
                                reason = None
                            if isinstance(reason, str) and reason in {
                                "model_query_too_long",
                                "evidence_requires_rechunking",
                            }:
                                raise ModelServiceError(reason)
                        code = (
                            "model_service_busy"
                            if response.status_code == 503
                            else "model_service_rejected"
                        )
                        raise ModelServiceError(code, retryable=response.status_code == 503)
                    body = bytearray()
                    for block in response.iter_bytes():
                        body.extend(block)
                        if len(body) > 256_000:
                            raise ModelServiceError("model_service_invalid_response")
                    span.set_attribute("model.outcome", "completed")
                    return bytes(body)
            except httpx.TimeoutException:
                span.set_attribute("model.outcome", "timeout")
                raise ModelServiceError("model_service_timeout", retryable=True) from None
            except httpx.RequestError:
                span.set_attribute("model.outcome", "unavailable")
                raise ModelServiceError("model_service_unavailable", retryable=True) from None
            except ModelServiceError as error:
                span.set_attribute("model.outcome", error.code)
                raise

    def _embeddings(self, texts: Sequence[str], task: str) -> list[list[float]]:
        payload = EmbeddingRequest.model_validate(
            {"revision": EMBEDDING_REVISION, "task": task, "texts": list(texts)}
        )
        try:
            response = EmbeddingResponse.model_validate_json(
                self._post("embeddings", payload.model_dump())
            )
        except ValidationError:
            raise ModelServiceError("model_service_invalid_response") from None
        if response.revision != EMBEDDING_REVISION or len(response.vectors) != len(texts):
            raise ModelServiceError("model_service_revision_mismatch")
        if any(
            abs(math.sqrt(sum(value * value for value in vector)) - 1) > 0.01
            for vector in response.vectors
        ):
            raise ModelServiceError("model_service_invalid_vector")
        return response.vectors

    def encode_passages(self, passages: Sequence[str]) -> list[list[float]]:
        return self._embeddings(passages, "passage") if passages else []

    def encode_query(self, query: str) -> list[float]:
        return self._embeddings([query], "query")[0]

    def score_passages(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        payload = RerankRequest(revision=RERANKER_REVISION, query=query, passages=list(passages))
        try:
            response = RerankResponse.model_validate_json(
                self._post("rerank", payload.model_dump())
            )
        except ValidationError:
            raise ModelServiceError("model_service_invalid_response") from None
        if response.revision != RERANKER_REVISION or len(response.scores) != len(passages):
            raise ModelServiceError("model_service_revision_mismatch")
        return response.scores
