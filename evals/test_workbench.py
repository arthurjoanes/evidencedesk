"""Synthetic review simulations test the workflow; they never establish a human gate."""

from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals import workbench as wb

SIMULATION = "simulated_test"
CASE = "evaluation-dev-000"
RESPONSE = f"{CASE}--A"
WHEN = "2026-10-12T13:00:00-03:00"


def spec(*, cases: list[str] | None = None, systems: list[str] | None = None) -> wb.RoundSpec:
    template = wb.read_json(wb.EVALS / "human-review/round.template.json")
    template.update(
        round_id="test-simulation", planned_case_ids=cases or [CASE], system_codes=systems or ["A"]
    )
    template["release"].update(
        id="test-release",
        commit="7" * 40,
        chunk_policy="utf8-bytes-352-v2",
        parser_rules_version="text-pdf-v2",
        retrieval_profile="lexical",
    )
    return wb.RoundSpec.model_validate(template)


def response(case_id: str = CASE, system: str = "A", *, state: str = "answered") -> dict:
    answer = "Mensagens repetidas representam reentrega; não demonstram cobrança duplicada."
    return {
        "case_id": case_id,
        "system_code": system,
        "state": state,
        "answer": answer,
        "claims": [{"claim_id": "claim-1", "exact_claim": answer, "references": []}],
    }


def make_round(
    path: Path, *, round_spec: wb.RoundSpec | None = None, responses: list[dict] | None = None
) -> wb.FrozenRound:
    return wb.prepare(
        round_spec or spec(),
        wb.ResponsesInput.model_validate(
            {"responses": responses if responses is not None else [response()]}
        ),
        path,
    )


def annotation(
    bundle: wb.Bundle, *, label: str | None = "supported", status: str = "submitted", index: int = 0
) -> wb.Annotation:
    frozen = bundle.responses[index]
    source = next(source for source in frozen.sources if source.source_id.endswith("document-0"))
    return wb.Annotation.model_validate(
        {
            "response_id": frozen.response_id,
            "case_id": frozen.case_id,
            "scenario_instance": frozen.scenario_instance,
            "system_code": frozen.system_code,
            "answer_sha256": frozen.answer_sha256,
            "source_manifest_sha256": frozen.source_manifest_sha256,
            "release_sha256": bundle.release_sha256,
            "revision": frozen.annotation_revision + 1,
            "base_annotation_sha256": frozen.annotation_sha256,
            "status": status,
            "reviewer_id": bundle.reviewer_id,
            "reviewed_at": WHEN,
            "claims": [
                {
                    "claim_id": claim.claim_id,
                    "exact_claim": claim.exact_claim,
                    "source_id": source.source_id if label == "supported" else None,
                    "source_sha256": source.sha256 if label == "supported" else None,
                    "span_or_locator": source.locators[0] if label == "supported" else None,
                    "label": label,
                    "rationale": "Justificativa de teste identificada; não é julgamento humano."
                    if label
                    else None,
                }
                for claim in frozen.claims
            ],
            "required_facts": None,
            "omitted_facts": None,
            "numbers_checked": None,
            "numbers_matching": None,
            "assistance_received": "Simulação determinística de teste.",
            "elapsed_seconds": 12,
            "evidence_origin": SIMULATION,
        }
    )


def annotation_file(
    bundle: wb.Bundle, reviews: list[wb.Annotation] | None = None
) -> wb.AnnotationFile:
    return wb.AnnotationFile(
        round_id=bundle.round_id,
        reviewer_id=bundle.reviewer_id,
        bundle_sha256=bundle.bundle_sha256,
        annotations=reviews or [annotation(bundle)],
    )


def submit_pair(path: Path, *, disagree: bool = False) -> tuple[wb.Annotation, wb.Annotation]:
    bundle_a = wb.bundle_for(path, "reviewer-a")
    bundle_b = wb.bundle_for(path, "reviewer-b")
    review_a = annotation(bundle_a)
    review_b = annotation(bundle_b, label="contradicted" if disagree else "supported")
    wb.import_annotations(path, annotation_file(bundle_a, [review_a]))
    wb.import_annotations(path, annotation_file(bundle_b, [review_b]))
    return review_a, review_b


def decision(
    path: Path, *, response_id: str = RESPONSE, adjudicator: str = "adjudicator-c"
) -> wb.Adjudication:
    value = wb.adjudication_template(path, response_id, adjudicator)
    bundle = wb.bundle_for(path, adjudicator)
    index = next(
        index for index, item in enumerate(bundle.responses) if item.response_id == response_id
    )
    final = annotation(bundle, index=index).model_dump()
    value.update(
        adjudicated_at=WHEN,
        final_rationale="Decisão explícita simulada, sem autoridade humana real.",
        assistance_received="Teste determinístico.",
        elapsed_seconds=20,
        final_review=final,
    )
    return wb.Adjudication.model_validate(value)


@pytest.fixture
def private_round(tmp_path: Path) -> Path:
    path = tmp_path / "round"
    make_round(path)
    return path


@pytest.fixture
def development_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy only named dev artifacts. Never even enumerate the reserved directory."""
    target = tmp_path / "dev-package"
    (target / "human-review").mkdir(parents=True)
    (target / "data/sources/dev").mkdir(parents=True)
    shutil.copyfile(wb.EVALS / "human-review/package.json", target / "human-review/package.json")
    shutil.copyfile(
        wb.EVALS / "human-review/round.template.json", target / "human-review/round.template.json"
    )
    shutil.copyfile(wb.EVALS / "data/dev.jsonl", target / "data/dev.jsonl")
    index = wb.read_json(target / "human-review/package.json")["index"]
    for item in index:
        name = f"{item['case_id']}.json"
        shutil.copyfile(wb.EVALS / f"data/sources/dev/{name}", target / f"data/sources/dev/{name}")
    monkeypatch.setattr(wb, "EVALS", target)
    return target


def test_prepare_verifies_only_dev_and_preserves_all_planned_responses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    read = wb.read_bytes
    accessed = []

    def record(path, *args, **kwargs):
        accessed.append(str(path))
        assert "reserved" not in str(path)
        return read(path, *args, **kwargs)

    monkeypatch.setattr(wb, "read_bytes", record)
    path = tmp_path / "round"
    frozen = make_round(
        path, round_spec=spec(cases=[CASE, "evaluation-dev-001"], systems=["A", "B"]), responses=[]
    )
    assert len(frozen.responses) == 4
    assert all(item.state == "not_run" and item.answer is None for item in frozen.responses)
    value = wb.report(path)
    assert value["state"] == "prepared"
    assert value["human_gate"] == "inconclusive"
    for system in ["A", "B"]:
        summary = value["systems"][system]["summary"]
        assert summary["funnel"]["planned"] == 2
        assert summary["funnel"]["executed"] == 0
        assert summary["gates"]["human_support"] == "inconclusive"
    assert accessed


def test_bundle_is_blind_and_complete(private_round: Path):
    submit_pair(private_round)
    bundle = wb.bundle_for(private_round, "new-reviewer")
    encoded = wb.canonical(bundle.model_dump()).decode()
    for hidden in (
        "expected_evidence_grades",
        "prohibited_facts",
        "reconciliation_expectation",
        "answerable",
        "reviewer-a",
        "reviewer-b",
    ):
        assert hidden not in encoded
    assert bundle.responses[0].annotation is None
    assert bundle.responses[0].annotation_revision == 0
    assert bundle.responses[0].sources
    assert bundle.release.corpus_sha256
    assert bundle.bundle_sha256 == wb.object_hash(bundle.model_dump(exclude={"bundle_sha256"}))


@pytest.mark.parametrize(
    "value", ["../escape", "..\\escape", "C:/outside", "/outside", "folder/../../outside"]
)
def test_path_traversal_is_rejected(tmp_path: Path, value: str):
    with pytest.raises(wb.WorkbenchError):
        wb.checked_path(tmp_path, value, exists=False)


def test_symlink_escape_is_rejected(tmp_path: Path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (outside / "file.json").write_text("{}", encoding="utf-8")
    try:
        (allowed / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip(
            "Host does not permit symlink creation; explicit traversal tests still execute."
        )
    with pytest.raises(wb.WorkbenchError, match="Symlink"):
        wb.checked_path(allowed, "link/file.json")


def test_private_artifacts_cannot_be_written_inside_git():
    with pytest.raises(wb.WorkbenchError, match="externa ao Git"):
        wb.private_destination(wb.ROOT / "evals/private-round")


@pytest.mark.parametrize("raw", [b"{", b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff"])
def test_invalid_duplicate_and_nonfinite_json_is_rejected(raw: bytes):
    with pytest.raises(wb.WorkbenchError):
        wb.decode(raw)


def test_size_limit_is_enforced_before_reading(tmp_path: Path):
    path = tmp_path / "large.json"
    path.write_bytes(b"{}" * 100)
    with pytest.raises(wb.WorkbenchError, match="grande"):
        wb.read_bytes(path, maximum=100)


def test_explicit_reserved_input_is_rejected_without_reading_content(
    monkeypatch: pytest.MonkeyPatch,
):
    def forbidden_open(*args, **kwargs):
        pytest.fail("Reserved input was opened")

    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises(wb.WorkbenchError, match="reservado"):
        wb.read_bytes(wb.EVALS / "data/reserved.jsonl")


def test_claim_text_must_be_exact_part_of_frozen_answer():
    value = response()
    value["claims"][0]["exact_claim"] = "Uma alegação não presente na resposta"
    with pytest.raises(ValueError, match="pertencer à resposta"):
        wb.ResponseInput.model_validate(value)


def test_strict_types_unknown_fields_and_duplicate_ids_rejected():
    value = spec().model_dump()
    value["reserved_dataset_access"] = "false"
    with pytest.raises(ValidationError):
        wb.RoundSpec.model_validate(value)
    value = spec().model_dump()
    value["system_codes"] = ["A", "A"]
    with pytest.raises(ValueError, match="duplicados"):
        wb.RoundSpec.model_validate(value)
    with pytest.raises(ValidationError):
        wb.ResponsesInput.model_validate({"responses": [], "gold": []})


@pytest.mark.parametrize("ids", [["evaluation-reserved-000"], ["evaluation-dev-999"]])
def test_cases_outside_verified_dev_package_rejected(tmp_path: Path, ids: list[str]):
    with pytest.raises(wb.WorkbenchError, match="fora do pacote"):
        make_round(tmp_path / "round", round_spec=spec(cases=ids), responses=[])


def test_duplicate_or_unplanned_responses_rejected(tmp_path: Path):
    with pytest.raises(wb.WorkbenchError, match="duplicada"):
        make_round(tmp_path / "one", responses=[response(), response()])
    with pytest.raises(wb.WorkbenchError, match="fora da rodada"):
        make_round(tmp_path / "two", responses=[response(system="OTHER")])


def test_package_corpus_and_source_modification_are_rejected(
    tmp_path: Path, development_copy: Path
):
    path = tmp_path / "round"
    make_round(path)
    source = development_copy / f"data/sources/dev/{CASE}.json"
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(wb.WorkbenchError, match="hash divergente"):
        wb.report(path)


def test_source_path_traversal_even_with_updated_dev_hash_is_rejected(
    tmp_path: Path, development_copy: Path
):
    dev = development_copy / "data/dev.jsonl"
    cases = [wb.decode(line) for line in dev.read_bytes().splitlines()]
    cases[0]["source_path"] = "../../outside.json"
    dev.write_bytes(b"\n".join(wb.canonical(case) for case in cases) + b"\n")
    package = development_copy / "human-review/package.json"
    value = wb.read_json(package)
    value["case_file_sha256"] = wb.digest(dev.read_bytes())
    package.write_bytes(wb.canonical(value))
    with pytest.raises(wb.WorkbenchError, match="Path traversal"):
        make_round(tmp_path / "round", responses=[])


def test_release_corpus_mismatch_and_invalid_claim_locator_rejected(tmp_path: Path):
    value = spec().model_dump()
    value["release"]["corpus_sha256"] = "a" * 64
    with pytest.raises(wb.WorkbenchError, match="Corpus"):
        make_round(tmp_path / "one", round_spec=wb.RoundSpec.model_validate(value))
    invalid = response()
    invalid["claims"][0]["references"] = [
        {"source_id": f"{CASE}-document-0", "locator": "/corpus/999"}
    ]
    with pytest.raises(ValueError, match="locator"):
        make_round(tmp_path / "two", responses=[invalid])


def test_bundle_tampering_detected(private_round: Path):
    value = wb.bundle_for(private_round, "reviewer-a").model_dump()
    value["responses"][0]["answer"] = "Texto modificado"
    with pytest.raises(ValueError, match="Hash da resposta"):
        wb.Bundle.model_validate(value)
    value = wb.bundle_for(private_round, "reviewer-a").model_dump()
    value["release"]["chunk_policy"] = "changed"
    with pytest.raises(ValueError, match="release"):
        wb.Bundle.model_validate(value)


def test_unassessed_draft_fields_stay_null_and_not_false(private_round: Path):
    bundle = wb.bundle_for(private_round, "reviewer-a")
    draft = annotation(bundle, label=None, status="draft")
    wb.import_annotations(private_round, annotation_file(bundle, [draft]))
    own = wb.bundle_for(private_round, "reviewer-a")
    assert own.responses[0].annotation is not None
    assert own.responses[0].annotation.claims[0].label is None
    value = wb.report(private_round)
    assert value["cases"][0]["claim_labels"] is None
    assert value["cases"][0]["numbers_checked"] is None
    assert value["systems"]["A"]["summary"]["metrics"]["human_support_precision"]["value"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("answer_sha256", "0" * 64),
        ("source_manifest_sha256", "0" * 64),
        ("release_sha256", "0" * 64),
        ("scenario_instance", "another-incident"),
        ("case_id", "evaluation-dev-001"),
        ("system_code", "B"),
    ],
)
def test_annotation_other_versions_rejected(private_round: Path, field: str, value: str):
    bundle = wb.bundle_for(private_round, "reviewer-a")
    item = annotation(bundle).model_dump()
    item[field] = value
    with pytest.raises(wb.WorkbenchError):
        wb.import_annotations(
            private_round, annotation_file(bundle, [wb.Annotation.model_validate(item)])
        )


def test_supported_requires_real_frozen_source_and_locator(private_round: Path):
    bundle = wb.bundle_for(private_round, "reviewer-a")
    item = annotation(bundle).model_dump()
    item["claims"][0].update(source_id=None, source_sha256=None, span_or_locator=None)
    with pytest.raises(wb.WorkbenchError, match="supported exige"):
        wb.import_annotations(
            private_round, annotation_file(bundle, [wb.Annotation.model_validate(item)])
        )
    item = annotation(bundle).model_dump()
    item["claims"][0]["span_or_locator"] = "/corpus/999"
    with pytest.raises(wb.WorkbenchError, match="locator inválido"):
        wb.import_annotations(
            private_round, annotation_file(bundle, [wb.Annotation.model_validate(item)])
        )


def test_every_claim_exact_text_and_reason_required(private_round: Path):
    bundle = wb.bundle_for(private_round, "reviewer-a")
    item = annotation(bundle).model_dump()
    item["claims"][0]["rationale"] = " "
    with pytest.raises(ValueError, match="motivo"):
        wb.Annotation.model_validate(item)
    item = annotation(bundle).model_dump()
    item["claims"] = []
    with pytest.raises(wb.WorkbenchError, match="todas as alegações"):
        wb.import_annotations(
            private_round, annotation_file(bundle, [wb.Annotation.model_validate(item)])
        )
    item = annotation(bundle).model_dump()
    item["claims"][0]["exact_claim"] = "Paráfrase alterada"
    with pytest.raises(wb.WorkbenchError, match="Texto de alegação"):
        wb.import_annotations(
            private_round, annotation_file(bundle, [wb.Annotation.model_validate(item)])
        )


def test_import_idempotence_revision_cas_and_submission_immutability(private_round: Path):
    bundle = wb.bundle_for(private_round, "reviewer-a")
    file = annotation_file(bundle, [annotation(bundle, status="draft")])
    assert wb.import_annotations(private_round, file) == {"imported": 1, "idempotent": False}
    assert wb.import_annotations(private_round, file) == {"imported": 0, "idempotent": True}
    old = annotation(bundle, label="contradicted", status="draft")
    with pytest.raises(wb.WorkbenchError, match="Conflito"):
        wb.import_annotations(private_round, annotation_file(bundle, [old]))
    fresh = wb.bundle_for(private_round, "reviewer-a")
    submitted = annotation(fresh)
    wb.import_annotations(private_round, annotation_file(fresh, [submitted]))
    assert len(wb.review_history(private_round)) == 2
    after = wb.bundle_for(private_round, "reviewer-a")
    with pytest.raises(wb.WorkbenchError, match="imutável"):
        wb.import_annotations(private_round, annotation_file(after, [annotation(after)]))


def test_no_concurrent_annotation_overwrite(private_round: Path):
    bundle = wb.bundle_for(private_round, "reviewer-a")
    one = annotation_file(bundle, [annotation(bundle, status="draft")])
    two = annotation_file(bundle, [annotation(bundle, label="contradicted", status="draft")])

    def attempt(file):
        try:
            return wb.import_annotations(private_round, file)
        except wb.WorkbenchError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [one, two]))
    assert results.count("conflict") == 1
    assert len(wb.review_history(private_round)) == 1
    assert not (private_round / ".write.lock").exists()


def test_batch_validates_every_record_before_mutation(tmp_path: Path):
    path = tmp_path / "round"
    make_round(
        path,
        round_spec=spec(cases=[CASE, "evaluation-dev-001"]),
        responses=[response(), response("evaluation-dev-001")],
    )
    bundle = wb.bundle_for(path, "reviewer-a")
    one = annotation(bundle)
    invalid = annotation(bundle, index=1).model_dump()
    invalid["answer_sha256"] = "0" * 64
    with pytest.raises(wb.WorkbenchError):
        wb.import_annotations(
            path, annotation_file(bundle, [one, wb.Annotation.model_validate(invalid)])
        )
    assert not wb.review_history(path)


def test_two_reviews_independent_and_disagreement_needs_explicit_distinct_adjudicator(
    private_round: Path,
):
    one = wb.bundle_for(private_round, "reviewer-a")
    wb.import_annotations(private_round, annotation_file(one))
    assert wb.report(private_round)["state"] == "in_review"
    with pytest.raises(wb.WorkbenchError, match="duas submissões"):
        wb.adjudication_template(private_round, RESPONSE, "adjudicator-c")
    two = wb.bundle_for(private_round, "reviewer-b")
    wb.import_annotations(
        private_round, annotation_file(two, [annotation(two, label="contradicted")])
    )
    assert wb.report(private_round)["state"] == "with_disagreements"
    row = wb.compare(private_round)["responses"][0]
    assert row["submitted_reviews"] == 2
    assert row["disagreements"] == ["claims"]
    with pytest.raises(wb.WorkbenchError, match="distinto"):
        wb.adjudication_template(private_round, RESPONSE, "reviewer-a")
    value = decision(private_round).model_dump()
    value["disagreements"] = []
    with pytest.raises(wb.WorkbenchError, match="divergências"):
        wb.adjudicate(private_round, wb.Adjudication.model_validate(value))
    wb.adjudicate(private_round, decision(private_round))
    report = wb.report(private_round)
    assert report["state"] == "completed"
    assert report["human_gate"] == "inconclusive"
    assert report["cases"][0]["human_adjudicated"] is False


def test_agreement_also_requires_explicit_adjudication(private_round: Path):
    submit_pair(private_round)
    report = wb.report(private_round)
    assert report["state"] == "in_review"
    assert report["systems"]["A"]["summary"]["funnel"]["adjudicated"] == 0
    wb.adjudicate(private_round, decision(private_round))
    assert wb.report(private_round)["human_gate"] == "inconclusive"


def test_third_submitted_review_is_rejected(private_round: Path):
    submit_pair(private_round)
    bundle = wb.bundle_for(private_round, "reviewer-third")
    with pytest.raises(wb.WorkbenchError, match="dois julgamentos"):
        wb.import_annotations(private_round, annotation_file(bundle))


def test_simulation_cannot_be_adjudicated_as_human(private_round: Path):
    submit_pair(private_round)
    value = decision(private_round).model_dump()
    value["evidence_origin"] = "human_declared"
    value["final_review"]["evidence_origin"] = "human_declared"
    with pytest.raises(wb.WorkbenchError, match="Simulação"):
        wb.adjudicate(private_round, wb.Adjudication.model_validate(value))


@pytest.mark.parametrize(
    "mutation",
    [
        "review_label",
        "review_release",
        "decision_identity",
        "decision_response",
        "decision_provenance",
        "decision_final_source",
    ],
)
def test_report_revalidates_imported_disk_provenance(private_round: Path, mutation: str):
    submit_pair(private_round, disagree=True)
    wb.adjudicate(private_round, decision(private_round))
    if mutation.startswith("review"):
        target = next((private_round / "annotations").glob("*.json"))
        value = wb.read_json(target)
        if mutation == "review_label":
            value["claims"][0]["label"] = "irrelevant"
        else:
            value["release_sha256"] = "0" * 64
    else:
        target = next((private_round / "adjudications").glob("*.json"))
        value = wb.read_json(target)
        if mutation == "decision_identity":
            value["adjudicator_id"] = "reviewer-a"
            value["final_review"]["reviewer_id"] = "reviewer-a"
        elif mutation == "decision_response":
            value["response_id"] = "foreign-response"
        elif mutation == "decision_provenance":
            value["review_sha256s"][0] = "0" * 64
        else:
            value["final_review"]["claims"][0]["source_sha256"] = "0" * 64
    target.write_bytes(wb.canonical(value))
    with pytest.raises((wb.WorkbenchError, ValidationError, OSError)):
        wb.report(private_round)


def test_revision_history_cannot_skip_or_change_previous_draft(private_round: Path):
    bundle = wb.bundle_for(private_round, "reviewer-a")
    wb.import_annotations(
        private_round, annotation_file(bundle, [annotation(bundle, status="draft")])
    )
    fresh = wb.bundle_for(private_round, "reviewer-a")
    wb.import_annotations(private_round, annotation_file(fresh))
    first = next(
        item
        for item in (private_round / "annotations").glob("*.json")
        if wb.read_json(item)["revision"] == 1
    )
    value = wb.read_json(first)
    value["elapsed_seconds"] = 50
    first.write_bytes(wb.canonical(value))
    with pytest.raises(wb.WorkbenchError, match="histórico"):
        wb.report(private_round)


def test_all_eight_categories_remain_required_when_planned_subset_is_smaller(private_round: Path):
    frozen = wb.load_round(private_round)
    assert len(frozen.required_categories) == 8
    assert len({item.category for item in frozen.responses}) == 1
    report = wb.report(private_round)
    assert len(report["systems"]["A"]["categories"]) == 8
    assert report["systems"]["A"]["categories"]["obsolete_procedure"]["funnel"]["planned"] == 0


def test_thirty_simulated_responses_do_not_meet_real_human_gate(tmp_path: Path):
    path = tmp_path / "round"
    cases = [f"evaluation-dev-{index:03d}" for index in range(30)]
    make_round(path, round_spec=spec(cases=cases), responses=[response(case) for case in cases])
    for reviewer in ["reviewer-a", "reviewer-b"]:
        bundle = wb.bundle_for(path, reviewer)
        wb.import_annotations(
            path, annotation_file(bundle, [annotation(bundle, index=index) for index in range(30)])
        )
    for case_id in cases:
        wb.adjudicate(path, decision(path, response_id=f"{case_id}--A"))
    report = wb.report(path)
    summary = report["systems"]["A"]["summary"]
    assert summary["funnel"]["planned"] == 30
    assert summary["human_evidence"]["responses"] == 0
    assert summary["human_evidence"]["eligible"] is False
    assert summary["gates"]["human_support"] == "inconclusive"
    assert summary["gates"]["useful_coverage"] == "inconclusive"


def test_failures_remain_in_each_system_denominator(tmp_path: Path):
    path = tmp_path / "round"
    make_round(
        path,
        round_spec=spec(cases=[CASE, "evaluation-dev-001"], systems=["A", "B"]),
        responses=[
            response(),
            {
                "case_id": "evaluation-dev-001",
                "system_code": "A",
                "state": "failed",
                "failure_reason": "Fixture timeout",
            },
        ],
    )
    value = wb.report(path)
    assert value["systems"]["A"]["summary"]["funnel"] == {
        "planned": 2,
        "executed": 2,
        "failed": 1,
        "answered": 1,
        "abstained": 0,
        "adjudicated": 0,
    }
    assert value["systems"]["B"]["summary"]["funnel"]["planned"] == 2
    assert value["systems"]["B"]["summary"]["funnel"]["executed"] == 0


def test_adjudication_event_idempotence_and_no_overwrite(private_round: Path):
    submit_pair(private_round)
    value = decision(private_round)
    wb.adjudicate(private_round, value)
    wb.adjudicate(private_round, value)
    modified = value.model_dump()
    modified["final_rationale"] = "Outro motivo"
    with pytest.raises(wb.WorkbenchError, match="Conflito"):
        wb.adjudicate(private_round, wb.Adjudication.model_validate(modified))


def test_report_escapes_attacks_including_script_closures():
    rendered = wb.report_html({"attack": "</script><img src=x onerror=alert(1)>"}).decode()
    assert "<img src=x" not in rendered
    assert "&lt;/script&gt;" in rendered
    assert "connect-src 'none'" in rendered


def test_cli_errors_do_not_echo_private_validation_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        json.dumps({"responses": [{"private-secret": "PRIVATE_TEST_CONTENT"}]}), encoding="utf-8"
    )
    spec_file = tmp_path / "spec.json"
    wb.write_json(spec_file, spec().model_dump())
    assert (
        wb.main(
            [
                "prepare",
                "--round-spec",
                str(spec_file),
                "--responses",
                str(invalid),
                "--output",
                str(tmp_path / "round"),
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert "PRIVATE_TEST_CONTENT" not in output.err
    assert "incompatível" in output.err


def test_cli_prepare_bundle_validate_import_compare_report(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    spec_file = tmp_path / "spec.json"
    responses_file = tmp_path / "responses.json"
    path = tmp_path / "round"
    wb.write_json(spec_file, spec().model_dump())
    wb.write_json(responses_file, {"responses": [response()]})
    assert (
        wb.main(
            [
                "prepare",
                "--round-spec",
                str(spec_file),
                "--responses",
                str(responses_file),
                "--output",
                str(path),
            ]
        )
        == 0
    )
    bundle_path = tmp_path / "bundle.json"
    assert (
        wb.main(
            [
                "bundle",
                "--round",
                str(path),
                "--reviewer",
                "reviewer-a",
                "--output",
                str(bundle_path),
            ]
        )
        == 0
    )
    bundle = wb.Bundle.model_validate(wb.read_json(bundle_path))
    annotations_path = tmp_path / "annotations.json"
    wb.write_json(annotations_path, annotation_file(bundle).model_dump())
    for command in ["validate", "import"]:
        assert wb.main([command, "--round", str(path), "--annotations", str(annotations_path)]) == 0
    assert wb.main(["compare", "--round", str(path)]) == 0
    assert wb.main(["report", "--round", str(path), "--output", str(tmp_path / "report.html")]) == 0
    assert (tmp_path / "report.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    capsys.readouterr()


def test_oversized_generated_artifact_is_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(wb, "MAX_FILE_BYTES", 100)
    target = tmp_path / "large-output.json"
    with pytest.raises(wb.WorkbenchError, match="grande"):
        wb.write_json(target, {"data": "x" * 101})
    assert not target.exists()


def test_unknown_parser_policy_and_retrieval_versions_remain_null(tmp_path: Path):
    value = spec().model_dump()
    for key in ("chunk_policy", "parser_rules_version", "retrieval_profile"):
        value["release"][key] = None
    frozen = make_round(
        tmp_path / "round", round_spec=wb.RoundSpec.model_validate(value), responses=[]
    )
    assert frozen.spec.release.chunk_policy is None
    assert wb.load_round(tmp_path / "round").spec.release.parser_rules_version is None


@pytest.mark.parametrize(
    "mutation",
    [
        "text",
        "title",
        "metadata",
        "locator",
        "context",
        "question",
        "scenario",
        "category",
        "gold",
        "corpus",
        "execution",
        "inputs",
    ],
)
def test_recomputed_self_hashes_do_not_replace_verified_dev_anchors(
    private_round: Path, mutation: str
):
    path = private_round / "round.json"
    value = wb.read_json(path)
    frozen = value["responses"][0]
    if mutation == "text":
        frozen["sources"][0]["text"] = "FONTE ALTERADA EM TESTE SINTÉTICO"
        frozen["sources"][0]["sha256"] = wb.digest(frozen["sources"][0]["text"].encode())
    elif mutation in {"title", "metadata", "locator"}:
        source = frozen["sources"][0]
        if mutation == "title":
            source["title"] = "Título alterado"
        elif mutation == "metadata":
            source["metadata"]["lineage"] = "false-lineage"
        else:
            source["locators"] = ["/corpus/999"]
    elif mutation == "context":
        frozen["context"]["focus_order"] = "wrong-order"
    elif mutation == "question":
        frozen["question"] = "Pergunta adulterada"
    elif mutation == "scenario":
        frozen["scenario_instance"] = "another-incident"
    elif mutation == "category":
        frozen["category"] = "another-category"
    elif mutation == "gold":
        value["evaluations"][0]["answerable"] = False
    elif mutation == "corpus":
        value["spec"]["release"]["corpus_sha256"] = "0" * 64
        value["release_sha256"] = wb.object_hash(value["spec"]["release"])
    elif mutation == "execution":
        frozen["answer"] += " ALTERADO"
        frozen["answer_sha256"] = wb.digest(frozen["answer"].encode())
        value["execution"][0]["answer"] = frozen["answer"]
    else:
        value["inputs"]["responses"][0]["answer"] += " ALTERADO"
    frozen["source_manifest_sha256"] = wb.object_hash(
        {
            "source_file_sha256": frozen["source_file_sha256"],
            "sources": [
                {key: item for key, item in source.items() if key != "text"}
                for source in frozen["sources"]
            ],
        }
    )
    value["round_sha256"] = wb.object_hash(
        {key: item for key, item in value.items() if key != "round_sha256"}
    )
    path.write_bytes(wb.canonical(value))
    with pytest.raises((wb.WorkbenchError, ValidationError)):
        wb.load_round(private_round)


def test_adjudicator_template_does_not_inherit_assessed_dimensions(private_round: Path):
    for reviewer in ["reviewer-a", "reviewer-b"]:
        bundle = wb.bundle_for(private_round, reviewer)
        review = annotation(bundle).model_dump()
        review.update(
            required_facts=["Observed test fact"],
            omitted_facts=["Missing test fact"],
            counterevidence_notes="Counterevidence test",
            temporal_notes="Temporal test",
            abstention_judgment="appropriate",
            numbers_checked=1,
            numbers_matching=1,
            critical_flags=["unsupported_root_cause"],
        )
        wb.import_annotations(
            private_round, annotation_file(bundle, [wb.Annotation.model_validate(review)])
        )
    template = wb.adjudication_template(private_round, RESPONSE, "adjudicator-c")
    final = template["final_review"]
    for field in [
        "required_facts",
        "omitted_facts",
        "counterevidence_notes",
        "temporal_notes",
        "abstention_judgment",
        "numbers_checked",
        "numbers_matching",
    ]:
        assert final[field] is None
    assert final["critical_flags"] == []
    assert final["claims"][0]["label"] is None
    assert len(wb.review_history(private_round)) == 2


def test_cli_schema_is_strict_and_reproducible(tmp_path: Path, capsys: pytest.CaptureFixture):
    path = tmp_path / "schema.json"
    assert wb.main(["schema", "--kind", "annotations", "--output", str(path)]) == 0
    schema = wb.read_json(path)
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Annotation"]["additionalProperties"] is False
    capsys.readouterr()
