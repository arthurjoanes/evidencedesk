"""Real API/jobs/storage with a deliberately simulated provider transport, never Azure."""

import asyncio
import hashlib
import json

import httpx2
import pytest
from openai import AsyncOpenAI
from sqlalchemy import text
from test_manual_workflow import create_incident, import_document

from evidencedesk.config import get_settings
from evidencedesk.database import lock_policy, transaction
from evidencedesk.errors import Problem
from evidencedesk.evidence.storage import PrivateStorage
from evidencedesk.identity.service import actor_for_worker
from evidencedesk.investigations import processing
from evidencedesk.jobs.service import acquire, cancel
from evidencedesk.worker import execute_lease

pytestmark = pytest.mark.integration


def provider_response():
    dossier = {
        "summary": "A coleta não oferece eventos operacionais suficientes.",
        "claims": [],
        "outcome": "insufficient_evidence",
        "missing_information": ["Eventos de pagamento da janela"],
        "suggested_checks": ["Importar o extrato de pagamentos"],
    }
    return {
        "id": "resp-fixture-only",
        "object": "response",
        "created_at": 1,
        "model": "fixture-version",
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "output": [
            {
                "type": "message",
                "id": "msg-fixture",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": json.dumps(dossier), "annotations": []}
                ],
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


def prepare_run(workspace, monkeypatch):
    client = workspace["client"]()
    tenant = workspace["tenants"][0]
    snapshot = import_document(client, tenant)
    incident = create_incident(client)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fixture-no-network-transport")
    monkeypatch.setenv("ED_AI_PROVIDER", "azure_openai")
    get_settings.cache_clear()
    body = {
        "evidence_snapshot_id": snapshot,
        "question": "Quais lacunas existem nos eventos de pagamento?",
    }
    url = f"/api/v1/incidents/{incident}/runs"
    response = client.post(url, json=body, headers={"Idempotency-Key": "first-run"})
    assert response.status_code == 202, response.text
    run = response.json()
    assert (
        client.post(url, json=body, headers={"Idempotency-Key": "first-run"}).json()["id"]
        == run["id"]
    )
    assert (
        client.post(
            url,
            json=body | {"question": "Outro pedido de investigação"},
            headers={"Idempotency-Key": "first-run"},
        ).status_code
        == 409
    )
    return client, tenant, run


def mock_transport(monkeypatch, handler):
    def factory(**kwargs):
        return AsyncOpenAI(
            **kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        )

    monkeypatch.setattr(processing, "AsyncOpenAI", factory)


def test_generated_draft_reopens_from_db_artifacts_and_sse_without_provider(workspace, monkeypatch):
    client, tenant, run = prepare_run(workspace, monkeypatch)
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx2.Response(200, json=provider_response())

    mock_transport(monkeypatch, handler)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "changed-after-admission")
    get_settings.cache_clear()
    lease = acquire(tenant, "generation-fixture")
    assert lease is not None
    execute_lease(lease)
    result = client.get(f"/api/v1/runs/{run['id']}")
    assert result.status_code == 200, result.text
    state = result.json()
    assert state["state"] == "succeeded", result.text
    assert state["outcome"] == "insufficient_evidence"
    assert len(calls) == 1
    assert calls[0]["model"] == "fixture-deployment"
    assert calls[0]["store"] is False and calls[0]["background"] is False
    assert state["usage"]["input_tokens"] == 100 and state["usage"]["output_tokens"] == 80
    assert [step["key"] for step in state["steps"]] == [
        "reconciliation",
        "planning",
        "retrieval",
        "generation",
        "validation",
    ]
    assert all(step["status"] == "succeeded" and step["completed_at"] for step in state["steps"])
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
    get_settings.cache_clear()
    dossier = client.get(f"/api/v1/dossiers/{state['dossier_id']}")
    assert dossier.status_code == 200 and dossier.json()["origin"] == "ai"
    revision = client.get(
        f"/api/v1/dossiers/{state['dossier_id']}/revisions/{state['revision_id']}"
    )
    assert revision.json()["review_status"] == "draft"
    events = client.get(f"/api/v1/runs/{run['id']}/events")
    assert events.status_code == 200 and "event: terminal" in events.text
    assert "event: snapshot" in events.text
    assert (
        "event: resync_required"
        in client.get(f"/api/v1/runs/{run['id']}/events", headers={"Last-Event-ID": "9999"}).text
    )
    with transaction(tenant) as connection:
        artifact = (
            connection.execute(
                text("SELECT * FROM result_artifacts WHERE run_id=:id"), {"id": run["id"]}
            )
            .mappings()
            .one()
        )
        policy = (
            connection.execute(text("SELECT token_reserved,token_reported FROM tenant_policy"))
            .mappings()
            .one()
        )
    assert policy["token_reserved"] == 0 and policy["token_reported"] == 180
    stored = PrivateStorage().read(artifact["result_key"])
    assert hashlib.sha256(stored).hexdigest() == artifact["result_sha256"]
    assert json.loads(stored)["response_id"] == "resp-fixture-only"
    assert len(calls) == 1  # read/reconnect never invokes generation again


def test_cancellation_during_provider_call_accounts_usage_but_forbids_publication(
    workspace, monkeypatch
):
    client, tenant, run = prepare_run(workspace, monkeypatch)

    def handler(request):
        with transaction(tenant) as connection:
            lock_policy(connection, tenant)
            actor = actor_for_worker(connection, tenant, tenant + "-author")
            cancel(connection, actor, run["id"])
        return httpx2.Response(200, json=provider_response())

    mock_transport(monkeypatch, handler)
    lease = acquire(tenant, "cancel-fixture")
    assert lease is not None
    execute_lease(lease)
    response = client.get(f"/api/v1/runs/{run['id']}").json()
    assert response["state"] == "cancelled" and response["dossier_id"] is None
    with transaction(tenant) as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM dossiers WHERE run_id=:id"), {"id": run["id"]}
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM result_artifacts WHERE run_id=:id"), {"id": run["id"]}
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(text("SELECT token_reported FROM tenant_policy")).scalar_one() == 180
        )


def test_ambiguous_timeout_keeps_reservation_and_never_automatically_repeats(
    workspace, monkeypatch
):
    client, tenant, run = prepare_run(workspace, monkeypatch)
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx2.ReadTimeout("Sensitive provider payload must not escape", request=request)

    mock_transport(monkeypatch, handler)
    lease = acquire(tenant, "timeout-fixture")
    assert lease is not None
    execute_lease(lease)
    response = client.get(f"/api/v1/runs/{run['id']}")
    assert response.json()["state"] == "failed", response.text
    assert response.json()["usage"]["status"] == "unknown"
    assert "Sensitive" not in response.text
    assert acquire(tenant, "second-worker") is None and len(calls) == 1
    with transaction(tenant) as connection:
        reservation = connection.execute(
            text("SELECT token_reserved FROM tenant_policy")
        ).scalar_one()
        call = (
            connection.execute(
                text("SELECT status,error_code FROM provider_calls WHERE run_id=:id"),
                {"id": run["id"]},
            )
            .mappings()
            .one()
        )
    assert reservation == 12400
    assert call["status"] == "unknown" and call["error_code"] == "provider_timeout"


def test_changed_source_text_is_rejected_before_paid_dispatch(workspace, monkeypatch):
    _, tenant, _ = prepare_run(workspace, monkeypatch)
    lease = acquire(tenant, "source-check-fixture")
    assert lease is not None
    run, sources = processing.investigation_context(lease)
    sources[0] = sources[0].model_copy(update={"text": "Conteúdo substituído fora do snapshot"})
    with pytest.raises(Problem) as caught:
        asyncio.run(processing.generate(lease, run, sources))
    assert caught.value.code == "dispatch_source_changed"
    with transaction(tenant) as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM provider_calls WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            ).scalar_one()
            == 0
        )


def test_revocation_during_paid_call_records_usage_without_publishing(workspace, monkeypatch):
    _, tenant, run = prepare_run(workspace, monkeypatch)

    def handler(_request):
        with workspace["admin"].begin() as connection:
            connection.execute(
                text("UPDATE tenant_policy SET revision=revision+1 WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            )
            connection.execute(
                text("DELETE FROM collection_grants WHERE tenant_id=:tenant"), {"tenant": tenant}
            )
        return httpx2.Response(200, json=provider_response())

    mock_transport(monkeypatch, handler)
    lease = acquire(tenant, "revoke-provider-fixture")
    assert lease is not None
    execute_lease(lease)
    with transaction(tenant) as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM dossiers WHERE run_id=:run"), {"run": run["id"]}
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM result_artifacts WHERE run_id=:run"), {"run": run["id"]}
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(text("SELECT token_reported FROM tenant_policy")).scalar_one() == 180
        )


@pytest.mark.parametrize("disabled_setting", ["provider", "credential", "allowed_host"])
def test_queued_run_honors_generation_disabled_before_dispatch(
    workspace, monkeypatch, disabled_setting
):
    client, tenant, run = prepare_run(workspace, monkeypatch)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(200, json=provider_response())

    mock_transport(monkeypatch, handler)
    if disabled_setting == "provider":
        monkeypatch.setenv("ED_AI_PROVIDER", "disabled")
    elif disabled_setting == "credential":
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
    else:
        monkeypatch.setenv("ED_AZURE_OPENAI_ALLOWED_HOSTS", "replacement-resource.openai.azure.com")
    get_settings.cache_clear()
    lease = acquire(tenant, "disabled-generator-fixture")
    assert lease is not None
    execute_lease(lease)
    state = client.get(f"/api/v1/runs/{run['id']}").json()
    assert state["state"] == "failed"
    assert state["error"]["code"] == (
        "model_release_incompatible"
        if disabled_setting == "allowed_host"
        else "generator_unavailable"
    )
    assert calls == []
    with transaction(tenant) as connection:
        assert connection.execute(text("SELECT count(*) FROM provider_calls")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM dossiers")).scalar_one() == 0
        assert (
            connection.execute(text("SELECT token_reserved FROM tenant_policy")).scalar_one() == 0
        )
