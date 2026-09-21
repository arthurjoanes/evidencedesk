"""Frozen generation identity and auditable conservative admission estimates."""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from evidencedesk.config import Settings
from evidencedesk.errors import Problem
from evidencedesk.retrieval.lexical import LEXICAL_REVISION
from evidencedesk.retrieval.local_models import EMBEDDING_REVISION, RERANKER_REVISION

from .azure import SYSTEM_INSTRUCTIONS, response_payload, response_schema_sha256
from .contracts import ContextEvidence, GenerationRequest

ALLOWED_AZURE_HOSTS = frozenset({"agentes-sol-foundry.openai.azure.com"})
ESTIMATION_METHOD = "utf8-envelope-bytes-plus-512-v1"


def validate_azure_base_url(value: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("Porta do endpoint Azure inválida.") from None
    if (
        any(ord(character) < 32 for character in value)
        or value != value.strip()
        or parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_AZURE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path.rstrip("/") != "/openai/v1"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Endpoint Azure fora da allowlist HTTPS de inferência.")
    return f"https://{parsed.hostname}/openai/v1/"


class RuntimeLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_input_tokens: int = Field(ge=1024, le=100_000)
    max_output_tokens: int = Field(ge=128, le=8000)
    max_generation_calls: int = Field(default=4, ge=1, le=4)
    connect_timeout_seconds: int = Field(default=10, ge=1, le=30)
    read_timeout_seconds: int = Field(default=80, ge=10, le=120)
    total_timeout_seconds: int = Field(default=90, ge=10, le=150)


class FrozenModelRelease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str = "azure-synthesis-v2"
    provider: str = "azure_openai"
    deployment: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    base_url: str
    instructions: str = Field(min_length=1, max_length=20_000)
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    estimation_method: str = ESTIMATION_METHOD
    retrieval: str = LEXICAL_REVISION
    retrieval_profile: Literal["lexical", "hybrid", "hybrid_reranked"] = "lexical"
    embedding_revision: str | None = None
    reranker_revision: str | None = None
    store: bool = False
    background: bool = False
    limits: RuntimeLimits

    @model_validator(mode="after")
    def immutable_contract(self) -> FrozenModelRelease:
        validate_azure_base_url(self.base_url)
        if hashlib.sha256(self.instructions.encode()).hexdigest() != self.prompt_sha256:
            raise ValueError("Hash de prompt inconsistente.")
        if (
            self.version != "azure-synthesis-v2"
            or self.estimation_method != ESTIMATION_METHOD
            or self.provider != "azure_openai"
            or self.retrieval != LEXICAL_REVISION
        ):
            raise ValueError("Versão de runtime incompatível.")
        if self.store or self.background:
            raise ValueError("O runtime requer persistência local e execução própria.")
        expected_embedding = None if self.retrieval_profile == "lexical" else EMBEDDING_REVISION
        expected_reranker = (
            RERANKER_REVISION if self.retrieval_profile == "hybrid_reranked" else None
        )
        if (
            self.embedding_revision != expected_embedding
            or self.reranker_revision != expected_reranker
        ):
            raise ValueError("Revisões de retrieval incompatíveis com o perfil congelado.")
        return self


def freeze_release(settings: Settings) -> FrozenModelRelease:
    try:
        return FrozenModelRelease(
            deployment=settings.azure_openai_deployment,
            base_url=validate_azure_base_url(settings.azure_openai_base_url),
            instructions=SYSTEM_INSTRUCTIONS,
            prompt_sha256=hashlib.sha256(SYSTEM_INSTRUCTIONS.encode()).hexdigest(),
            schema_sha256=response_schema_sha256(),
            retrieval_profile=settings.retrieval_mode,
            embedding_revision=EMBEDDING_REVISION if settings.retrieval_mode != "lexical" else None,
            reranker_revision=RERANKER_REVISION
            if settings.retrieval_mode == "hybrid_reranked"
            else None,
            limits=RuntimeLimits(
                max_input_tokens=settings.ai_max_input_tokens,
                max_output_tokens=settings.ai_max_output_tokens,
            ),
        )
    except ValueError:
        raise Problem(
            503, "generator_configuration", "A configuração segura do gerador precisa ser revisada."
        ) from None


def load_release(value: dict) -> FrozenModelRelease:
    try:
        release = FrozenModelRelease.model_validate(value)
    except (ValidationError, ValueError):
        raise Problem(
            409, "model_release_incompatible", "A configuração desta execução precisa ser recriada."
        ) from None
    if release.schema_sha256 != response_schema_sha256():
        raise Problem(
            409, "model_schema_changed", "O contrato de saída mudou; crie uma nova investigação."
        )
    return release


def estimate_input_tokens(request: GenerationRequest, release: FrozenModelRelease) -> int:
    """Conservative estimate, NOT the deployment's exact tokenizer.

    It counts UTF-8 bytes of the complete serialized API body, including system
    instructions, messages, structured schema and framing, plus a fixed allowance.
    Returned usage is authoritative and can differ; any excess remains accounted.
    """
    payload = response_payload(request, release.deployment, release.instructions)
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 512


def bounded_request(
    question: str,
    snapshot_id: str,
    sources: list[ContextEvidence],
    release: FrozenModelRelease,
) -> tuple[GenerationRequest, int]:
    if not sources or sources[0].kind != "reconciliation_result":
        raise Problem(
            422,
            "reconciliation_context_required",
            "A investigação exige conciliação determinística.",
        )
    retained = list(sources)
    while retained:
        if len(retained) > 24 or sum(len(item.text) for item in retained) > 32_000:
            if len(retained) == 1:
                break
            retained.pop()
            continue
        request = GenerationRequest(
            question=question,
            evidence_snapshot_id=snapshot_id,
            evidence=tuple(retained),
            max_output_tokens=release.limits.max_output_tokens,
        )
        estimate = estimate_input_tokens(request, release)
        if estimate <= release.limits.max_input_tokens:
            return request, estimate
        if len(retained) == 1:
            break
        retained.pop()  # Keep whole source spans and the mandatory deterministic aggregate.
    raise Problem(
        422,
        "input_budget_exceeded",
        "O recorte mínimo excede o orçamento de entrada. Reduza a pergunta ou o incidente.",
    )
