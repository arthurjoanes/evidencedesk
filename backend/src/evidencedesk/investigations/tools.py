"""Small read-tool boundary. Identity and authority never come from model arguments."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from evidencedesk.audit import record_action
from evidencedesk.database import transaction
from evidencedesk.errors import Problem
from evidencedesk.evidence.service import resolve_evidence
from evidencedesk.identity.service import actor_for_worker
from evidencedesk.incidents.service import load_reconciliation
from evidencedesk.investigations.service import authorize_run
from evidencedesk.jobs.service import Lease, assert_publishable
from evidencedesk.model_runtime.contracts import ContextEvidence
from evidencedesk.reconciliation import ReconciliationResult
from evidencedesk.retrieval.http_client import RemoteModels
from evidencedesk.retrieval.http_contracts import ModelServiceError
from evidencedesk.retrieval.local_models import EMBEDDING_REVISION
from evidencedesk.retrieval.repository import rerank_evidence, search_evidence
from evidencedesk.telemetry.signals import TRACER

T = TypeVar("T")
MAX_TOOL_CALLS = 8
MAX_OUTPUT_BYTES = 64_000
MAX_TOOL_SECONDS = 120


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchArguments(Arguments):
    query: str = Field(min_length=1, max_length=3000)
    limit: int = Field(default=8, ge=1, le=8)


class ReadArguments(Arguments):
    evidence_id: str = Field(min_length=1, max_length=200)
    start: int = Field(default=0, ge=0)
    length: int = Field(default=4000, ge=1, le=8000)


class TimelineArguments(Arguments):
    order_reference: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=20, ge=1, le=50)


class CompareArguments(Arguments):
    first_id: str = Field(min_length=1, max_length=200)
    second_id: str = Field(min_length=1, max_length=200)


class InvestigationPlan(Arguments):
    revision: str = "single-question-v1"
    questions: tuple[str, ...] = Field(min_length=1, max_length=3)


def plan_investigation(question: str) -> InvestigationPlan:
    # Baseline keeps the user's actual question. Decomposition remains an evaluated
    # experiment; generating three paraphrases by default adds cost, not evidence.
    validated = SearchArguments(query=question.strip())
    return InvestigationPlan(questions=(validated.query,))


def reconciliation_summary(result: ReconciliationResult) -> dict:
    summary: dict = {
        "counts": result.counts.model_dump(),
        "rule_revision": result.rule_revision,
        "window": result.window.model_dump(mode="json", by_alias=True),
        "coverage": [item.model_dump(mode="json", by_alias=True) for item in result.coverage],
        "divergences": [
            item.model_dump(mode="json", exclude={"evidence_ids"})
            for item in result.divergences[:15]
        ],
        "divergences_included": min(15, len(result.divergences)),
        "divergences_total": len(result.divergences),
    }
    while len(json.dumps(summary, ensure_ascii=False).encode()) > 6000:
        if not summary["divergences"]:
            raise Problem(422, "context_too_large", "Reduza o recorte da investigação.")
        summary["divergences"].pop()
        summary["divergences_included"] = len(summary["divergences"])
    return summary


@dataclass(frozen=True)
class ExecutionContext:
    lease: Lease
    incident_id: str
    snapshot_id: str

    @classmethod
    def from_lease(cls, lease: Lease) -> ExecutionContext:
        with transaction(lease.tenant_id) as connection:
            assert_publishable(connection, lease)
            actor = actor_for_worker(connection, lease.tenant_id, lease.actor_id)
            run = authorize_run(connection, actor, lease.resource_id)
            return cls(lease, run["incident_id"], run["snapshot_id"])

    def authorize(self, connection):
        assert_publishable(connection, self.lease)
        actor = actor_for_worker(connection, self.lease.tenant_id, self.lease.actor_id)
        run = authorize_run(connection, actor, self.lease.resource_id)
        if run["incident_id"] != self.incident_id or run["snapshot_id"] != self.snapshot_id:
            raise Problem(409, "tool_scope_changed", "O escopo da investigação mudou.")
        return actor


class ReadTools:
    def __init__(
        self,
        context: ExecutionContext,
        *,
        mode: str = "lexical",
        models: RemoteModels | None = None,
    ) -> None:
        if mode not in {"lexical", "hybrid", "hybrid_reranked"}:
            raise ValueError("Perfil de retrieval desconhecido.")
        if mode != "lexical" and models is None:
            raise Problem(503, "embedding_unavailable", "Ative o perfil privado de modelos.")
        self.context = context
        self.mode = mode
        self.models = models
        self.deadline = time.monotonic() + MAX_TOOL_SECONDS

    def _remaining_seconds(self, connection) -> float:
        # The first admitted call starts a durable budget. Recreating an executor
        # or reacquiring a lease must not provide another two minutes.
        remaining = connection.execute(
            text("""
            SELECT :maximum - coalesce(extract(epoch FROM clock_timestamp()-min(created_at)),0)
            FROM audit_events WHERE tenant_id=:tenant AND resource_id=:run AND action='tool.invoked'
        """),
            {
                "maximum": MAX_TOOL_SECONDS,
                "tenant": self.context.lease.tenant_id,
                "run": self.context.lease.resource_id,
            },
        ).scalar_one()
        if remaining <= 0:
            raise Problem(408, "tool_deadline", "A leitura de evidências excedeu o prazo.")
        return float(remaining)

    def _call(
        self,
        name: str,
        arguments: Arguments,
        operation: Callable[[], T],
        visible: Callable[[T], object] = lambda value: value,
    ) -> T:
        lease = self.context.lease
        digest = hashlib.sha256((name + arguments.model_dump_json()).encode()).hexdigest()
        if time.monotonic() >= self.deadline:
            raise Problem(408, "tool_deadline", "A leitura de evidências excedeu o prazo.")
        with transaction(lease.tenant_id) as connection:
            actor = self.context.authorize(connection)
            self.deadline = min(
                self.deadline, time.monotonic() + self._remaining_seconds(connection)
            )
            calls = list(
                connection.execute(
                    text("""
                SELECT metadata FROM audit_events WHERE tenant_id=:tenant
                AND resource_id=:run AND action='tool.invoked'
            """),
                    {"tenant": lease.tenant_id, "run": lease.resource_id},
                ).scalars()
            )
            if len(calls) >= MAX_TOOL_CALLS:
                raise Problem(
                    429, "tool_call_limit", "A investigação atingiu o limite de leituras."
                )
            if any(
                item.get("fingerprint") == digest and item.get("attempt") == lease.token
                for item in calls
            ):
                raise Problem(
                    409, "tool_repeated", "Uma leitura idêntica foi repetida sem progresso."
                )
            # Admission is committed before execution: failed attempts also consume quota.
            record_action(
                connection,
                actor,
                "tool.invoked",
                lease.resource_id,
                lease.policy_revision,
                {"tool": name, "fingerprint": digest, "attempt": lease.token},
            )
        with TRACER.start_as_current_span(
            "investigation.tool", record_exception=False, set_status_on_exception=False
        ) as span:
            span.set_attribute("ed.tool", name)
            span.set_attribute("ed.fencing_token", lease.token)
            try:
                result = operation()
                output_bytes = len(
                    json.dumps(visible(result), ensure_ascii=False, separators=(",", ":")).encode()
                )
                if time.monotonic() >= self.deadline:
                    raise Problem(408, "tool_deadline", "A leitura de evidências excedeu o prazo.")
                with transaction(lease.tenant_id) as connection:
                    actor = self.context.authorize(connection)
                    self._remaining_seconds(connection)
                    used = connection.execute(
                        text("""
                        SELECT coalesce(sum((metadata->>'output_bytes')::bigint),0)
                        FROM audit_events WHERE tenant_id=:tenant AND resource_id=:run AND action='tool.completed'
                    """),
                        {"tenant": lease.tenant_id, "run": lease.resource_id},
                    ).scalar_one()
                    if used + output_bytes > MAX_OUTPUT_BYTES:
                        raise Problem(
                            422, "tool_output_limit", "As leituras excederam o limite de contexto."
                        )
                    record_action(
                        connection,
                        actor,
                        "tool.completed",
                        lease.resource_id,
                        lease.policy_revision,
                        {"tool": name, "output_bytes": output_bytes, "attempt": lease.token},
                    )
                span.set_attribute("ed.output_bytes", output_bytes)
                return result
            except (Problem, ModelServiceError) as error:
                span.set_status(Status(StatusCode.ERROR))
                span.set_attribute("error.type", error.code)
                if isinstance(error, ModelServiceError):
                    raise Problem(
                        422
                        if error.code in {"model_query_too_long", "evidence_requires_rechunking"}
                        else 503,
                        error.code,
                        "Reduza a pergunta ou importe a fonte dividida em trechos menores."
                        if error.code in {"model_query_too_long", "evidence_requires_rechunking"}
                        else "O serviço privado de modelos está indisponível.",
                        retryable=error.retryable,
                    ) from None
                raise

    def summarize_reconciliation(self) -> ReconciliationResult:
        def read():
            with transaction(self.context.lease.tenant_id) as connection:
                actor = self.context.authorize(connection)
                return load_reconciliation(
                    connection, actor, self.context.incident_id, self.context.snapshot_id
                )

        # Full domain rows stay in trusted application code; only the bounded summary
        # is charged as tool output and later supplied to generation.
        return self._call("summarize_reconciliation", Arguments(), read, reconciliation_summary)

    def search(self, arguments: SearchArguments) -> list[ContextEvidence]:
        def read():
            vector = self.models.encode_query(arguments.query) if self.models else None
            with transaction(self.context.lease.tenant_id) as connection:
                actor = self.context.authorize(connection)
                candidates = search_evidence(
                    connection,
                    actor,
                    self.context.incident_id,
                    self.context.snapshot_id,
                    arguments.query,
                    mode="lexical" if self.mode == "lexical" else "hybrid",
                    limit=20 if self.mode == "hybrid_reranked" else arguments.limit,
                    query_embedding=vector,
                    embedding_revision=EMBEDDING_REVISION if vector else None,
                )
            if self.mode == "hybrid_reranked":
                assert self.models is not None
                return rerank_evidence(
                    arguments.query, candidates, self.models, limit=arguments.limit
                )
            return candidates

        return self._call(
            "search_evidence",
            arguments,
            read,
            lambda rows: [row.model_dump(mode="json") for row in rows],
        )

    def read_span(self, arguments: ReadArguments) -> dict:
        def read():
            with transaction(self.context.lease.tenant_id) as connection:
                actor = self.context.authorize(connection)
                row = resolve_evidence(
                    connection,
                    actor,
                    arguments.evidence_id,
                    self.context.snapshot_id,
                    incident_id=self.context.incident_id,
                )
                original = row["canonical_text"] or ""
                end = min(len(original), arguments.start + arguments.length)
                if arguments.start >= len(original):
                    raise Problem(422, "span_out_of_range", "O intervalo não existe nesta fonte.")
                return {
                    "evidence_id": row["id"],
                    "version": row["version"],
                    "sha256": row["sha256"],
                    "locator": row["locator"],
                    "start": arguments.start,
                    "end": end,
                    "text": original[arguments.start : end],
                    "total_characters": len(original),
                }

        return self._call("read_evidence_span", arguments, read)

    def order_timeline(self, arguments: TimelineArguments) -> dict:
        def read():
            with transaction(self.context.lease.tenant_id) as connection:
                actor = self.context.authorize(connection)
                result = load_reconciliation(
                    connection, actor, self.context.incident_id, self.context.snapshot_id
                )
                rows = [
                    row
                    for row in result.timeline
                    if row.order_reference == arguments.order_reference
                ]
                return {
                    "items": [row.model_dump(mode="json") for row in rows[: arguments.limit]],
                    "total": len(rows),
                    "truncated": len(rows) > arguments.limit,
                    "ordering": result.ordering,
                    "window": result.window.model_dump(mode="json", by_alias=True),
                }

        return self._call("get_order_timeline", arguments, read)

    def compare_revisions(self, arguments: CompareArguments) -> dict:
        def read():
            with transaction(self.context.lease.tenant_id) as connection:
                actor = self.context.authorize(connection)
                rows = [
                    resolve_evidence(connection, actor, identity, self.context.snapshot_id)
                    for identity in (arguments.first_id, arguments.second_id)
                ]
                if any(row["kind"] != "document_span" for row in rows):
                    raise Problem(422, "document_required", "Selecione dois trechos documentais.")
                lineage = [row["record"].get("document_lineage") for row in rows]
                if not lineage[0] or lineage[0] != lineage[1]:
                    raise Problem(
                        422,
                        "unrelated_documents",
                        "As fontes não pertencem à mesma linhagem documental.",
                    )
                return {
                    "same_content": rows[0]["canonical_text"] == rows[1]["canonical_text"],
                    "revisions": [
                        {
                            "evidence_id": row["id"],
                            "version": row["version"],
                            "temporal_role": row["temporal_role"],
                            "valid_from": row["valid_from"].isoformat()
                            if row["valid_from"]
                            else None,
                            "valid_until": row["valid_until"].isoformat()
                            if row["valid_until"]
                            else None,
                            "text": row["canonical_text"],
                        }
                        for row in rows
                    ],
                }

        return self._call("compare_document_revisions", arguments, read)
