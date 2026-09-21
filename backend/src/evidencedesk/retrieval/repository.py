"""PostgreSQL retrieval with authorization before ranking and bounded exact vectors."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Engine, text

from evidencedesk.database import lock_policy
from evidencedesk.errors import Problem
from evidencedesk.evidence.service import authorize_snapshot
from evidencedesk.identity.service import Actor, actor_for_worker, authorize_incident
from evidencedesk.model_runtime.contracts import ContextEvidence

from .lexical import LEXEME_PLAN_SQL
from .local_models import EMBEDDING_REVISION

SearchMode = Literal["lexical", "vector", "hybrid"]
TemporalPurpose = Literal["applicable_procedure", "historical_artifact", "retrospective_context"]

# MATERIALIZED makes the authorized exact candidate set explicit; no ANN index is used.
_AUTHORIZED = """
    WITH authorized AS MATERIALIZED (
        SELECT e.id,e.title,e.kind,e.canonical_text,e.temporal_role,e.valid_from,e.valid_until,
               e.embedding,e.embedding_revision,
               coalesce(e.record->>'document_lineage',e.original_key,e.id) AS document_id,
               e.search_vector
        FROM evidence e
        JOIN snapshot_members sm ON sm.tenant_id=e.tenant_id AND sm.evidence_id=e.id
        JOIN evidence_snapshots es ON es.tenant_id=sm.tenant_id AND es.id=sm.snapshot_id
        JOIN collections c ON c.tenant_id=e.tenant_id AND c.id=e.collection_id
        JOIN collection_grants cg ON cg.tenant_id=c.tenant_id AND cg.collection_id=c.id
        JOIN incidents i ON i.tenant_id=c.tenant_id AND i.collection_id=c.id
        JOIN incident_members im ON im.tenant_id=i.tenant_id AND im.incident_id=i.id
        JOIN users u ON u.tenant_id=cg.tenant_id AND u.id=cg.user_id
        JOIN tenants t ON t.id=u.tenant_id
        WHERE e.tenant_id=:tenant AND sm.snapshot_id=:snapshot AND i.id=:incident
          AND es.collection_id=e.collection_id
          AND cg.user_id=:user AND im.user_id=:user AND u.enabled AND t.enabled
          AND c.tombstoned_at IS NULL AND e.tombstoned_at IS NULL
          AND e.kind='document_span'
          AND (CAST(:purpose AS text) IS NULL OR e.temporal_role=:purpose)
          AND (e.temporal_role <> 'applicable_procedure'
               OR (e.valid_from IS NOT NULL AND e.valid_from < i.window_to
                   AND (e.valid_until IS NULL OR e.valid_until > i.window_from)))
    )
"""


def _vector_literal(vector: Sequence[float]) -> str:
    if len(vector) != 384 or any(not math.isfinite(value) for value in vector):
        raise ValueError("Vetor deve possuir 384 componentes finitos.")
    if not any(value != 0 for value in vector):
        raise ValueError("Vetor nulo não admite distância cosseno.")
    return json.dumps(list(vector), separators=(",", ":"))


def search_evidence(
    connection: Connection,
    actor: Actor,
    incident_id: str,
    snapshot_id: str,
    query: str,
    mode: SearchMode = "lexical",
    limit: int = 8,
    *,
    purpose: TemporalPurpose | None = None,
    query_embedding: Sequence[float] | None = None,
    embedding_revision: str | None = None,
) -> list[ContextEvidence]:
    """Return authorized documentary context; operational facts use reconciliation tools.

    Encode queries before opening this connection. Rerank after closing it, then
    reauthorize source IDs at model dispatch/publication. No model is loaded here.
    """
    if not 1 <= limit <= 20 or not 1 <= len(query.strip()) <= 3000:
        raise ValueError("Consulta ou limite de retrieval inválido.")
    if mode not in {"lexical", "vector", "hybrid"}:
        raise ValueError("Modo de retrieval desconhecido.")
    actor_for_worker(connection, actor.tenant_id, actor.id)
    incident = authorize_incident(connection, actor, incident_id)
    authorize_snapshot(connection, actor, snapshot_id, incident["collection_id"])
    params = {
        "tenant": actor.tenant_id,
        "user": actor.id,
        "incident": incident_id,
        "snapshot": snapshot_id,
        "query": query,
        "purpose": purpose,
    }
    if mode != "lexical":
        if query_embedding is None or embedding_revision is None:
            raise Problem(
                503, "embedding_unavailable", "O perfil de embeddings não está preparado."
            )
        params.update(vector=_vector_literal(query_embedding), revision=embedding_revision)
        counts = (
            connection.execute(
                text(
                    _AUTHORIZED
                    + """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE embedding IS NOT NULL AND embedding_revision=:revision) AS indexed
            FROM authorized
        """
                ),
                params,
            )
            .mappings()
            .one()
        )
        if counts["total"] != counts["indexed"]:
            raise Problem(
                409,
                "embedding_index_incomplete",
                "Este snapshot ainda não possui índice vetorial completo.",
            )
    lexical_rows, vector_rows = [], []
    if mode in {"lexical", "hybrid"}:
        params["lexical_query"] = connection.execute(
            text(LEXEME_PLAN_SQL), {"query": query}
        ).scalar_one()
        lexical_rows = list(
            connection.execute(
                text(
                    _AUTHORIZED
                    + """
            SELECT *,ts_rank_cd(search_vector,to_tsquery('simple',:lexical_query)) AS rank_score
            FROM authorized
            WHERE search_vector @@ to_tsquery('simple',:lexical_query)
            ORDER BY rank_score DESC,id LIMIT 30
        """
                ),
                params,
            ).mappings()
        )
    if mode in {"vector", "hybrid"}:
        vector_rows = list(
            connection.execute(
                text(
                    _AUTHORIZED
                    + """
            SELECT *,1 - (embedding <=> CAST(:vector AS vector)) AS rank_score
            FROM authorized WHERE embedding_revision=:revision AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:vector AS vector),id LIMIT 30
        """
                ),
                params,
            ).mappings()
        )
    records = {row["id"]: row for row in (*lexical_rows, *vector_rows)}
    if mode == "hybrid":
        scores: dict[str, float] = {}
        for ranking in (lexical_rows, vector_rows):
            for rank, row in enumerate(ranking, 1):
                scores[row["id"]] = scores.get(row["id"], 0) + 1 / (60 + rank)
    else:
        ranking = lexical_rows if mode == "lexical" else vector_rows
        scores = {row["id"]: float(row["rank_score"]) for row in ranking}
    ranked_ids = sorted(scores, key=lambda evidence_id: (-scores[evidence_id], evidence_id))
    per_document: Counter[str] = Counter()
    context = []
    used_characters = 0
    for evidence_id in ranked_ids:
        row = records[evidence_id]
        if per_document[row["document_id"]] >= 3:
            continue
        source_text = row["canonical_text"]
        # Preserve exact locators. Large spans require ingestion rechunking, not truncation here.
        if len(source_text) > 12_000:
            raise Problem(
                409,
                "evidence_requires_chunking",
                "Uma fonte precisa ser dividida em trechos antes da investigação.",
            )
        if used_characters + len(source_text) > 24_000:
            continue
        context.append(
            ContextEvidence(
                evidence_id=row["id"],
                title=row["title"],
                text=source_text,
                kind=row["kind"],
                temporal_role=row["temporal_role"],
                valid_from=row["valid_from"],
                valid_until=row["valid_until"],
            )
        )
        used_characters += len(source_text)
        per_document[row["document_id"]] += 1
        if len(context) == limit:
            break
    return context


class PassageEncoder(Protocol):
    batch_size: int
    dimensions: int

    def encode_passages(self, passages: Sequence[str]) -> list[list[float]]: ...


class EvidenceReranker(Protocol):
    def score_passages(self, query: str, passages: Sequence[str]) -> list[float]: ...


def rerank_evidence(
    query: str,
    evidence: Sequence[ContextEvidence],
    reranker: EvidenceReranker,
    *,
    limit: int = 8,
) -> list[ContextEvidence]:
    """Call only after leaving the retrieval transaction; reauthorize before dispatch."""
    if len(evidence) > 20 or not 1 <= limit <= 8:
        raise ValueError("Limites de reranking inválidos.")
    scores = reranker.score_passages(query, [item.text for item in evidence])
    if len(scores) != len(evidence) or any(not math.isfinite(score) for score in scores):
        raise ValueError("Reranker devolveu scores incompatíveis.")
    ranked = sorted(
        zip(scores, evidence, strict=True), key=lambda pair: (-pair[0], pair[1].evidence_id)
    )
    return [item for _, item in ranked[:limit]]


class IndexResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_snapshot_id: str
    embedding_revision: str
    indexed_now: int
    total_documents: int
    complete: bool


def index_snapshot(
    engine: Engine,
    actor: Actor,
    snapshot_id: str,
    encoder: PassageEncoder,
    *,
    embedding_revision: str = EMBEDDING_REVISION,
    guard: Callable[[Connection], None] | None = None,
) -> IndexResult:
    """Index one immutable snapshot without holding the DB pool during inference.

    Current schema stores a single vector revision per span. A different model
    requires a new corpus/evidence version; never overwrite the previous revision.
    Search rejects partially indexed snapshots instead of advertising readiness.
    """
    if encoder.dimensions != 384 or not 1 <= encoder.batch_size <= 32:
        raise ValueError("Configuração do encoder incompatível com o índice.")
    indexed_now = 0
    while True:
        with engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('ed.tenant_id',:tenant,true)"), {"tenant": actor.tenant_id}
            )
            if guard:
                guard(connection)
            actor_for_worker(connection, actor.tenant_id, actor.id)
            snapshot = authorize_snapshot(connection, actor, snapshot_id)
            policy_revision = connection.execute(
                text("SELECT revision FROM tenant_policy WHERE tenant_id=:tenant"),
                {"tenant": actor.tenant_id},
            ).scalar_one()
            rows = list(
                connection.execute(
                    text("""
                SELECT e.id,e.canonical_text,e.sha256,e.embedding_revision
                FROM evidence e
                JOIN snapshot_members sm ON sm.tenant_id=e.tenant_id AND sm.evidence_id=e.id
                JOIN collection_grants cg ON cg.tenant_id=e.tenant_id AND cg.collection_id=e.collection_id
                WHERE e.tenant_id=:tenant AND sm.snapshot_id=:snapshot AND cg.user_id=:user
                  AND e.collection_id=:collection AND e.tombstoned_at IS NULL
                  AND e.kind='document_span'
                  AND (e.embedding IS NULL OR e.embedding_revision IS DISTINCT FROM :revision)
                ORDER BY e.id LIMIT :batch
            """),
                    {
                        "tenant": actor.tenant_id,
                        "snapshot": snapshot_id,
                        "user": actor.id,
                        "collection": snapshot["collection_id"],
                        "revision": embedding_revision,
                        "batch": encoder.batch_size,
                    },
                ).mappings()
            )
        if not rows:
            break
        if any(row["embedding_revision"] not in {None, embedding_revision} for row in rows):
            raise Problem(
                409,
                "embedding_revision_conflict",
                "Crie uma nova versão do corpus para mudar o modelo de embedding.",
            )
        vectors = encoder.encode_passages([row["canonical_text"] for row in rows])
        if len(vectors) != len(rows):
            raise ValueError("Encoder devolveu quantidade de vetores incompatível.")
        encoded = [_vector_literal(vector) for vector in vectors]
        with engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('ed.tenant_id',:tenant,true)"), {"tenant": actor.tenant_id}
            )
            if guard:
                guard(connection)
            current_revision = lock_policy(connection, actor.tenant_id, mutation=True)
            actor_for_worker(connection, actor.tenant_id, actor.id)
            authorize_snapshot(connection, actor, snapshot_id, snapshot["collection_id"])
            if current_revision != policy_revision:
                raise Problem(
                    409, "index_access_changed", "As permissões mudaram durante a indexação."
                )
            for row, vector in zip(rows, encoded, strict=True):
                updated = connection.execute(
                    text("""
                    UPDATE evidence e SET embedding=CAST(:vector AS vector),embedding_revision=:revision
                    WHERE e.tenant_id=:tenant AND e.id=:id AND e.sha256=:sha
                      AND e.collection_id=:collection
                      AND e.canonical_text=:canonical AND e.tombstoned_at IS NULL
                      AND (e.embedding_revision IS NULL OR e.embedding_revision=:revision)
                      AND EXISTS(SELECT 1 FROM snapshot_members sm WHERE sm.tenant_id=e.tenant_id
                                 AND sm.snapshot_id=:snapshot AND sm.evidence_id=e.id)
                    RETURNING e.id
                """),
                    {
                        "tenant": actor.tenant_id,
                        "id": row["id"],
                        "sha": row["sha256"],
                        "canonical": row["canonical_text"],
                        "vector": vector,
                        "revision": embedding_revision,
                        "snapshot": snapshot_id,
                        "collection": snapshot["collection_id"],
                    },
                ).scalar_one_or_none()
                if updated is None:
                    raise Problem(
                        409,
                        "index_source_changed",
                        "Uma fonte mudou ou foi removida durante a indexação.",
                    )
                indexed_now += 1
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('ed.tenant_id',:tenant,true)"), {"tenant": actor.tenant_id}
        )
        if guard:
            guard(connection)
        actor_for_worker(connection, actor.tenant_id, actor.id)
        snapshot = authorize_snapshot(connection, actor, snapshot_id)
        counts = (
            connection.execute(
                text("""
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE e.embedding IS NOT NULL AND e.embedding_revision=:revision) AS indexed
            FROM evidence e JOIN snapshot_members sm ON sm.tenant_id=e.tenant_id AND sm.evidence_id=e.id
            WHERE e.tenant_id=:tenant AND sm.snapshot_id=:snapshot AND e.collection_id=:collection
              AND e.kind='document_span' AND e.tombstoned_at IS NULL
        """),
                {
                    "tenant": actor.tenant_id,
                    "snapshot": snapshot_id,
                    "revision": embedding_revision,
                    "collection": snapshot["collection_id"],
                },
            )
            .mappings()
            .one()
        )
    return IndexResult(
        evidence_snapshot_id=snapshot_id,
        embedding_revision=embedding_revision,
        indexed_now=indexed_now,
        total_documents=counts["total"],
        complete=counts["indexed"] == counts["total"],
    )
