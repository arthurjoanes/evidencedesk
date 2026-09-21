import hashlib

import pytest
from pydantic import ValidationError

from evidencedesk.config import Settings
from evidencedesk.errors import Problem
from evidencedesk.model_runtime.azure import response_payload
from evidencedesk.model_runtime.contracts import ContextEvidence, GenerationRequest
from evidencedesk.model_runtime.release import (
    ESTIMATION_METHOD,
    FrozenModelRelease,
    bounded_request,
    estimate_input_tokens,
    freeze_release,
    load_release,
    validate_azure_base_url,
)


def aggregate():
    return ContextEvidence(
        evidence_id="reconciliation",
        title="Conciliação",
        text='{"orders": 1}',
        kind="reconciliation_result",
        temporal_role="historical_artifact",
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://agentes-sol-foundry.openai.azure.com/openai/v1/",
        "https://evil.example/openai/v1/",
        "https://agentes-sol-foundry.openai.azure.com.evil.example/openai/v1/",
        "https://secret@agentes-sol-foundry.openai.azure.com/openai/v1/",
        "https://agentes-sol-foundry.openai.azure.com:444/openai/v1/",
        "https://agentes-sol-foundry.openai.azure.com/openai/v1/?proxy=other",
        "https://agentes-sol-foundry.openai.azure.com/openai/v1/#fragment",
        "https://agentes-sol-foundry.services.ai.azure.com/api/projects/agentes-sol",
        "https://agentes-sol-foundry.openai.azure.com/openai/v1/\n",
    ],
)
def test_runtime_endpoint_allowlist_rejects_unapproved_routes(url):
    with pytest.raises(ValueError):
        validate_azure_base_url(url)


def test_frozen_release_preserves_prompt_endpoint_limits_and_hashes():
    settings = Settings()
    release = freeze_release(settings)
    assert release.prompt_sha256 == hashlib.sha256(release.instructions.encode()).hexdigest()
    assert release.estimation_method == ESTIMATION_METHOD
    assert release.limits.max_input_tokens == settings.ai_max_input_tokens
    assert load_release(release.model_dump(mode="json")) == release
    with pytest.raises(ValidationError):
        FrozenModelRelease.model_validate({**release.model_dump(), "instructions": "changed"})


def test_schema_drift_blocks_queued_release_before_provider_dispatch():
    release = freeze_release(Settings()).model_dump()
    release["schema_sha256"] = "0" * 64
    with pytest.raises(Problem) as caught:
        load_release(release)
    assert caught.value.code == "model_schema_changed"


def test_estimate_counts_unicode_schema_instructions_and_envelope():
    release = freeze_release(Settings())
    request = GenerationRequest(
        question="Há confirmação? 🔎", evidence_snapshot_id="snapshot", evidence=(aggregate(),)
    )
    payload = response_payload(request, release.deployment, release.instructions)
    estimate = estimate_input_tokens(request, release)
    assert estimate > len(request.question.encode()) + len(aggregate().text.encode())
    assert estimate > len(release.instructions.encode()) + len(str(payload["text"]).encode())
    assert estimate > estimate_input_tokens(request.model_copy(update={"question": "?"}), release)


def test_budget_removes_whole_documents_but_keeps_required_aggregate():
    release = freeze_release(Settings())
    minimum = GenerationRequest(
        question="O que ocorreu?",
        evidence_snapshot_id="snapshot",
        evidence=(aggregate(),),
        max_output_tokens=release.limits.max_output_tokens,
    )
    limit = estimate_input_tokens(minimum, release) + 100
    release = release.model_copy(
        update={"limits": release.limits.model_copy(update={"max_input_tokens": limit})}
    )
    document = ContextEvidence(
        evidence_id="document",
        title="Manual",
        text="X" * 6000,
        kind="document_span",
        temporal_role="historical_artifact",
    )
    request, estimate = bounded_request(
        "O que ocorreu?", "snapshot", [aggregate(), document], release
    )
    assert request.evidence == (aggregate(),)
    assert estimate <= limit
    assert document.text == "X" * 6000


def test_minimum_context_over_budget_fails_without_dispatch():
    release = freeze_release(Settings())
    release = release.model_copy(
        update={"limits": release.limits.model_copy(update={"max_input_tokens": 1024})}
    )
    with pytest.raises(Problem) as caught:
        bounded_request("O que ocorreu?", "snapshot", [aggregate()], release)
    assert caught.value.code == "input_budget_exceeded"
