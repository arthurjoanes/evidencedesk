import asyncio
import hashlib
import json
from contextlib import ExitStack
from datetime import UTC, datetime

import httpx
from httpx2 import Timeout
from openai import AsyncOpenAI
from sqlalchemy import text

from evidencedesk.config import get_settings
from evidencedesk.database import transaction
from evidencedesk.errors import Problem
from evidencedesk.evidence.service import resolve_evidence
from evidencedesk.evidence.storage import PrivateStorage
from evidencedesk.identity.service import actor_for_worker
from evidencedesk.investigations.budget import authorize_dispatch, reconcile_usage
from evidencedesk.investigations.service import append_event, authorize_run
from evidencedesk.investigations.tools import (
    ExecutionContext,
    ReadTools,
    SearchArguments,
    plan_investigation,
    reconciliation_summary,
)
from evidencedesk.jobs.service import Lease, assert_publishable, complete
from evidencedesk.model_runtime.azure import AzureResponsesGenerator
from evidencedesk.model_runtime.contracts import ContextEvidence, GenerationRequest, ModelFailure
from evidencedesk.model_runtime.release import bounded_request, load_release
from evidencedesk.retrieval.http_client import MODEL_SERVICE_URL, RemoteModels
from evidencedesk.reviews.service import create_dossier


def checkpoint(lease: Lease, stage: str) -> None:
    from evidencedesk.jobs.progress import update_steps

    with transaction(lease.tenant_id) as connection:
        assert_publishable(connection, lease)
        update_steps(connection, lease.tenant_id, lease.resource_id, "running", stage)
        connection.execute(
            text("UPDATE jobs SET stage=:stage WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": lease.tenant_id, "id": lease.job_id, "stage": stage},
        )
        append_event(
            connection,
            lease.tenant_id,
            lease.resource_id,
            "progress",
            {"state": "running", "stage": stage},
        )


def investigation_context(lease: Lease) -> tuple[dict, list[ContextEvidence]]:
    context = ExecutionContext.from_lease(lease)
    with transaction(lease.tenant_id) as connection:
        actor = context.authorize(connection)
        run = authorize_run(connection, actor, lease.resource_id)
    release = load_release(run["model_release"])
    with ExitStack() as resources:
        models = None
        if release.retrieval_profile != "lexical":
            token = get_settings().model_service_token.get_secret_value()
            if len(token) < 24:
                raise Problem(
                    503, "model_service_configuration", "Configure o perfil privado de modelos."
                )
            client = resources.enter_context(
                httpx.Client(
                    base_url=MODEL_SERVICE_URL,
                    trust_env=False,
                    limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
                )
            )
            models = RemoteModels(client, token=token)
        tools = ReadTools(context, mode=release.retrieval_profile, models=models)
        reconciliation = tools.summarize_reconciliation()
        checkpoint(lease, "planning")
        plan = plan_investigation(run["question"])
        checkpoint(lease, "retrieval")
        sources = tools.search(SearchArguments(query=plan.questions[0]))
    run["plan"] = plan.model_dump(mode="json")
    with transaction(lease.tenant_id) as connection:
        context.authorize(connection)
        # The model cites an immutable deterministic artifact for aggregates. Raw event
        # arithmetic is never delegated to generation.
        aggregate = reconciliation_summary(reconciliation)
        canonical = json.dumps(aggregate, ensure_ascii=False, separators=(",", ":"))
        evidence_id = f"reconciliation_{lease.resource_id}_{lease.token}"
        collection = connection.execute(
            text("SELECT collection_id FROM incidents WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": lease.tenant_id, "id": run["incident_id"]},
        ).scalar_one()
        source_ids = (
            connection.execute(
                text("""
            SELECT e.id FROM evidence e JOIN snapshot_members m ON m.tenant_id=e.tenant_id AND m.evidence_id=e.id
            JOIN incidents i ON i.tenant_id=e.tenant_id AND i.id=:incident
            WHERE e.tenant_id=:tenant AND m.snapshot_id=:snapshot AND e.kind IN('source_event','order_snapshot') AND e.tombstoned_at IS NULL
              AND CAST(coalesce(e.record->>'occurred_at',e.record->>'observed_at',e.record->>'as_of') AS timestamptz)
                  BETWEEN i.window_from AND i.window_to
        """),
                {
                    "tenant": lease.tenant_id,
                    "snapshot": run["snapshot_id"],
                    "incident": run["incident_id"],
                },
            )
            .scalars()
            .all()
        )
        connection.execute(
            text("""
            INSERT INTO evidence(tenant_id,id,collection_id,kind,title,version,sha256,source_system,temporal_role,canonical_text,record)
            VALUES(:tenant,:id,:collection,'reconciliation_result','Conciliação determinística do recorte',:version,:hash,'evidencedesk','historical_artifact',:canonical,CAST(:record AS jsonb))
            ON CONFLICT(tenant_id,id) DO NOTHING
        """),
            {
                "tenant": lease.tenant_id,
                "id": evidence_id,
                "collection": collection,
                "version": reconciliation.rule_revision,
                "hash": hashlib.sha256(canonical.encode()).hexdigest(),
                "canonical": canonical,
                "record": json.dumps(
                    {
                        "source_ids": sorted(source_ids),
                        "run_id": lease.resource_id,
                        "snapshot_id": run["snapshot_id"],
                    }
                ),
            },
        )
        sources.insert(
            0,
            ContextEvidence(
                evidence_id=evidence_id,
                text=canonical,
                kind="reconciliation_result",
                temporal_role="historical_artifact",
                title="Conciliação determinística do recorte",
            ),
        )
        # Keep entire cited chunks; omitted chunks remain searchable in the product.
        bounded: list[ContextEvidence] = []
        used_characters = 0
        for source in sources:
            if used_characters + len(source.text) <= 26000:
                bounded.append(source)
                used_characters += len(source.text)
        run["allowed_order_references"] = sorted(
            {
                item.order_reference
                for item in reconciliation.timeline
                if item.order_reference is not None
            }
        )
        run["impact_summary"] = reconciliation.counts.model_dump() | {"evidence_id": evidence_id}
        return run, bounded


def authorize_context(lease: Lease, request: GenerationRequest) -> None:
    # Check each actual dispatched source, including derived dependencies. The
    # subsequent admission rechecks the same policy revision under its lock.
    with transaction(lease.tenant_id) as connection:
        assert_publishable(connection, lease)
        actor = actor_for_worker(connection, lease.tenant_id, lease.actor_id)
        current = authorize_run(connection, actor, lease.resource_id)
        if current["snapshot_id"] != request.evidence_snapshot_id:
            raise Problem(409, "tool_scope_changed", "O escopo da investigação mudou.")
        for source in request.evidence:
            persisted = resolve_evidence(
                connection, actor, source.evidence_id, current["snapshot_id"]
            )
            if any(
                persisted[field] != getattr(source, attribute)
                for field, attribute in (
                    ("canonical_text", "text"),
                    ("kind", "kind"),
                    ("title", "title"),
                    ("temporal_role", "temporal_role"),
                    ("valid_from", "valid_from"),
                    ("valid_until", "valid_until"),
                )
            ):
                raise Problem(409, "dispatch_source_changed", "Uma fonte mudou após a recuperação.")


async def generate(lease: Lease, run: dict, sources: list[ContextEvidence]):
    settings = get_settings()
    release = load_release(run["model_release"])
    request, input_estimate = bounded_request(run["question"], run["snapshot_id"], sources, release)
    authorize_context(lease, request)
    call_id = authorize_dispatch(lease, release, input_estimate)
    try:
        async with AsyncOpenAI(
            api_key=settings.azure_openai_api_key.get_secret_value(),
            base_url=release.base_url,
            max_retries=0,
            timeout=Timeout(
                release.limits.read_timeout_seconds, connect=release.limits.connect_timeout_seconds
            ),
        ) as client:
            async with asyncio.timeout(release.limits.total_timeout_seconds):
                result = await AzureResponsesGenerator(
                    client, release.deployment, instructions=release.instructions
                ).generate(request)
    except ModelFailure as error:
        reconcile_usage(
            lease, call_id, error.usage, error.response_id, failed=True, error_code=error.code
        )
        raise Problem(
            503 if error.retryable else 422, error.code, str(error), retryable=error.retryable
        ) from None
    except TimeoutError:
        reconcile_usage(lease, call_id, None, None, failed=True, error_code="provider_timeout")
        raise Problem(
            503, "provider_timeout", "A chamada excedeu o prazo. O consumo permanece reservado."
        ) from None
    except OSError:
        reconcile_usage(
            lease, call_id, None, None, failed=True, error_code="provider_outcome_unknown"
        )
        raise Problem(
            503,
            "provider_outcome_unknown",
            "A chamada não teve confirmação. O consumo permanece reservado.",
        ) from None
    reconcile_usage(lease, call_id, result.usage, result.response_id, failed=False)
    allowed_orders = set(run["allowed_order_references"])
    if any(
        order not in allowed_orders
        for claim in result.dossier.claims
        for order in claim.order_references
    ):
        raise Problem(
            422, "invalid_order_reference", "A síntese citou um pedido fora do recorte autorizado."
        )
    return result.model_copy(
        update={
            "input_token_estimate": input_estimate,
            "input_estimation_method": release.estimation_method,
        }
    )


def process_investigation(lease: Lease) -> None:
    checkpoint(lease, "reconciliation")
    run, sources = investigation_context(lease)
    checkpoint(lease, "generation")
    result = asyncio.run(generate(lease, run, sources))
    checkpoint(lease, "validation")
    storage = PrivateStorage()
    prefix = f"tenants/{lease.tenant_id}/runs/{lease.resource_id}/attempts/{lease.token}"
    result_key = f"{prefix}/result.json"
    result_hash = storage.put(result_key, result.model_dump_json().encode())
    manifest = {
        "schema_version": "1",
        "run_id": lease.resource_id,
        "attempt_token": lease.token,
        "snapshot_id": run["snapshot_id"],
        "saved_at": datetime.now(UTC).isoformat(),
        "release": run["model_release"],
        "plan": run["plan"],
        "context_sources": [
            {
                "evidence_id": source.evidence_id,
                "canonical_sha256": hashlib.sha256(source.text.encode()).hexdigest(),
            }
            for source in bounded_request(
                run["question"], run["snapshot_id"], sources, load_release(run["model_release"])
            )[0].evidence
        ],
        "deployment": result.deployment,
        "returned_model": result.returned_model,
        "response_id": result.response_id,
        "usage": result.usage.model_dump(),
        "result_sha256": result_hash,
        "validation": "schema_and_references_passed_semantic_support_pending",
    }
    manifest_key = f"{prefix}/manifest.json"
    manifest_hash = storage.put(manifest_key, json.dumps(manifest, ensure_ascii=False).encode())
    with transaction(lease.tenant_id) as connection:
        assert_publishable(connection, lease)
        actor = actor_for_worker(connection, lease.tenant_id, lease.actor_id)
        run = authorize_run(connection, actor, lease.resource_id)
        dossier_id, revision_id = create_dossier(
            connection,
            actor,
            run["incident_id"],
            run["snapshot_id"],
            result.dossier,
            origin="ai",
            run_id=lease.resource_id,
        )
        connection.execute(
            text("""
            UPDATE investigation_runs SET outcome=:outcome,dossier_id=:dossier,revision_id=:revision,usage=usage || CAST(:usage AS jsonb)
            WHERE tenant_id=:tenant AND id=:id
        """),
            {
                "tenant": lease.tenant_id,
                "id": lease.resource_id,
                "outcome": result.dossier.outcome,
                "dossier": dossier_id,
                "revision": revision_id,
                "usage": result.usage.model_dump_json(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO result_artifacts VALUES(:tenant,:run,:token,:result,:result_hash,:manifest,:manifest_hash)"
            ),
            {
                "tenant": lease.tenant_id,
                "run": lease.resource_id,
                "token": lease.token,
                "result": result_key,
                "result_hash": result_hash,
                "manifest": manifest_key,
                "manifest_hash": manifest_hash,
            },
        )
        complete(connection, lease)
        append_event(
            connection,
            lease.tenant_id,
            lease.resource_id,
            "terminal",
            {
                "state": "succeeded",
                "stage": "complete",
                "dossier_id": dossier_id,
                "revision_id": revision_id,
            },
        )
