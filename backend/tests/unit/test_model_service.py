import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from fastapi.testclient import TestClient

from evidencedesk.retrieval.http_client import MODEL_SERVICE_URL, RemoteModels
from evidencedesk.retrieval.http_contracts import ModelServiceError
from evidencedesk.retrieval.local_models import (
    EMBEDDING_REVISION,
    RERANKER_REVISION,
    ModelTokenLimitError,
)
from evidencedesk.retrieval.model_service import create_app

TOKEN = "model-test-only-token-minimum-24"
HEADERS = {"Authorization": "Bearer " + TOKEN}
VECTOR = [1.0] + [0.0] * 383


class Models:
    def encode_query(self, query):
        return VECTOR

    def encode_passages(self, passages):
        return [VECTOR for _ in passages]

    def score_passages(self, query, passages):
        return [0.5 for _ in passages]


@pytest.fixture
def client():
    models = Models()
    with TestClient(create_app(token=TOKEN, encoder=models, reranker=models)) as connection:
        yield connection


def embedding_body(**extra):
    return {"revision": EMBEDDING_REVISION, "task": "query", "texts": ["pagamento"], **extra}


def test_authentication_precedes_body_validation_and_no_content_is_echoed(client):
    response = client.post("/v1/embeddings", content="PRIVATE invalid JSON")
    assert response.status_code == 401
    assert "PRIVATE" not in response.text
    assert client.get("/healthz").json()["status"] == "ready"
    assert client.get("/metrics").status_code == 401


def test_service_rejects_arbitrary_tenant_revision_and_oversized_payload(client):
    assert (
        client.post(
            "/v1/embeddings", headers=HEADERS, json=embedding_body(tenant_id="other")
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/embeddings", headers=HEADERS, json=embedding_body(revision="0" * 40)
        ).status_code
        == 409
    )
    assert client.post("/v1/embeddings", headers=HEADERS, content=b"x" * 128001).status_code == 413
    assert (
        client.post(
            "/v1/embeddings", headers=HEADERS, json=embedding_body(texts=["a", "b"])
        ).status_code
        == 422
    )


def test_service_returns_stable_order_and_metrics_without_text(client):
    result = client.post("/v1/embeddings", headers=HEADERS, json=embedding_body()).json()
    assert result["vectors"] == [VECTOR]
    result = client.post(
        "/v1/rerank",
        headers=HEADERS,
        json={"revision": RERANKER_REVISION, "query": "PRIVATE source", "passages": ["one", "two"]},
    ).json()
    assert result["scores"] == [0.5, 0.5]
    metrics = client.get("/metrics", headers=HEADERS).text
    assert "ed_local_model_requests_total" in metrics
    assert "PRIVATE" not in metrics


def test_busy_model_rejects_concurrent_work_instead_of_queueing():
    entered, release = Event(), Event()

    class SlowModels(Models):
        def encode_query(self, query):
            entered.set()
            assert release.wait(5)
            return VECTOR

    models = SlowModels()
    with TestClient(create_app(token=TOKEN, encoder=models, reranker=models)) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(
                client.post, "/v1/embeddings", headers=HEADERS, json=embedding_body()
            )
            assert entered.wait(5)
            try:
                response = client.post("/v1/embeddings", headers=HEADERS, json=embedding_body())
                assert response.status_code == 503
                assert response.json()["error"]["code"] == "model_service_busy"
            finally:
                release.set()
            assert first.result().status_code == 200


def test_internal_model_failure_does_not_return_source_content():
    class BrokenModels(Models):
        def encode_query(self, query):
            raise RuntimeError("PRIVATE raw source inside exception")

    models = BrokenModels()
    with TestClient(create_app(token=TOKEN, encoder=models, reranker=models)) as client:
        response = client.post("/v1/embeddings", headers=HEADERS, json=embedding_body())
        assert response.status_code == 503
        assert "PRIVATE" not in response.text


def test_remote_models_injects_auth_and_checks_revision_shape_and_normalization():
    def response(request):
        assert request.headers["Authorization"] == HEADERS["Authorization"]
        payload = json.loads(request.content)
        assert payload["revision"] == EMBEDDING_REVISION
        return httpx.Response(
            200, json={"revision": EMBEDDING_REVISION, "dimensions": 384, "vectors": [VECTOR]}
        )

    with httpx.Client(
        base_url=MODEL_SERVICE_URL, transport=httpx.MockTransport(response)
    ) as client:
        assert RemoteModels(client, token=TOKEN).encode_query("private") == VECTOR


@pytest.mark.parametrize(
    "payload",
    [
        {"revision": "0" * 40, "dimensions": 384, "vectors": [VECTOR]},
        {"revision": EMBEDDING_REVISION, "dimensions": 384, "vectors": [[0.0] * 384]},
        {"revision": EMBEDDING_REVISION, "dimensions": 384, "vectors": [[1.0]]},
    ],
)
def test_remote_models_rejects_invalid_vectors_or_revision(payload):
    with httpx.Client(
        base_url=MODEL_SERVICE_URL,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    ) as client:
        with pytest.raises(ModelServiceError):
            RemoteModels(client, token=TOKEN).encode_query("query")


def test_remote_model_timeout_is_retryable_without_provider_exception_text():
    def timeout(request):
        raise httpx.ReadTimeout("PRIVATE source", request=request)

    with httpx.Client(base_url=MODEL_SERVICE_URL, transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(ModelServiceError) as caught:
            RemoteModels(client, token=TOKEN).encode_query("query")
    assert caught.value.retryable
    assert str(caught.value) == "model_service_timeout"


def test_remote_model_cannot_follow_an_arbitrary_endpoint():
    with httpx.Client(base_url="https://external.invalid") as client:
        with pytest.raises(ValueError):
            RemoteModels(client, token=TOKEN)


def test_real_tokenizer_limit_is_a_safe_nonretryable_contract():
    class LongInputModels(Models):
        def encode_passages(self, passages):
            raise ModelTokenLimitError("evidence_requires_rechunking")

    models = LongInputModels()
    with TestClient(create_app(token=TOKEN, encoder=models, reranker=models)) as client:
        response = client.post(
            "/v1/embeddings",
            headers=HEADERS,
            json=embedding_body(task="passage", texts=["PRIVATE evidence"]),
        )
        assert response.status_code == 422
        assert response.json()["error"] == {
            "code": "evidence_requires_rechunking",
            "retryable": False,
        }
        assert "PRIVATE" not in response.text
    with httpx.Client(
        base_url=MODEL_SERVICE_URL,
        transport=httpx.MockTransport(lambda _: httpx.Response(422, json=response.json())),
    ) as client:
        with pytest.raises(ModelServiceError) as caught:
            RemoteModels(client, token=TOKEN).encode_passages(["PRIVATE evidence"])
        assert caught.value.code == "evidence_requires_rechunking"
        assert not caught.value.retryable
