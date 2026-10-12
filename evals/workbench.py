"""Offline development review. Files declare identities; they do not authenticate them.

The immutable round/event store is separate from production dossier decisions.
Nothing in this module calls a model, a database, or the network.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.metrics import CaseResult, summarize

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
Id = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")]
Sha = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=100_000)]
Label = Literal["supported", "contradicted", "insufficient", "irrelevant"]
Origin = Literal["human_declared", "simulated_test"]
State = Literal["not_run", "failed", "answered", "abstained"]
FLAGS = Literal[
    "unsupported_root_cause",
    "wrong_order_or_period",
    "omitted_decisive_counterevidence",
    "unsupported_financial_action",
]


class WorkbenchError(ValueError):
    """A malformed, changed, incompatible, or conflicting private artifact."""


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", validate_default=True)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def object_hash(value: Any) -> str:
    return digest(canonical(value))


def require_unique(values: list[str], name: str) -> None:
    if len(values) != len(set(values)):
        raise WorkbenchError(f"IDs duplicados: {name}.")


def timestamp(value: str | None) -> None:
    if value is None:
        return
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkbenchError("Data ISO inválida.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WorkbenchError("Data exige fuso explícito.")


def frozen_numbers(value: Any) -> None:
    """Keep frozen JSON interoperable with JSON.stringify without float rounding."""
    if isinstance(value, float):
        raise WorkbenchError("Bundle congelado aceita somente números inteiros.")
    if isinstance(value, int) and abs(value) > 2**53 - 1:
        raise WorkbenchError("Número fora da precisão JSON interoperável.")
    if isinstance(value, dict):
        for item in value.values():
            frozen_numbers(item)
    elif isinstance(value, list):
        for item in value:
            frozen_numbers(item)


def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkbenchError("Chave JSON duplicada.")
        result[key] = value
    return result


def decode(raw: bytes) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=no_duplicate_keys,
            parse_constant=lambda _: (_ for _ in ()).throw(WorkbenchError("Número JSON inválido.")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise WorkbenchError("JSON inválido ou profundo demais.") from exc


def checked_path(root: Path, relative: str, *, exists: bool = True) -> Path:
    """Reject traversal before resolution, and reject symlink/reparse escapes."""
    if "\\" in relative or ":" in relative:
        raise WorkbenchError("Caminho relativo inválido.")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise WorkbenchError("Path traversal recusado.")
    allowed = root.resolve(strict=True)
    resolved = (allowed / candidate).resolve(strict=exists)
    if not resolved.is_relative_to(allowed):
        raise WorkbenchError("Symlink fora da raiz permitida.")
    return resolved


def read_bytes(path: Path, maximum: int = MAX_FILE_BYTES) -> bytes:
    resolved = path.resolve()
    for data_root in ((ROOT / "evals/data").resolve(), (EVALS / "data").resolve()):
        if resolved == data_root / "reserved.jsonl" or resolved.is_relative_to(
            data_root / "sources/reserved"
        ):
            raise WorkbenchError("Conteúdo reservado não pode ser aberto pelo workbench dev.")
    if not path.is_file() or path.stat().st_size > maximum:
        raise WorkbenchError("Arquivo ausente, incompatível ou grande demais.")
    with path.open("rb") as handle:
        raw = handle.read(maximum + 1)
    if len(raw) > maximum:
        raise WorkbenchError("Arquivo grande demais.")
    return raw


def read_json(path: Path) -> Any:
    return decode(read_bytes(path))


def private_destination(path: Path) -> Path:
    """Resolve the target before writing; no filled artifact may enter this Git tree."""
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT.resolve()):
        raise WorkbenchError("Artefatos preenchidos exigem pasta privada externa ao Git.")
    for parent in [resolved, *resolved.parents]:
        if (parent / ".git").exists():
            raise WorkbenchError("Destino de artefatos não pode pertencer a checkout Git.")
    return resolved


def atomic_new(path: Path, raw: bytes) -> None:
    """Publish complete bytes with O_EXCL-equivalent hard link; never overwrite."""
    if len(raw) > MAX_FILE_BYTES:
        raise WorkbenchError("Artefato grande demais; reduza sistemas ou casos planejados.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if read_bytes(path) == raw:
            return
        raise WorkbenchError("Conflito: arquivo existente não será sobrescrito.")
    descriptor, temporary = tempfile.mkstemp(prefix=".workbench-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError as exc:
            if read_bytes(path) != raw:
                raise WorkbenchError("Conflito concorrente; nenhuma anotação sobrescrita.") from exc
    finally:
        temporary_path.unlink(missing_ok=True)


def write_json(path: Path, value: Any) -> None:
    atomic_new(path, canonical(value) + b"\n")


@contextmanager
def round_lock(path: Path) -> Iterator[None]:
    lock = checked_path(path, ".write.lock", exists=False)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise WorkbenchError("Conflito concorrente: rodada em escrita; tente novamente.") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


class Release(StrictModel):
    id: Id
    commit: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")] | None = None
    image_id: Text | None = None
    corpus_sha256: Sha | None = None
    chunk_policy: Text | None = None
    parser_rules_version: Text | None = None
    retrieval_profile: Text | None = None
    encoder_revision: Text | None = None
    reranker_revision: Text | None = None
    generation_deployment_revision: Text | None = None

    @model_validator(mode="after")
    def source_version(self) -> Release:
        if self.commit is None and self.image_id is None:
            raise WorkbenchError("Release exige commit ou imagem identificada.")
        return self


class RoundSpec(StrictModel):
    schema_version: Literal[1] = 1
    status: Literal["not_started"] = "not_started"
    round_id: Id
    purpose: Literal["development_semantic_review"] = "development_semantic_review"
    split: Literal["dev"] = "dev"
    release: Release
    planned_case_ids: Annotated[list[Id], Field(min_length=1, max_length=60)]
    system_codes: Annotated[list[Id], Field(min_length=1, max_length=20)]
    presentation_order: list[Id] = Field(default_factory=list)
    participant_ids: list[Id] = Field(default_factory=list)
    started_at: str | None = None
    completed_at: Literal[None] = None
    paid_calls_authorized: Literal[False] = False
    reserved_dataset_access: Literal[False] = False
    human_gate: Literal["inconclusive"] = "inconclusive"
    promotion: Literal["not_requested"] = "not_requested"

    @model_validator(mode="after")
    def identities(self) -> RoundSpec:
        for name in ("planned_case_ids", "system_codes", "presentation_order", "participant_ids"):
            require_unique(getattr(self, name), name)
        timestamp(self.started_at)
        return self


class Reference(StrictModel):
    source_id: Id
    locator: Text


class Claim(StrictModel):
    claim_id: Id
    exact_claim: Text
    references: list[Reference] = Field(default_factory=list)


class ResponseInput(StrictModel):
    case_id: Id
    system_code: Id
    state: State
    answer: Text | None = None
    claims: list[Claim] = Field(default_factory=list)
    retrieved_ids: list[Id] = Field(default_factory=list)
    failure_reason: Text | None = None
    latency_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    invalid_citations: Annotated[int, Field(ge=0)] = 0
    tenant_leaks: Annotated[int, Field(ge=0)] = 0
    isolation_checked: bool = False
    citations_checked: bool = False

    @model_validator(mode="after")
    def execution(self) -> ResponseInput:
        require_unique([claim.claim_id for claim in self.claims], "claims")
        require_unique(self.retrieved_ids, "retrieved_ids")
        if self.state in {"answered", "abstained"} and self.answer is None:
            raise WorkbenchError("Resposta executada exige texto exato.")
        if self.state == "answered" and not self.claims:
            raise WorkbenchError("Resposta exige alegações identificadas para revisão.")
        if self.answer is not None and any(
            claim.exact_claim not in self.answer for claim in self.claims
        ):
            raise WorkbenchError("Texto exato de alegação deve pertencer à resposta congelada.")
        if self.state in {"not_run", "failed"} and (self.answer is not None or self.claims):
            raise WorkbenchError("Falha/não executado não pode receber resposta inventada.")
        if self.state == "failed" and self.failure_reason is None:
            raise WorkbenchError("Falha exige motivo.")
        return self


class ResponsesInput(StrictModel):
    schema_version: Literal[1] = 1
    responses: list[ResponseInput]


class Source(StrictModel):
    source_id: Id
    sha256: Sha
    text: Text
    title: Text
    kind: Text
    metadata: dict[str, Any]
    locators: Annotated[list[Text], Field(min_length=1)]

    @model_validator(mode="after")
    def integrity(self) -> Source:
        if digest(self.text.encode("utf-8")) != self.sha256:
            raise WorkbenchError("Hash da fonte divergente.")
        require_unique(self.locators, "locators")
        frozen_numbers(self.metadata)
        return self


class ClaimReview(StrictModel):
    claim_id: Id
    exact_claim: Text
    source_id: Id | None = None
    source_sha256: Sha | None = None
    span_or_locator: Text | None = None
    label: Label | None = None
    rationale: Text | None = None


class Annotation(StrictModel):
    response_id: Id
    case_id: Id
    scenario_instance: Id
    system_code: Id
    answer_sha256: Sha
    source_manifest_sha256: Sha
    release_sha256: Sha
    revision: Annotated[int, Field(ge=1)]
    base_annotation_sha256: Sha | None = None
    status: Literal["draft", "submitted"]
    reviewer_id: Id
    reviewed_at: str | None = None
    claims: list[ClaimReview]
    required_facts: list[Text] | None = None
    omitted_facts: list[Text] | None = None
    counterevidence_notes: Text | None = None
    temporal_notes: Text | None = None
    abstention_judgment: Literal["appropriate", "inappropriate", "not_applicable"] | None = None
    numbers_checked: Annotated[int, Field(ge=0)] | None = None
    numbers_matching: Annotated[int, Field(ge=0)] | None = None
    critical_flags: list[FLAGS] = Field(default_factory=list)
    assistance_received: Text | None = None
    elapsed_seconds: Annotated[int, Field(ge=0)] | None = None
    evidence_origin: Origin = "human_declared"

    @model_validator(mode="after")
    def completeness(self) -> Annotation:
        timestamp(self.reviewed_at)
        require_unique([claim.claim_id for claim in self.claims], "claim reviews")
        for name in ("required_facts", "omitted_facts", "critical_flags"):
            values = getattr(self, name)
            if values is not None:
                require_unique(values, name)
        if (self.numbers_checked is None) != (self.numbers_matching is None):
            raise WorkbenchError("Números não avaliados devem permanecer ambos null.")
        if self.numbers_checked is not None and self.numbers_matching is not None:
            if self.numbers_matching > self.numbers_checked:
                raise WorkbenchError("Números concordantes excedem os verificados.")
        if self.status == "submitted":
            if (
                self.reviewed_at is None
                or self.elapsed_seconds is None
                or self.assistance_received is None
            ):
                raise WorkbenchError("Submissão exige data, tempo e declaração de assistência.")
            if any(
                claim.label is None or not (claim.rationale or "").strip() for claim in self.claims
            ):
                raise WorkbenchError("Submissão exige rótulo e motivo de cada alegação.")
        return self


class AnnotationFile(StrictModel):
    schema_version: Literal[1] = 1
    kind: Literal["evidencedesk-annotations"] = "evidencedesk-annotations"
    round_id: Id
    reviewer_id: Id
    bundle_sha256: Sha
    annotations: Annotated[list[Annotation], Field(min_length=1)]

    @model_validator(mode="after")
    def unique(self) -> AnnotationFile:
        require_unique([annotation.response_id for annotation in self.annotations], "annotations")
        if any(annotation.reviewer_id != self.reviewer_id for annotation in self.annotations):
            raise WorkbenchError("Identidade do arquivo e da anotação divergem.")
        return self


class FrozenResponse(StrictModel):
    response_id: Id
    case_id: Id
    scenario_instance: Id
    category: Id
    system_code: Id
    question: Text
    state: State
    answer: Text | None
    answer_sha256: Sha | None
    source_file_sha256: Sha
    source_manifest_sha256: Sha
    claims: list[Claim]
    sources: list[Source]
    context: dict[str, Any]
    annotation_revision: int = 0
    annotation_sha256: Sha | None = None
    annotation: Annotation | None = None

    @model_validator(mode="after")
    def integrity(self) -> FrozenResponse:
        if self.answer_sha256 != (
            digest(self.answer.encode("utf-8")) if self.answer is not None else None
        ):
            raise WorkbenchError("Hash da resposta divergente.")
        require_unique([source.source_id for source in self.sources], "sources")
        require_unique([claim.claim_id for claim in self.claims], "claims")
        manifest = {
            "source_file_sha256": self.source_file_sha256,
            "sources": [source.model_dump(exclude={"text"}) for source in self.sources],
        }
        if self.source_manifest_sha256 != object_hash(manifest):
            raise WorkbenchError("Hash do manifesto de fontes divergente.")
        for claim in self.claims:
            for reference in claim.references:
                source = next(
                    (item for item in self.sources if item.source_id == reference.source_id), None
                )
                if source is None or reference.locator not in source.locators:
                    raise WorkbenchError("Referência/locator fora da fonte congelada.")
        frozen_numbers(self.context)
        return self


class Bundle(StrictModel):
    schema_version: Literal[1] = 1
    kind: Literal["evidencedesk-review-bundle"] = "evidencedesk-review-bundle"
    round_id: Id
    split: Literal["dev"] = "dev"
    reviewer_id: Id
    release: Release
    release_sha256: Sha
    rubric_version: Literal["semantic-review-v1"] = "semantic-review-v1"
    presentation_order: list[Id]
    responses: list[FrozenResponse]
    bundle_sha256: Sha

    @model_validator(mode="after")
    def integrity(self) -> Bundle:
        require_unique([response.response_id for response in self.responses], "responses")
        require_unique(self.presentation_order, "presentation_order")
        if set(self.presentation_order) != {response.response_id for response in self.responses}:
            raise WorkbenchError("Ordem de apresentação não cobre todas as respostas.")
        if self.release_sha256 != object_hash(self.release.model_dump()):
            raise WorkbenchError("Hash da release divergente.")
        if self.bundle_sha256 != object_hash(self.model_dump(exclude={"bundle_sha256"})):
            raise WorkbenchError("Hash do bundle divergente.")
        frozen_numbers(self.model_dump())
        return self


class EvaluatorReference(StrictModel):
    case_id: Id
    answerable: bool
    relevant_grades: dict[str, int]
    required_facts: list[Text]


class FrozenRound(StrictModel):
    schema_version: Literal[1] = 1
    spec: RoundSpec
    package_sha256: Sha
    dev_case_file_sha256: Sha
    responses_input_sha256: Sha
    release_sha256: Sha
    required_categories: list[Id]
    responses: list[FrozenResponse]
    evaluations: list[EvaluatorReference]
    execution: list[ResponseInput]
    inputs: ResponsesInput
    round_sha256: Sha

    @model_validator(mode="after")
    def integrity(self) -> FrozenRound:
        if self.round_sha256 != object_hash(self.model_dump(exclude={"round_sha256"})):
            raise WorkbenchError("Rodada modificada: hash divergente.")
        if self.release_sha256 != object_hash(self.spec.release.model_dump()):
            raise WorkbenchError("Release modificada.")
        if self.responses_input_sha256 != object_hash(self.inputs.model_dump()):
            raise WorkbenchError("Respostas de entrada modificadas.")
        expected = {
            f"{case_id}--{system}"
            for case_id in self.spec.planned_case_ids
            for system in self.spec.system_codes
        }
        require_unique([response.response_id for response in self.responses], "frozen responses")
        if expected != {response.response_id for response in self.responses}:
            raise WorkbenchError("Rodada não conserva todas as respostas planejadas.")
        require_unique([item.case_id for item in self.evaluations], "evaluation references")
        if set(self.spec.planned_case_ids) != {item.case_id for item in self.evaluations}:
            raise WorkbenchError("Referências de avaliação não cobrem a rodada.")
        keys = [(item.case_id, item.system_code) for item in self.execution]
        if (
            len(keys) != len(set(keys))
            or {f"{case}--{system}" for case, system in keys} != expected
        ):
            raise WorkbenchError("Execução não cobre todos os casos/sistemas planejados.")
        execution = {(item.case_id, item.system_code): item for item in self.execution}
        inputs = {(item.case_id, item.system_code): item for item in self.inputs.responses}
        if len(inputs) != len(self.inputs.responses) or not set(inputs) <= set(execution):
            raise WorkbenchError("Inputs duplicados ou fora do planejamento.")
        for response in self.responses:
            item = execution[response.case_id, response.system_code]
            original = inputs.get(
                (response.case_id, response.system_code),
                ResponseInput(
                    case_id=response.case_id, system_code=response.system_code, state="not_run"
                ),
            )
            if item != original:
                raise WorkbenchError("Execução diverge dos inputs congelados.")
            if (
                response.state != item.state
                or response.answer != item.answer
                or response.claims != item.claims
            ):
                raise WorkbenchError("Resposta congelada diverge do registro de execução.")
        return self


def verified_dev() -> tuple[dict[str, dict[str, Any]], str, str]:
    """Read the development package only; never enumerate/read reserved content."""
    package_raw = read_bytes(checked_path(EVALS, "human-review/package.json"))
    package = decode(package_raw)
    if (
        package.get("case_file") != "../data/dev.jsonl"
        or package.get("reserved_content_read") is not False
    ):
        raise WorkbenchError("Pacote incompatível com preparação exclusivamente dev.")
    cases_raw = read_bytes(checked_path(EVALS, "data/dev.jsonl"))
    if digest(cases_raw) != package["case_file_sha256"]:
        raise WorkbenchError("Hash do pacote dev divergente.")
    cases: dict[str, dict[str, Any]] = {}
    index: dict[str, dict[str, Any]] = {}
    for entry in package["index"]:
        identity = entry["case_id"]
        if identity in index:
            raise WorkbenchError("IDs duplicados no índice do pacote.")
        index[identity] = entry
    for line in cases_raw.splitlines():
        case = decode(line)
        identity = case["case_id"]
        if (
            not re.fullmatch(r"evaluation-dev-[0-9]{3}", identity)
            or identity in cases
            or case["split"] != "dev"
        ):
            raise WorkbenchError("Caso duplicado ou fora do pacote dev.")
        if identity not in index or case["source_path"] != f"sources/dev/{identity}.json":
            raise WorkbenchError("Path traversal/fonte fora do pacote dev.")
        entry = index[identity]
        if (
            entry["source_path"] != f"../data/sources/dev/{identity}.json"
            or entry["source_sha256"] != case["source_sha256"]
        ):
            raise WorkbenchError("Índice e manifesto de fonte divergem.")
        raw = read_bytes(checked_path(EVALS, f"data/sources/dev/{identity}.json"), MAX_SOURCE_BYTES)
        if digest(raw) != case["source_sha256"]:
            raise WorkbenchError("Fonte dev modificada: hash divergente.")
        case["_source"] = decode(raw)
        cases[identity] = case
    if set(cases) != set(index) or len(cases) != package["cases"]:
        raise WorkbenchError("Índice de casos incompleto.")
    return cases, digest(package_raw), digest(cases_raw)


def source_material(case: dict[str, Any]) -> tuple[list[Source], dict[str, Any]]:
    data = case["_source"]
    sources = [
        Source(
            source_id=source["evidence_id"],
            text=source["text"],
            sha256=digest(source["text"].encode("utf-8")),
            title=source.get("metadata", {}).get("title", source["evidence_id"]),
            kind=source["kind"],
            metadata={
                "lineage": source["lineage"],
                **source.get("metadata", {}),
                **({"source_record": source["source_record"]} if "source_record" in source else {}),
            },
            locators=[f"/corpus/{position}"],
        )
        for position, source in enumerate(data["corpus"])
    ]
    return sources, {key: data[key] for key in ("coverage", "mappings", "window", "focus_order")}


def prepare(spec: RoundSpec, inputs: ResponsesInput, destination: Path) -> FrozenRound:
    destination = private_destination(destination)
    cases, package_hash, dev_hash = verified_dev()
    if not set(spec.planned_case_ids) <= set(cases):
        raise WorkbenchError("Caso fora do pacote dev.")
    planned = [
        (case_id, system) for case_id in spec.planned_case_ids for system in spec.system_codes
    ]
    indexed = {(item.case_id, item.system_code): item for item in inputs.responses}
    if len(indexed) != len(inputs.responses) or not set(indexed) <= set(planned):
        raise WorkbenchError("Resposta duplicada ou fora da rodada.")
    corpus_hash = object_hash(
        [
            {"case_id": identity, "source_sha256": cases[identity]["source_sha256"]}
            for identity in spec.planned_case_ids
        ]
    )
    if spec.release.corpus_sha256 is not None and spec.release.corpus_sha256 != corpus_hash:
        raise WorkbenchError("Corpus da release diverge das fontes verificadas.")
    release = spec.release.model_copy(update={"corpus_sha256": corpus_hash})
    release_hash = object_hash(release.model_dump())
    frozen: list[FrozenResponse] = []
    execution: list[ResponseInput] = []
    for identity, system in planned:
        case = cases[identity]
        sources, context = source_material(case)
        execution_item = indexed.get(
            (identity, system), ResponseInput(case_id=identity, system_code=system, state="not_run")
        )
        execution.append(execution_item)
        manifest_hash = object_hash(
            {
                "source_file_sha256": case["source_sha256"],
                "sources": [source.model_dump(exclude={"text"}) for source in sources],
            }
        )
        frozen.append(
            FrozenResponse(
                response_id=f"{identity}--{system}",
                case_id=identity,
                scenario_instance=case["scenario_instance"],
                category=case["scenario_family"],
                system_code=system,
                question=case["question"],
                state=execution_item.state,
                answer=execution_item.answer,
                answer_sha256=digest(execution_item.answer.encode("utf-8"))
                if execution_item.answer is not None
                else None,
                source_file_sha256=case["source_sha256"],
                source_manifest_sha256=manifest_hash,
                claims=execution_item.claims,
                sources=sources,
                context=context,
            )
        )
    order = spec.presentation_order or [response.response_id for response in frozen]
    if set(order) != {response.response_id for response in frozen}:
        raise WorkbenchError("Ordem precisa conter cada resposta planejada uma vez.")
    spec = spec.model_copy(update={"release": release, "presentation_order": order})
    value = {
        "schema_version": 1,
        "spec": spec.model_dump(),
        "package_sha256": package_hash,
        "dev_case_file_sha256": dev_hash,
        "responses_input_sha256": object_hash(inputs.model_dump()),
        "release_sha256": release_hash,
        "required_categories": sorted({case["scenario_family"] for case in cases.values()}),
        "responses": [response.model_dump() for response in frozen],
        "evaluations": [
            EvaluatorReference(
                case_id=identity,
                answerable=cases[identity]["answerable"],
                relevant_grades=cases[identity]["expected_evidence_grades"],
                required_facts=cases[identity]["required_facts"],
            ).model_dump()
            for identity in spec.planned_case_ids
        ],
        "execution": [item.model_dump() for item in execution],
        "inputs": inputs.model_dump(),
    }
    round_data = FrozenRound.model_validate({**value, "round_sha256": object_hash(value)})
    destination.mkdir(parents=True, exist_ok=True)
    with round_lock(destination):
        write_json(checked_path(destination, "round.json", exists=False), round_data.model_dump())
    return round_data


def load_round(path: Path) -> FrozenRound:
    path = private_destination(path)
    round_data = FrozenRound.model_validate(read_json(checked_path(path, "round.json")))
    cases, package_hash, dev_hash = verified_dev()
    if round_data.package_sha256 != package_hash or round_data.dev_case_file_sha256 != dev_hash:
        raise WorkbenchError("Pacote/corpus alterado desde o congelamento.")
    if round_data.required_categories != sorted(
        {case["scenario_family"] for case in cases.values()}
    ):
        raise WorkbenchError("Categorias obrigatórias alteradas.")
    corpus_hash = object_hash(
        [
            {"case_id": identity, "source_sha256": cases[identity]["source_sha256"]}
            for identity in round_data.spec.planned_case_ids
        ]
    )
    if round_data.spec.release.corpus_sha256 != corpus_hash:
        raise WorkbenchError("Hash do corpus da release diverge do pacote dev.")
    for response in round_data.responses:
        case = cases[response.case_id]
        if response.source_file_sha256 != case["source_sha256"]:
            raise WorkbenchError("Corpus alterado desde o congelamento.")
        sources, context = source_material(case)
        if response.sources != sources or response.context != context:
            raise WorkbenchError("Fontes/contexto congelados divergem do corpus dev verificado.")
        if (
            response.question != case["question"]
            or response.scenario_instance != case["scenario_instance"]
            or response.category != case["scenario_family"]
        ):
            raise WorkbenchError("Identidade/pergunta do caso diverge do pacote dev.")
    expected_evaluations = [
        EvaluatorReference(
            case_id=identity,
            answerable=cases[identity]["answerable"],
            relevant_grades=cases[identity]["expected_evidence_grades"],
            required_facts=cases[identity]["required_facts"],
        )
        for identity in round_data.spec.planned_case_ids
    ]
    if round_data.evaluations != expected_evaluations:
        raise WorkbenchError("Referências de avaliação divergem do pacote dev.")
    return round_data


def events(path: Path, folder: str) -> list[dict[str, Any]]:
    base = checked_path(path, folder, exists=False)
    if not base.exists():
        return []
    return [
        read_json(checked_path(path, f"{folder}/{entry.name}"))
        for entry in sorted(base.glob("*.json"))
    ]


def review_history(path: Path, round_data: FrozenRound | None = None) -> list[Annotation]:
    result = [Annotation.model_validate(value) for value in events(path, "annotations")]
    round_data = round_data or load_round(path)
    responses = {response.response_id: response for response in round_data.responses}
    keys = [(item.response_id, item.reviewer_id, item.revision) for item in result]
    if len(keys) != len(set(keys)):
        raise WorkbenchError("Store contém revisões duplicadas.")
    previous: dict[tuple[str, str], Annotation] = {}
    for item in sorted(result, key=lambda review: review.revision):
        response = responses.get(item.response_id)
        if response is None:
            raise WorkbenchError("Store contém revisão fora da rodada.")
        validate_annotation(item, response, round_data.release_sha256)
        key = item.response_id, item.reviewer_id
        base = previous.get(key)
        if item.revision != (base.revision + 1 if base else 1):
            raise WorkbenchError("Histórico de revisões não é contíguo.")
        if item.base_annotation_sha256 != (object_hash(base.model_dump()) if base else None):
            raise WorkbenchError("Hash de proveniência do histórico divergente.")
        if base is not None and base.status == "submitted":
            raise WorkbenchError("Histórico alterou submissão imutável.")
        filename = object_hash([item.response_id, item.reviewer_id, item.revision])
        expected_path = checked_path(path, f"annotations/{filename}.json")
        if read_json(expected_path) != item.model_dump():
            raise WorkbenchError("Nome/conteúdo do evento de revisão diverge.")
        previous[key] = item
    for response_id in responses:
        if (
            sum(
                review.status == "submitted"
                for (identity, _), review in previous.items()
                if identity == response_id
            )
            > 2
        ):
            raise WorkbenchError("Mais de dois julgamentos submetidos para uma resposta.")
    return result


def current_reviews(
    path: Path, round_data: FrozenRound | None = None
) -> dict[tuple[str, str], Annotation]:
    latest: dict[tuple[str, str], Annotation] = {}
    for item in review_history(path, round_data):
        key = item.response_id, item.reviewer_id
        if key not in latest or item.revision > latest[key].revision:
            latest[key] = item
    return latest


def bundle_for(path: Path, reviewer_id: str) -> Bundle:
    round_data = load_round(path)
    IdAdapter(reviewer_id)
    latest = current_reviews(path, round_data)
    responses = []
    for response in round_data.responses:
        annotation = latest.get((response.response_id, reviewer_id))
        responses.append(
            response.model_copy(
                update={
                    "annotation_revision": annotation.revision if annotation else 0,
                    "annotation_sha256": object_hash(annotation.model_dump())
                    if annotation
                    else None,
                    "annotation": annotation,
                }
            )
        )
    value = {
        "schema_version": 1,
        "kind": "evidencedesk-review-bundle",
        "round_id": round_data.spec.round_id,
        "split": "dev",
        "reviewer_id": reviewer_id,
        "release": round_data.spec.release.model_dump(),
        "release_sha256": round_data.release_sha256,
        "rubric_version": "semantic-review-v1",
        "presentation_order": round_data.spec.presentation_order,
        "responses": [response.model_dump() for response in responses],
    }
    bundle = Bundle.model_validate({**value, "bundle_sha256": object_hash(value)})
    # Retain every issued hash. Old bundles remain usable for unchanged records only.
    with round_lock(path):
        write_json(
            checked_path(path, f"bundles/{bundle.bundle_sha256}.json", exists=False),
            bundle.model_dump(),
        )
    return bundle


def IdAdapter(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", value):
        raise WorkbenchError("Identificador inválido.")


def validate_annotation(
    annotation: Annotation, response: FrozenResponse, release_hash: str
) -> None:
    for name in (
        "response_id",
        "case_id",
        "scenario_instance",
        "system_code",
        "answer_sha256",
        "source_manifest_sha256",
    ):
        if getattr(annotation, name) != getattr(response, name):
            raise WorkbenchError(f"Anotação dirigida a outra versão: {name}.")
    if annotation.release_sha256 != release_hash or response.state not in {"answered", "abstained"}:
        raise WorkbenchError("Release incompatível ou resposta não executada.")
    if {claim.claim_id for claim in annotation.claims} != {
        claim.claim_id for claim in response.claims
    }:
        raise WorkbenchError("Anotação deve conservar todas as alegações congeladas.")
    original = {claim.claim_id: claim for claim in response.claims}
    sources = {source.source_id: source for source in response.sources}
    for claim in annotation.claims:
        if claim.exact_claim != original[claim.claim_id].exact_claim:
            raise WorkbenchError("Texto de alegação modificado.")
        reference = (claim.source_id, claim.source_sha256, claim.span_or_locator)
        if any(value is not None for value in reference):
            source = sources.get(claim.source_id or "")
            if (
                source is None
                or source.sha256 != claim.source_sha256
                or claim.span_or_locator not in source.locators
            ):
                raise WorkbenchError("Fonte/hash/locator inválido na alegação.")
        if claim.label == "supported" and any(value is None for value in reference):
            raise WorkbenchError("supported exige fonte real, hash e locator válidos.")


def validate_file(
    path: Path, annotation_file: AnnotationFile
) -> tuple[FrozenRound, list[Annotation]]:
    round_data = load_round(path)
    if annotation_file.round_id != round_data.spec.round_id:
        raise WorkbenchError("Anotação fora da rodada.")
    bundle = Bundle.model_validate(
        read_json(checked_path(path, f"bundles/{annotation_file.bundle_sha256}.json"))
    )
    if (
        bundle.reviewer_id != annotation_file.reviewer_id
        or bundle.round_id != annotation_file.round_id
    ):
        raise WorkbenchError("Bundle de outro revisor/rodada.")
    latest = current_reviews(path, round_data)
    adjudicated = {decision["response_id"] for decision in events(path, "adjudications")}
    responses = {response.response_id: response for response in round_data.responses}
    bundle_responses = {response.response_id: response for response in bundle.responses}
    pending = []
    for annotation in annotation_file.annotations:
        response = responses.get(annotation.response_id)
        if response is None:
            raise WorkbenchError("Caso/resposta fora da rodada.")
        validate_annotation(annotation, response, round_data.release_sha256)
        key = annotation.response_id, annotation.reviewer_id
        previous = latest.get(key)
        if previous is not None and annotation.model_dump() == previous.model_dump():
            continue  # Exact retransmission is safe even after adjudication.
        if annotation.response_id in adjudicated:
            raise WorkbenchError("Resposta adjudicada é imutável.")
        if previous is not None and previous.status == "submitted":
            raise WorkbenchError("Submissão é imutável; nova resposta exige nova rodada.")
        if annotation.revision != (previous.revision + 1 if previous else 1):
            raise WorkbenchError("Conflito de revisão concorrente.")
        previous_hash = object_hash(previous.model_dump()) if previous else None
        if annotation.base_annotation_sha256 != previous_hash:
            raise WorkbenchError("Conflito: base da anotação desatualizada.")
        frozen = bundle_responses[annotation.response_id]
        if frozen.annotation_sha256 != previous_hash or frozen.annotation_revision != (
            previous.revision if previous else 0
        ):
            raise WorkbenchError("Bundle desatualizado para essa anotação.")
        other_submitted = [
            review
            for (response_id, reviewer), review in latest.items()
            if response_id == annotation.response_id
            and reviewer != annotation.reviewer_id
            and review.status == "submitted"
        ]
        if annotation.status == "submitted" and len(other_submitted) >= 2:
            raise WorkbenchError(
                "A rodada já tem os dois julgamentos independentes dessa resposta."
            )
        pending.append(annotation)
    return round_data, pending


def import_annotations(path: Path, annotation_file: AnnotationFile) -> dict[str, Any]:
    path = private_destination(path)
    with round_lock(path):
        _, pending = validate_file(path, annotation_file)
        for annotation in pending:
            # Hash names remove any filename interpretation of declared IDs.
            name = object_hash(
                [annotation.response_id, annotation.reviewer_id, annotation.revision]
            )
            write_json(
                checked_path(path, f"annotations/{name}.json", exists=False),
                annotation.model_dump(),
            )
    return {"imported": len(pending), "idempotent": not pending}


def review_signature(annotation: Annotation) -> dict[str, Any]:
    return {
        "claims": {
            claim.claim_id: claim.model_dump(exclude={"rationale", "exact_claim"})
            for claim in annotation.claims
        },
        **{
            name: getattr(annotation, name)
            for name in (
                "required_facts",
                "omitted_facts",
                "abstention_judgment",
                "numbers_checked",
                "numbers_matching",
                "critical_flags",
                "counterevidence_notes",
                "temporal_notes",
            )
        },
    }


def compare(
    path: Path,
    round_data: FrozenRound | None = None,
    latest: dict[tuple[str, str], Annotation] | None = None,
) -> dict[str, Any]:
    round_data = round_data or load_round(path)
    latest = latest if latest is not None else current_reviews(path, round_data)
    rows = []
    for response in round_data.responses:
        submitted = sorted(
            [
                review
                for (response_id, _), review in latest.items()
                if response_id == response.response_id and review.status == "submitted"
            ],
            key=lambda review: review.reviewer_id,
        )
        signatures = [review_signature(review) for review in submitted]
        disagreements = (
            [name for name in signatures[0] if signatures[0][name] != signatures[1][name]]
            if len(signatures) == 2
            else []
        )
        rows.append(
            {
                "response_id": response.response_id,
                "case_id": response.case_id,
                "system_code": response.system_code,
                "submitted_reviews": len(submitted),
                "reviewer_ids": [review.reviewer_id for review in submitted],
                "review_sha256s": [object_hash(review.model_dump()) for review in submitted],
                "disagreements": disagreements,
                "ready_for_adjudication": len(submitted) == 2,
                "submitted_judgments": [review.model_dump() for review in submitted]
                if len(submitted) == 2
                else None,
            }
        )
    return {"round_id": round_data.spec.round_id, "responses": rows}


class Adjudication(StrictModel):
    schema_version: Literal[1] = 1
    kind: Literal["evidencedesk-adjudication"] = "evidencedesk-adjudication"
    round_id: Id
    response_id: Id
    adjudicator_id: Id
    adjudicated_at: str
    review_sha256s: Annotated[list[Sha], Field(min_length=2, max_length=2)]
    disagreements: list[Text]
    final_rationale: Text
    assistance_received: Text
    elapsed_seconds: Annotated[int, Field(ge=0)]
    evidence_origin: Origin = "human_declared"
    final_review: Annotation

    @model_validator(mode="after")
    def provenance(self) -> Adjudication:
        timestamp(self.adjudicated_at)
        require_unique(self.review_sha256s, "provenance reviews")
        if not self.final_rationale.strip():
            raise WorkbenchError("Adjudicação exige motivo explícito.")
        if (
            self.final_review.reviewer_id != self.adjudicator_id
            or self.final_review.status != "submitted"
        ):
            raise WorkbenchError("Decisão final exige adjudicador e revisão completa.")
        if self.final_review.evidence_origin != self.evidence_origin:
            raise WorkbenchError("Origem humana/simulada divergente.")
        return self


def validate_adjudication(
    path: Path,
    round_data: FrozenRound,
    decision: Adjudication,
    latest: dict[tuple[str, str], Annotation] | None = None,
) -> None:
    if decision.round_id != round_data.spec.round_id:
        raise WorkbenchError("Adjudicação fora da rodada.")
    response = next(
        (item for item in round_data.responses if item.response_id == decision.response_id),
        None,
    )
    if response is None:
        raise WorkbenchError("Adjudicação fora da resposta.")
    validate_annotation(decision.final_review, response, round_data.release_sha256)
    latest = latest if latest is not None else current_reviews(path, round_data)
    reviews = [
        item
        for (response_id, _), item in latest.items()
        if response_id == decision.response_id and item.status == "submitted"
    ]
    if len(reviews) != 2 or decision.adjudicator_id in {review.reviewer_id for review in reviews}:
        raise WorkbenchError("Exige dois revisores e adjudicador distinto de ambos.")
    if set(decision.review_sha256s) != {object_hash(review.model_dump()) for review in reviews}:
        raise WorkbenchError("Proveniência das revisões modificada.")
    row = next(
        item
        for item in compare(path, round_data, latest)["responses"]
        if item["response_id"] == decision.response_id
    )
    if decision.disagreements != row["disagreements"]:
        raise WorkbenchError("Decisão deve registrar todas as divergências atuais.")
    if (
        any(review.evidence_origin == "simulated_test" for review in reviews)
        and decision.evidence_origin != "simulated_test"
    ):
        raise WorkbenchError("Simulação não pode virar gate humano real.")
    if decision.final_review.response_id != decision.response_id:
        raise WorkbenchError("Decisão e revisão final se referem a respostas diferentes.")


def adjudicate(path: Path, decision: Adjudication) -> dict[str, Any]:
    path = private_destination(path)
    with round_lock(path):
        round_data = load_round(path)
        validate_adjudication(path, round_data, decision)
        destination = checked_path(
            path, f"adjudications/{object_hash(decision.response_id)}.json", exists=False
        )
        write_json(destination, decision.model_dump())
    return {
        "adjudicated": decision.response_id,
        "human_declared": decision.evidence_origin == "human_declared",
    }


def adjudication_template(path: Path, response_id: str, adjudicator_id: str) -> dict[str, Any]:
    round_data = load_round(path)
    latest = current_reviews(path, round_data)
    IdAdapter(adjudicator_id)
    row = next(
        (
            item
            for item in compare(path, round_data, latest)["responses"]
            if item["response_id"] == response_id
        ),
        None,
    )
    if row is None or not row["ready_for_adjudication"] or adjudicator_id in row["reviewer_ids"]:
        raise WorkbenchError("Adjudicador distinto exige duas submissões prévias.")
    reviews = [
        item
        for (identity, _), item in latest.items()
        if identity == response_id and item.status == "submitted"
    ]
    final = reviews[0].model_dump()
    final.update(
        reviewer_id=adjudicator_id,
        revision=1,
        base_annotation_sha256=None,
        reviewed_at=None,
        elapsed_seconds=None,
        assistance_received=None,
        required_facts=None,
        omitted_facts=None,
        counterevidence_notes=None,
        temporal_notes=None,
        abstention_judgment=None,
        numbers_checked=None,
        numbers_matching=None,
        critical_flags=[],
        evidence_origin="simulated_test"
        if any(review.evidence_origin == "simulated_test" for review in reviews)
        else "human_declared",
    )
    for claim in final["claims"]:
        claim.update(
            label=None, rationale=None, source_id=None, source_sha256=None, span_or_locator=None
        )
    # This template intentionally fails validation until the adjudicator fills it.
    return {
        "schema_version": 1,
        "kind": "evidencedesk-adjudication",
        "round_id": round_data.spec.round_id,
        "response_id": response_id,
        "adjudicator_id": adjudicator_id,
        "adjudicated_at": None,
        "review_sha256s": row["review_sha256s"],
        "disagreements": row["disagreements"],
        "final_rationale": None,
        "assistance_received": None,
        "elapsed_seconds": None,
        "evidence_origin": "simulated_test"
        if any(review.evidence_origin == "simulated_test" for review in reviews)
        else "human_declared",
        "final_review": final,
    }


def report(path: Path) -> dict[str, Any]:
    round_data = load_round(path)
    latest = current_reviews(path, round_data)
    decisions: dict[str, Adjudication] = {}
    for item in events(path, "adjudications"):
        record = Adjudication.model_validate(item)
        if record.response_id in decisions:
            raise WorkbenchError("Store contém adjudicação duplicada.")
        validate_adjudication(path, round_data, record, latest)
        expected_path = checked_path(path, f"adjudications/{object_hash(record.response_id)}.json")
        if read_json(expected_path) != record.model_dump():
            raise WorkbenchError("Nome/conteúdo do evento de adjudicação diverge.")
        decisions[record.response_id] = record
    comparison = compare(path, round_data, latest)
    references = {item.case_id: item for item in round_data.evaluations}
    execution = {(item.case_id, item.system_code): item for item in round_data.execution}
    systems: dict[str, Any] = {}
    case_rows = []
    for system in round_data.spec.system_codes:
        results = []
        for response in round_data.responses:
            if response.system_code != system:
                continue
            reference = references[response.case_id]
            executed = execution[response.case_id, system]
            decision = decisions.get(response.response_id)
            human = decision is not None and decision.evidence_origin == "human_declared"
            final = decision.final_review if human and decision else None
            # Null dimensions remain null in case rows; CaseResult receives a
            # value only for dimensions explicitly reviewed by a real person.
            results.append(
                CaseResult(
                    case_id=response.case_id,
                    scenario_instance=response.scenario_instance,
                    category=response.category,
                    state=response.state,
                    answerable=reference.answerable,
                    relevant_grades=reference.relevant_grades,
                    retrieved_ids=tuple(executed.retrieved_ids),
                    human_support_labels=tuple(claim.label == "supported" for claim in final.claims)
                    if final
                    else None,
                    required_facts=len(reference.required_facts)
                    if final and final.required_facts is not None
                    else 0,
                    covered_facts=len(
                        set(final.required_facts or []) & set(reference.required_facts)
                    )
                    if final
                    else 0,
                    human_adjudicated=human,
                    invalid_citations=executed.invalid_citations,
                    tenant_leaks=executed.tenant_leaks,
                    isolation_checked=executed.isolation_checked,
                    citations_checked=executed.citations_checked,
                    deterministic_numbers_checked=final.numbers_checked or 0 if final else 0,
                    deterministic_numbers_matching=final.numbers_matching or 0 if final else 0,
                    latency_ms=executed.latency_ms,
                )
            )
            row = next(
                item
                for item in comparison["responses"]
                if item["response_id"] == response.response_id
            )
            case_rows.append(
                {
                    **row,
                    "category": response.category,
                    "state": response.state,
                    "human_adjudicated": human,
                    "adjudication_recorded": decision is not None,
                    "adjudicator_id": decision.adjudicator_id if decision else None,
                    "adjudication_origin": decision.evidence_origin if decision else None,
                    "final_rationale": decision.final_rationale if decision else None,
                    "claim_labels": [claim.label for claim in final.claims] if final else None,
                    "required_facts": final.required_facts if final else None,
                    "numbers_checked": final.numbers_checked if final else None,
                    "numbers_matching": final.numbers_matching if final else None,
                }
            )
        categories = set(round_data.required_categories)

        def summarize_assessed(
            rows: list[CaseResult], category_set: set[str], system_code: str
        ) -> dict[str, Any]:
            value = summarize(rows, required_categories=category_set)
            # Apply null safeguards to system and category denominators alike.
            for attribute, gate_name in (
                ("required_facts", "useful_coverage"),
                ("numbers_checked", "deterministic_numbers"),
            ):
                if any(
                    item.human_adjudicated
                    and getattr(decisions[f"{item.case_id}--{system_code}"].final_review, attribute)
                    is None
                    for item in rows
                ):
                    value["gates"][gate_name] = "inconclusive"
            return value

        summary = summarize_assessed(results, categories, system)
        systems[system] = {
            "summary": summary,
            "categories": {
                category: summarize_assessed(
                    [item for item in results if item.category == category], categories, system
                )
                for category in sorted(categories)
            },
        }
    reviewable = {
        item.response_id for item in round_data.responses if item.state in {"answered", "abstained"}
    }
    all_adjudicated = bool(reviewable) and reviewable <= set(decisions)
    fully_executed = all(item.state in {"answered", "abstained"} for item in round_data.responses)
    submitted = sum(item["submitted_reviews"] for item in comparison["responses"])
    state = "prepared"
    if submitted or latest:
        state = "in_review"
    if any(
        item["disagreements"] and item["response_id"] not in decisions
        for item in comparison["responses"]
    ):
        state = "with_disagreements"
    if all_adjudicated:
        state = "completed" if fully_executed else "adjudicated"
    return {
        "schema_version": 1,
        "round_id": round_data.spec.round_id,
        "round_sha256": round_data.round_sha256,
        "release_sha256": round_data.release_sha256,
        "state": state,
        "systems": systems,
        "cases": case_rows,
        "human_gate": "inconclusive"
        if any(
            summary["summary"]["gates"][gate_name] == "inconclusive"
            for summary in systems.values()
            for gate_name in ("human_support", "useful_coverage", "deterministic_numbers")
        )
        else "evaluated",
        "identity_assurance": "declared_file_identity_not_institutional_authentication",
        "reserved_dataset_access": False,
        "paid_calls": 0,
        "promotion": "not_requested",
    }


def report_html(value: dict[str, Any]) -> bytes:
    safe = html.escape(json.dumps(value, ensure_ascii=False, indent=2))
    return (
        "<!doctype html><html lang='pt-BR'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'; connect-src 'none'\">"
        "<title>Relatório de revisão EvidenceDesk</title><style>body{font:1rem system-ui;max-width:80rem;margin:auto;padding:1rem}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}h1{font-size:1.6rem}</style><h1>Revisão de laboratório</h1>"
        "<p>Identidades declaradas em arquivos. Preenchimento e adjudicação não aprovam dossiês de produção.</p>"
        f"<pre>{safe}</pre></html>"
    ).encode()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--round-spec", type=Path, required=True)
    prepare_parser.add_argument("--responses", type=Path, required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    for name in (
        "bundle",
        "validate",
        "import",
        "compare",
        "adjudication-template",
        "adjudicate",
        "report",
    ):
        command = commands.add_parser(name)
        command.add_argument("--round", type=Path, required=True)
        if name == "bundle":
            command.add_argument("--reviewer", required=True)
        if name in {"validate", "import"}:
            command.add_argument("--annotations", type=Path, required=True)
        if name == "adjudicate":
            command.add_argument("--decision", type=Path, required=True)
        if name == "adjudication-template":
            command.add_argument("--response", required=True)
            command.add_argument("--adjudicator", required=True)
        if name in {"bundle", "adjudication-template", "report"}:
            command.add_argument("--output", type=Path, required=name != "report")
    ui_parser = commands.add_parser("ui")
    ui_parser.add_argument("--output", type=Path, required=True)
    schema_parser = commands.add_parser("schema")
    schema_parser.add_argument(
        "--kind",
        choices=["round-spec", "responses", "bundle", "annotations", "adjudication"],
        required=True,
    )
    schema_parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "prepare":
            value = prepare(
                RoundSpec.model_validate(read_json(arguments.round_spec)),
                ResponsesInput.model_validate(read_json(arguments.responses)),
                arguments.output,
            )
            result: Any = {
                "round_id": value.spec.round_id,
                "round_sha256": value.round_sha256,
                "state": "prepared",
            }
        elif arguments.command == "bundle":
            value_bundle = bundle_for(arguments.round, arguments.reviewer)
            write_json(private_destination(arguments.output), value_bundle.model_dump())
            result = {
                "bundle_sha256": value_bundle.bundle_sha256,
                "reviewer_id": arguments.reviewer,
            }
        elif arguments.command in {"validate", "import"}:
            annotation_file = AnnotationFile.model_validate(read_json(arguments.annotations))
            if arguments.command == "import":
                result = import_annotations(arguments.round, annotation_file)
            else:
                _, pending = validate_file(arguments.round, annotation_file)
                result = {"valid": True, "pending": len(pending)}
        elif arguments.command == "compare":
            result = compare(arguments.round)
        elif arguments.command == "adjudication-template":
            result = adjudication_template(
                arguments.round, arguments.response, arguments.adjudicator
            )
            write_json(private_destination(arguments.output), result)
        elif arguments.command == "adjudicate":
            result = adjudicate(
                arguments.round, Adjudication.model_validate(read_json(arguments.decision))
            )
        elif arguments.command == "report":
            result = report(arguments.round)
            if arguments.output:
                target = private_destination(arguments.output)
                atomic_new(
                    target, report_html(result)
                ) if target.suffix.lower() == ".html" else write_json(target, result)
        elif arguments.command == "schema":
            models: dict[str, type[BaseModel]] = {
                "round-spec": RoundSpec,
                "responses": ResponsesInput,
                "bundle": Bundle,
                "annotations": AnnotationFile,
                "adjudication": Adjudication,
            }
            result = models[arguments.kind].model_json_schema()
            if arguments.output:
                write_json(private_destination(arguments.output), result)
        else:
            target = private_destination(arguments.output)
            atomic_new(target, read_bytes(EVALS / "workbench.html"))
            result = {"ui": str(target)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (WorkbenchError, ValidationError, OSError, KeyError, TypeError) as exc:
        # Never echo source/annotation contents from Pydantic error messages.
        error = (
            str(exc)
            if isinstance(exc, WorkbenchError)
            else "Arquivo/contrato incompatível; confira schema, versão e caminhos."
        )
        print(json.dumps({"error": error}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
