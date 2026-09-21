from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class RetrievalScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: str
    evidence_snapshot_id: str
    purpose: Literal["applicable_procedure", "historical_artifact", "retrospective_context"]
    incident_at: AwareDatetime


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str
    tenant_id: str
    evidence_snapshot_id: str
    document_id: str
    text: str = Field(min_length=1, max_length=12_000)
    temporal_role: Literal["applicable_procedure", "historical_artifact", "retrospective_context"]
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid_interval(self) -> Candidate:
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("Vigência documental inválida.")
        return self


class RankedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate: Candidate
    score: float
    lexical_rank: int | None
    vector_rank: int | None
    reranker_score: float | None = None


def _validate_scope(candidate: Candidate, scope: RetrievalScope) -> None:
    if (
        candidate.tenant_id != scope.tenant_id
        or candidate.evidence_snapshot_id != scope.evidence_snapshot_id
    ):
        raise ValueError("Repository retornou candidato fora do tenant/snapshot autorizado.")


def temporally_eligible(candidate: Candidate, scope: RetrievalScope) -> bool:
    if candidate.temporal_role != scope.purpose:
        return False
    if scope.purpose != "applicable_procedure":
        return True
    return (
        candidate.valid_from is not None
        and candidate.valid_from <= scope.incident_at
        and (candidate.valid_until is None or scope.incident_at < candidate.valid_until)
    )


def fuse_rankings(
    lexical: Sequence[Candidate],
    vector: Sequence[Candidate],
    scope: RetrievalScope,
    *,
    rrf_k: int = 60,
    limit: int = 20,
    per_document: int = 3,
) -> list[RankedEvidence]:
    """Fuse authorized PostgreSQL FTS/exact-vector ranks without interpreting scores as truth.

    Scope checks detect repository mistakes; they cannot replace SQL authorization.
    Temporal eligibility should also be applied in the repository before its LIMIT.
    """
    if rrf_k < 1 or not 1 <= limit <= 30 or not 1 <= per_document <= 10:
        raise ValueError("Configuração de ranking inválida.")
    candidates: dict[str, Candidate] = {}
    ranks: list[dict[str, int]] = []
    for ranking in (lexical, vector):
        if len(ranking) > 30:
            raise ValueError("Cada ranking deve trazer no máximo 30 candidatos.")
        source_ranks: dict[str, int] = {}
        for rank, candidate in enumerate(ranking, 1):
            _validate_scope(candidate, scope)
            prior = candidates.get(candidate.evidence_id)
            if prior and prior != candidate:
                raise ValueError("O mesmo evidence_id aponta para conteúdo diferente.")
            candidates[candidate.evidence_id] = candidate
            if temporally_eligible(candidate, scope):
                source_ranks.setdefault(candidate.evidence_id, rank)
        ranks.append(source_ranks)
    combined = [
        RankedEvidence(
            candidate=candidates[evidence_id],
            score=sum(
                1 / (rrf_k + positions[evidence_id])
                for positions in ranks
                if evidence_id in positions
            ),
            lexical_rank=ranks[0].get(evidence_id),
            vector_rank=ranks[1].get(evidence_id),
        )
        for evidence_id in ranks[0].keys() | ranks[1].keys()
    ]
    combined.sort(key=lambda item: (-item.score, item.candidate.evidence_id))
    counts: Counter[str] = Counter()
    selected = []
    for item in combined:
        if counts[item.candidate.document_id] < per_document:
            selected.append(item)
            counts[item.candidate.document_id] += 1
        if len(selected) == limit:
            break
    return selected


def select_context(
    ranking: Sequence[RankedEvidence], *, max_spans: int = 8, max_characters: int = 24_000
) -> list[RankedEvidence]:
    if not 1 <= max_spans <= 8 or max_characters < 1:
        raise ValueError("Limite de contexto inválido.")
    selected, used = [], 0
    for item in ranking:
        size = len(item.candidate.text)
        if used + size > max_characters:
            continue  # Never silently truncate a span and keep its original locator.
        selected.append(item)
        used += size
        if len(selected) == max_spans:
            break
    return selected
