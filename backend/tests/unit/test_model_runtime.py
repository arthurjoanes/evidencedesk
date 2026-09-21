import json
from datetime import UTC

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from evidencedesk.model_runtime.azure import AzureResponsesGenerator, _strict_schema
from evidencedesk.model_runtime.contracts import (
    ContextEvidence,
    GeneratedDossier,
    GenerationRequest,
    ModelFailure,
    validate_generated_dossier,
)


def dossier():
    return {
        "summary": "Há confirmação de pagamento na fonte consultada.",
        "claims": [
            {
                "claim_id": None,
                "kind": "observed_fact",
                "text": "O pagamento foi confirmado.",
                "order_references": ["PED-1"],
                "evidence_links": [{"evidence_id": "e1", "relation": "supports"}],
                "support_status": "pending_review",
                "missing_information": [],
                "suggested_checks": [],
            }
        ],
        "outcome": "evidence_found",
        "missing_information": [],
        "suggested_checks": [],
    }


def generation_request():
    return GenerationRequest(
        question="O que foi observado?",
        evidence_snapshot_id="snap-1",
        evidence=(
            ContextEvidence(
                evidence_id="e1",
                text="Confirmação observada.",
                title="Evento de pagamento",
                kind="source_event",
                temporal_role="historical_artifact",
            ),
        ),
    )


def response_payload(*, text=None, status="completed", incomplete=None, refusal=False):
    content = (
        [{"type": "refusal", "refusal": "Não posso responder."}]
        if refusal
        else [
            {
                "type": "output_text",
                "text": text if text is not None else json.dumps(dossier()),
                "annotations": [],
            }
        ]
    )
    return {
        "id": "resp-test",
        "object": "response",
        "created_at": 1,
        "model": "deployment-version",
        "status": status,
        "error": None,
        "incomplete_details": incomplete,
        "output": [
            {
                "type": "message",
                "id": "msg-1",
                "status": "completed",
                "role": "assistant",
                "content": content,
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 80,
            "total_tokens": 180,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 4},
        },
    }


@pytest.mark.asyncio
async def test_adapter_uses_v1_structured_output_without_remote_state_or_sdk_retries():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response_payload(), headers={"x-request-id": "req-test"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = AsyncOpenAI(
            api_key="fixture-not-a-real-key",
            base_url="https://fixture.invalid/openai/v1/",
            http_client=http_client,
            max_retries=9,
        )
        result = await AzureResponsesGenerator(client, "test-deployment").generate(
            generation_request()
        )
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    assert str(calls[0].url) == "https://fixture.invalid/openai/v1/responses"
    assert body["model"] == "test-deployment"
    assert body["store"] is False and body["background"] is False
    assert body["text"]["format"]["strict"] is True
    assert result.usage.reasoning_tokens == 4
    assert result.usage.output_tokens == 80  # reasoning is included, never added twice
    assert result.request_id == "req-test"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "provider_credentials", False),
        (403, "provider_credentials", False),
        (404, "provider_deployment", False),
        (429, "provider_rate_limit", True),
        (503, "provider_unavailable", False),
    ],
)
async def test_status_errors_are_classified_without_amplifying_calls(status, code, retryable):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            json={"error": {"message": "SECRET raw provider text", "type": "error"}},
            headers={"retry-after": "7"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = AsyncOpenAI(
            api_key="fixture",
            base_url="https://fixture.invalid/openai/v1/",
            http_client=http_client,
        )
        with pytest.raises(ModelFailure) as caught:
            await AzureResponsesGenerator(client, "deployment").generate(generation_request())
    assert len(calls) == 1
    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert "SECRET" not in str(caught.value)
    assert caught.value.retry_after_seconds == 7


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (
            response_payload(status="incomplete", incomplete={"reason": "max_output_tokens"}),
            "provider_incomplete",
        ),
        (
            response_payload(status="incomplete", incomplete={"reason": "content_filter"}),
            "provider_filtered",
        ),
        (response_payload(refusal=True), "provider_refusal"),
        (response_payload(text="{invalid"), "invalid_schema"),
    ],
)
async def test_partial_refused_or_invalid_output_never_becomes_dossier(payload, code):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as http_client:
        client = AsyncOpenAI(
            api_key="fixture",
            base_url="https://fixture.invalid/openai/v1/",
            http_client=http_client,
        )
        with pytest.raises(ModelFailure) as caught:
            await AzureResponsesGenerator(client, "deployment").generate(generation_request())
    assert caught.value.code == code
    assert caught.value.usage.status == "reported"


@pytest.mark.asyncio
async def test_timeout_has_unknown_consumption_and_no_automatic_retry():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("uncertain after dispatch", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = AsyncOpenAI(
            api_key="fixture",
            base_url="https://fixture.invalid/openai/v1/",
            http_client=http_client,
        )
        with pytest.raises(ModelFailure) as caught:
            await AzureResponsesGenerator(client, "deployment").generate(generation_request())
    assert len(calls) == 1
    assert caught.value.code == "provider_timeout"
    assert caught.value.usage_status == "unknown"
    assert not caught.value.retryable


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("claim_id", "pretend-server-id", "invalid_claim_authority"),
        ("support_status", "reviewed", "invalid_claim_authority"),
    ],
)
def test_model_cannot_claim_human_review_or_assign_identity(field, value, code):
    data = dossier()
    data["claims"][0][field] = value
    with pytest.raises(ModelFailure, match="IA") as caught:
        validate_generated_dossier(GeneratedDossier.model_validate(data), {"e1"})
    assert caught.value.code == code


def test_citations_must_belong_to_provided_context():
    with pytest.raises(ModelFailure) as caught:
        validate_generated_dossier(GeneratedDossier.model_validate(dossier()), {"other-tenant"})
    assert caught.value.code == "invalid_citation"


def test_abstention_can_have_no_claims_but_evidence_outcome_cannot():
    assert GeneratedDossier(
        summary="Não há dados suficientes.", claims=[], outcome="insufficient_evidence"
    )
    with pytest.raises(ValidationError):
        GeneratedDossier(summary="Encontrado.", claims=[], outcome="evidence_found")


def test_strict_schema_requires_nullable_optional_fields_without_defaults():
    schema = _strict_schema(GeneratedDossier.model_json_schema())
    claim = schema["$defs"]["ClaimInput"]
    assert set(claim["required"]) == set(claim["properties"])
    assert "default" not in claim["properties"]["claim_id"]


def test_azure_schema_subset_does_not_remove_local_validation_limits():
    provider_schema = _strict_schema(GeneratedDossier.model_json_schema())
    assert "maxLength" not in provider_schema["properties"]["summary"]
    assert "maxItems" not in provider_schema["properties"]["claims"]
    assert "minLength" not in provider_schema["$defs"]["EvidenceLink"]["properties"]["evidence_id"]
    local_schema = GeneratedDossier.model_json_schema()
    assert local_schema["properties"]["summary"]["maxLength"] == 6000
    with pytest.raises(ValidationError):
        GeneratedDossier(summary="x" * 6001, claims=[], outcome="insufficient_evidence")


def test_schema_keyword_names_are_preserved_when_used_as_property_names():
    schema = _strict_schema(
        {"type": "object", "properties": {"format": {"type": "string", "maxLength": 10}}}
    )
    assert "format" in schema["properties"]
    assert "maxLength" not in schema["properties"]["format"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_model_trace_contains_metadata_but_no_prompt_or_raw_error(monkeypatch, failed):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from evidencedesk.model_runtime import azure

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(azure, "TRACER", provider.get_tracer("runtime-test"))

    def handler(request):
        if failed:
            return httpx.Response(
                403,
                json={"error": {"message": "PRIVATE provider text with secret", "type": "error"}},
            )
        return httpx.Response(200, json=response_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = AsyncOpenAI(
            api_key="fixture-secret",
            base_url="https://fixture.invalid/openai/v1/",
            http_client=http_client,
        )
        if failed:
            with pytest.raises(ModelFailure):
                await AzureResponsesGenerator(client, "deployment").generate(generation_request())
        else:
            await AzureResponsesGenerator(client, "deployment").generate(generation_request())
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "model.generate"
    exported = spans[0].to_json()
    assert "PRIVATE" not in exported and "fixture-secret" not in exported
    assert generation_request().question not in exported
    assert generation_request().evidence[0].text not in exported
    if failed:
        assert spans[0].attributes["error.type"] == "provider_credentials"
        assert not spans[0].events
    else:
        assert spans[0].attributes["evidencedesk.model.input_tokens"] == 100
    provider.shutdown()


@pytest.mark.asyncio
async def test_adapter_preserves_injected_connect_and_read_timeouts():
    observed = []

    def handler(request):
        observed.append(request.extensions["timeout"])
        return httpx.Response(200, json=response_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = AsyncOpenAI(
            api_key="fixture",
            base_url="https://fixture.invalid/openai/v1/",
            http_client=http_client,
            timeout=httpx.Timeout(80, connect=10),
        )
        await AzureResponsesGenerator(client, "deployment").generate(generation_request())
    assert observed[0]["connect"] == 10
    assert observed[0]["read"] == 80


@pytest.mark.asyncio
async def test_temporal_metadata_reaches_provider_as_json_without_losing_role():
    from datetime import datetime

    observed = []
    request = generation_request()
    source = request.evidence[0].model_copy(
        update={
            "valid_from": datetime(2026, 1, 1, tzinfo=UTC),
            "temporal_role": "retrospective_context",
        }
    )
    request = request.model_copy(update={"evidence": (source,)})

    def handler(http_request):
        observed.append(json.loads(http_request.content))
        return httpx.Response(200, json=response_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = AsyncOpenAI(
            api_key="fixture",
            base_url="https://fixture.invalid/openai/v1/",
            http_client=http_client,
        )
        await AzureResponsesGenerator(client, "deployment").generate(request)
    context = json.loads(observed[0]["input"][0]["content"])["evidence"][0]
    assert context["valid_from"] == "2026-01-01T00:00:00Z"
    assert context["temporal_role"] == "retrospective_context"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("invalid_output", "allowed_orders", "expected_error"),
    [
        (False, ["PED-1"], None),
        (True, ["PED-1"], "invalid_schema"),
        (False, [], "invalid_order_reference"),
    ],
)
async def test_pipeline_accounts_for_provider_response_before_rejecting_bad_draft(
    monkeypatch,
    invalid_output,
    allowed_orders,
    expected_error,
):
    from types import SimpleNamespace

    from pydantic import SecretStr

    from evidencedesk.errors import Problem
    from evidencedesk.investigations import processing
    from evidencedesk.jobs.service import Lease

    events = []
    real_client = AsyncOpenAI
    settings = SimpleNamespace(
        ai_max_output_tokens=2400,
        azure_openai_api_key=SecretStr("fixture-not-a-secret"),
        azure_openai_base_url="https://fixture.invalid/openai/v1/",
        azure_openai_deployment="changed-setting-must-not-be-used",
    )

    def authorize(lease, release, input_estimate):
        assert input_estimate <= release.limits.max_input_tokens
        events.append(("authorize", release.deployment))
        return "call-fixture"

    def authorize_context(lease, request):
        assert request.evidence_snapshot_id == "snap-1"

    def forbidden_database(*args, **kwargs):
        raise AssertionError("Runtime unit tests must never open a database connection.")

    def reconcile(lease, call_id, usage, response_id, *, failed, error_code=None):
        events.append(("account", call_id, usage.status, usage.input_tokens, response_id, failed))

    def handler(request):
        events.append(("provider", json.loads(request.content)["model"]))
        return httpx.Response(200, json=response_payload(text="{bad" if invalid_output else None))

    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs):
        return real_client(**kwargs, http_client=httpx.AsyncClient(transport=transport))

    monkeypatch.setattr(processing, "get_settings", lambda: settings)
    monkeypatch.setattr(processing, "authorize_dispatch", authorize)
    monkeypatch.setattr(processing, "authorize_context", authorize_context)
    monkeypatch.setattr(processing, "transaction", forbidden_database)
    monkeypatch.setattr(processing, "reconcile_usage", reconcile)
    monkeypatch.setattr(processing, "AsyncOpenAI", client_factory)
    lease = Lease(
        "tenant-fixture", "job-fixture", "run-fixture", "user-fixture", "investigation", 1, 1
    )
    from evidencedesk.config import Settings
    from evidencedesk.model_runtime.release import freeze_release

    release = freeze_release(Settings()).model_copy(update={"deployment": "frozen-deployment"})
    run = {
        "question": "O que ocorreu?",
        "snapshot_id": "snap-1",
        "model_release": release.model_dump(mode="json"),
        "allowed_order_references": allowed_orders,
    }
    if expected_error:
        with pytest.raises(Problem) as caught:
            await processing.generate(
                lease,
                run,
                [
                    generation_request()
                    .evidence[0]
                    .model_copy(update={"kind": "reconciliation_result"})
                ],
            )
        assert caught.value.code == expected_error
    else:
        result = await processing.generate(
            lease,
            run,
            [generation_request().evidence[0].model_copy(update={"kind": "reconciliation_result"})],
        )
        assert result.deployment == "frozen-deployment"
    assert [event[0] for event in events] == ["authorize", "provider", "account"]
    assert events[0][1] == events[1][1] == "frozen-deployment"
    assert events[2][2:5] == ("reported", 100, "resp-test")
