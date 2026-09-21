import hashlib

import pytest
from pydantic import ValidationError

from evidencedesk.config import Settings, get_settings
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


@pytest.mark.parametrize("domain", ["openai.azure.com", "services.ai.azure.com"])
def test_operator_can_configure_own_azure_resource_and_deployment(monkeypatch, domain):
    host = f"other-company-resource.{domain}"
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", f"https://{host}:443/openai/v1")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "my-reviewed-deployment")
    monkeypatch.setenv("ED_AZURE_OPENAI_ALLOWED_HOSTS", host)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "synthetic-no-network")
    monkeypatch.setenv("ED_AI_PROVIDER", "azure_openai")
    get_settings.cache_clear()
    settings = Settings()
    assert settings.generation_enabled
    release = freeze_release(settings)
    assert release.base_url == f"https://{host}/openai/v1/"
    assert release.deployment == "my-reviewed-deployment"
    assert load_release(release.model_dump()) == release


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://localhost/openai/v1/", "localhost"),
        ("https://127.0.0.1/openai/v1/", "127.0.0.1"),
        ("https://169.254.169.254/openai/v1/", "169.254.169.254"),
        ("https://evil.example/openai/v1/", "evil.example"),
        ("https://r.openai.azure.com.evil.example/openai/v1/", "r.openai.azure.com.evil.example"),
        ("https://r.openai.azure.com/openai/v1/", "*.openai.azure.com"),
        ("https://r.openai.azure.com/openai/v1/", "other.openai.azure.com"),
        ("https://r.openai.azure.com/openai/v1/", ""),
        ("https://r.openai.azure.com/openai/v1/", "r.openai.azure.com,"),
        ("https://r.openai.azure.com./openai/v1/", "r.openai.azure.com"),
        ("https://r.openai.azure.com/openai/v1//", "r.openai.azure.com"),
        ("https://r.openai.azure.com/openai/%76%31/", "r.openai.azure.com"),
        ("https://r.openai.azure.com\\@evil.example/openai/v1/", "r.openai.azure.com"),
    ],
)
def test_runtime_allowlist_cannot_enable_arbitrary_urls_or_wildcards(url, allowed):
    with pytest.raises(ValueError):
        validate_azure_base_url(url, allowed)


def test_unconfigured_clone_keeps_generation_disabled_without_a_personal_endpoint(monkeypatch):
    for key in (
        "AZURE_OPENAI_BASE_URL",
        "AZURE_OPENAI_DEPLOYMENT",
        "ED_AZURE_OPENAI_ALLOWED_HOSTS",
    ):
        monkeypatch.delenv(key)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "a-key-alone-is-not-configuration")
    settings = Settings()
    assert settings.azure_openai_base_url == ""
    assert settings.azure_openai_deployment == ""
    assert settings.azure_openai_allowed_hosts == ""
    assert not settings.generation_enabled


def test_disabled_runtime_message_explains_the_available_manual_workflow():
    from datetime import UTC, datetime

    from evidencedesk.identity.service import Actor, session_payload

    actor = Actor("analyst", "tenant", "Analyst", "Tenant", "reviewer", "csrf", datetime.now(UTC))
    runtime = session_payload(actor)["runtime"]
    assert not runtime["generation_enabled"]
    assert runtime["disabled_reason"] == (
        "A geração com IA não está disponível neste ambiente. "
        "Você pode continuar a investigação e editar o dossiê manualmente."
    )


def test_removing_host_from_runtime_blocks_a_previously_frozen_release(monkeypatch):
    release = freeze_release(Settings())
    monkeypatch.setenv("ED_AZURE_OPENAI_ALLOWED_HOSTS", "replacement-resource.openai.azure.com")
    get_settings.cache_clear()
    with pytest.raises(Problem) as caught:
        load_release(release.model_dump())
    assert caught.value.code == "model_release_incompatible"


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
