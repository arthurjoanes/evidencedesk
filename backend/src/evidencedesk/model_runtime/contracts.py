from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Outcome = Literal[
    "evidence_found", "conflicting_evidence", "insufficient_evidence", "unsupported_scope"
]
ShortText = Annotated[str, Field(min_length=1, max_length=1000)]
Identifier = Annotated[str, Field(min_length=1, max_length=200)]


class EvidenceLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(min_length=1, max_length=200)
    relation: Literal["supports", "contradicts", "context"]


class ClaimInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str | None = Field(default=None, min_length=1, max_length=200)
    kind: Literal["observed_fact", "hypothesis"]
    text: str = Field(min_length=1, max_length=3000)
    order_references: list[Identifier] = Field(default_factory=list, max_length=30)
    evidence_links: list[EvidenceLink] = Field(min_length=1, max_length=20)
    support_status: Literal["pending_review", "contested", "reviewed"] = "pending_review"
    missing_information: list[ShortText] = Field(default_factory=list, max_length=20)
    suggested_checks: list[ShortText] = Field(default_factory=list, max_length=20)


class GeneratedDossier(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=6000)
    claims: list[ClaimInput] = Field(default_factory=list, max_length=30)
    outcome: Outcome
    missing_information: list[ShortText] = Field(default_factory=list, max_length=20)
    suggested_checks: list[ShortText] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def meaningful_outcome(self) -> GeneratedDossier:
        if self.outcome in {"evidence_found", "conflicting_evidence"} and not self.claims:
            raise ValueError("Uma conclusão com evidência exige alegações citadas.")
        return self


class ContextEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=12_000)
    kind: Literal[
        "document_span",
        "source_event",
        "delivery_attempt",
        "order_snapshot",
        "reconciliation_result",
    ]
    temporal_role: Literal["applicable_procedure", "historical_artifact", "retrospective_context"]
    title: str = Field(min_length=1, max_length=300)
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    question: str = Field(min_length=1, max_length=3000)
    evidence_snapshot_id: str
    evidence: tuple[ContextEvidence, ...] = Field(max_length=24)
    max_output_tokens: int = Field(default=2400, ge=128, le=8000)
    context_char_limit: int = Field(default=32_000, ge=1000, le=100_000)

    @model_validator(mode="after")
    def unique_bounded_evidence(self) -> GenerationRequest:
        ids = [evidence.evidence_id for evidence in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("Contexto contém evidence_id duplicado.")
        if sum(len(evidence.text) for evidence in self.evidence) > self.context_char_limit:
            raise ValueError("Contexto excede o limite declarado.")
        return self


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["reported", "estimated", "unknown"]
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)


class GenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dossier: GeneratedDossier
    deployment: str
    returned_model: str | None
    response_id: str | None
    request_id: str | None
    status: Literal["completed"] = "completed"
    latency_ms: float = Field(ge=0)
    usage: TokenUsage
    input_token_estimate: int | None = Field(default=None, ge=0)
    input_estimation_method: str | None = None


class ModelFailure(Exception):
    """Safe operational information; never carries prompts or the raw SDK body."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        usage_status: Literal["reported", "estimated", "unknown"] = "unknown",
        retry_after_seconds: float | None = None,
        response_id: str | None = None,
        request_id: str | None = None,
        usage: TokenUsage | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.usage_status = usage_status
        self.retry_after_seconds = retry_after_seconds
        self.response_id = response_id
        self.request_id = request_id
        self.usage = usage


def validate_generated_dossier(
    dossier: GeneratedDossier, evidence_ids: set[str]
) -> GeneratedDossier:
    """Structural/reference validation; semantic support still needs human review."""
    for claim in dossier.claims:
        if claim.claim_id is not None or claim.support_status != "pending_review":
            raise ModelFailure(
                "invalid_claim_authority", "A IA não pode atribuir identidade ou revisão humana."
            )
        if any(link.evidence_id not in evidence_ids for link in claim.evidence_links):
            raise ModelFailure(
                "invalid_citation", "A resposta contém referência fora do contexto autorizado."
            )
        pairs = [(link.evidence_id, link.relation) for link in claim.evidence_links]
        if len(pairs) != len(set(pairs)):
            raise ModelFailure("duplicate_citation", "A resposta contém referência repetida.")
    return dossier
