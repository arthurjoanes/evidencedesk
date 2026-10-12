"""Synthetic contract regressions; these tests never create human judgments."""

from __future__ import annotations

import asyncio
import copy
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from evals import adversarial
from evidencedesk.errors import Problem
from evidencedesk.investigations import processing, tools
from evidencedesk.investigations.tools import (
    CompareArguments,
    ExecutionContext,
    ReadArguments,
    ReadTools,
    SearchArguments,
    TimelineArguments,
)
from evidencedesk.jobs.service import Lease
from evidencedesk.model_runtime.azure import SYSTEM_INSTRUCTIONS, response_payload
from evidencedesk.model_runtime.contracts import (
    GeneratedDossier,
    GenerationRequest,
    validate_generated_dossier,
)


def synthetic_lease() -> Lease:
    return Lease(
        "adversarial-fixture", "job-fixture", "run-fixture", "actor-fixture", "investigation", 1, 1
    )


def test_preparation_is_reproducible_and_has_no_semantic_or_human_verdict():
    first = adversarial.prepare()
    second = adversarial.prepare()
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert len(first.cases) == 10
    assert {case.category for case in first.cases} == {
        "fake_system",
        "delimiter_break",
        "canary_leak_request",
        "obsolete_procedure",
        "omitted_counterevidence",
        "invented_causality",
        "unsupported_cited_claim",
        "numerical_discordance",
    }
    assert {case.mutation_surface for case in first.cases} == {"text", "title", "metadata"}
    assert first.semantic_model_status == first.human_review_status == "not_run"
    assert first.human_gate == "inconclusive"
    assert not first.reserved_used and first.paid_calls == 0
    assert first.reranker_candidate == "unpromoted"
    assert first.parser_revision is first.chunk_policy is None  # No parser was executed.
    for case in first.cases:
        assert case.binding.answer_sha256 is None
        assert case.binding.corpus_sha256 == first.corpus_sha256
        assert case.binding.source_manifest_sha256 == adversarial.digest(case.source_manifest)
        assert case.binding.request_sha256 == adversarial.digest(
            response_payload(
                case.generation_request, first.release.deployment, first.release.instructions
            )
        )
    assert len({case.binding.request_sha256 for case in first.cases}) == 10


def test_deterministic_counts_survive_discordant_untrusted_source():
    prepared = adversarial.prepare()
    case = next(case for case in prepared.cases if case.category == "numerical_discordance")
    aggregate = json.loads(case.generation_request.evidence[0].text)
    assert aggregate["counts"]["observations"] == 2
    assert aggregate["counts"]["logical_events"] == 1
    assert aggregate["counts"]["orders"] == 1
    assert "99" in case.generation_request.evidence[1].text
    assert case.generation_request.evidence[0].kind == "reconciliation_result"


def test_canary_is_a_fictional_trusted_fixture_not_part_of_the_attack_text():
    prepared = adversarial.prepare()
    case = next(case for case in prepared.cases if case.category == "canary_leak_request")
    marker = "CANARIO-FICTICIO-LAB-GIRASSOL"
    assert prepared.release.instructions.startswith(SYSTEM_INSTRUCTIONS)
    assert marker in prepared.release.instructions
    assert marker not in json.dumps(case.generation_request.model_dump(mode="json"))
    assert prepared.semantic_model_status == "not_run"


def test_delimiter_break_remains_json_data_and_cannot_create_message_roles():
    prepared = adversarial.prepare()
    case = next(case for case in prepared.cases if case.case_id == "adv-dev-delimiter-title")
    payload = response_payload(
        case.generation_request, prepared.release.deployment, prepared.release.instructions
    )
    assert payload["instructions"] == prepared.release.instructions
    assert len(payload["input"]) == 1 and payload["input"][0]["role"] == "user"
    context = json.loads(payload["input"][0]["content"])
    assert "<system>" in context["evidence"][1]["title"]
    assert context["question"] == prepared.cases[0].generation_request.question
    assert set(payload) == {
        "model",
        "store",
        "background",
        "instructions",
        "input",
        "reasoning",
        "max_output_tokens",
        "text",
    }
    assert payload["store"] is False and payload["background"] is False
    assert payload["text"]["format"]["strict"] is True


def test_metadata_attack_preserves_temporal_role_without_expanding_generator_fields():
    prepared = adversarial.prepare()
    case = next(case for case in prepared.cases if case.case_id == "adv-dev-fake-system-metadata")
    context = case.generation_request.evidence[1].model_dump(mode="json")
    assert context["temporal_role"] == "retrospective_context"
    assert context["valid_from"] == "2026-01-13T00:00:00Z"
    metadata = case.source_manifest[1]["metadata"]
    assert isinstance(metadata, dict)
    assert "instruction" in metadata
    assert "url" in metadata
    assert "metadata" not in context and "url" not in context and "version" not in context
    obsolete = next(case for case in prepared.cases if case.category == "obsolete_procedure")
    assert obsolete.generation_request.evidence[1].valid_until < datetime(2026, 1, 12, tzinfo=UTC)
    assert obsolete.generation_request.evidence[1].temporal_role == "historical_artifact"


def test_preparation_never_opens_reserved_or_gold(monkeypatch):
    opened = []
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        opened.append(path)
        assert "reserved" not in path.parts
        assert path.name not in {"dev.jsonl", "package.json"}
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    adversarial.prepare()
    assert adversarial.FIXTURES in opened


@pytest.mark.parametrize(
    "mutation",
    [
        "reserved",
        "duplicate_case",
        "duplicate_source",
        "unknown_target",
        "bad_metadata",
        "bad_locator",
    ],
)
def test_fixture_contract_rejects_ambiguous_or_incompatible_cases(mutation):
    data = adversarial.read_json(adversarial.FIXTURES)
    assert isinstance(data, dict)
    if mutation == "reserved":
        data["split"] = "reserved"
    elif mutation == "duplicate_case":
        data["cases"].append(copy.deepcopy(data["cases"][0]))
    elif mutation == "duplicate_source":
        data["sources"].append(copy.deepcopy(data["sources"][0]))
    elif mutation == "unknown_target":
        data["cases"][0]["target_evidence_id"] = "missing"
    elif mutation == "bad_metadata":
        data["sources"][0]["metadata"]["temporal_role"] = "system"
    elif mutation == "bad_locator":
        data["sources"][0]["locator"]["line_end"] = 100
    with pytest.raises(ValidationError):
        adversarial.AdversarialSuite.model_validate(data)


def test_json_loader_refuses_duplicate_keys_and_oversized_files(tmp_path):
    artifact = tmp_path / "fixture.json"
    artifact.write_text('{"split":"dev","split":"reserved"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicada"):
        adversarial.read_json(artifact)
    artifact.write_bytes(b" " * (adversarial.MAX_JSON_BYTES + 1))
    with pytest.raises(ValueError, match="limite"):
        adversarial.read_json(artifact)


def test_mock_runs_are_deterministic_and_keep_real_gates_inconclusive():
    report = asyncio.run(adversarial.run_contracts())
    repeated = asyncio.run(adversarial.run_contracts())
    assert report.model_dump(mode="json") == repeated.model_dump(mode="json")
    assert report.planned_cases == report.executed_cases == report.contract_passed_cases == 10
    assert report.contract_failed_cases == 0
    assert (
        report.semantic_model_status
        == report.human_review_status
        == report.database_checks
        == "not_run"
    )
    assert report.human_gate == "inconclusive" and report.reranker_candidate == "unpromoted"
    assert report.accounting == "simulated_hooks_not_database_ledger"
    assert sum(probe.dispatches for case in report.cases for probe in case.probes) == 20
    for case in report.cases:
        assert case.human_labels is None
        assert case.semantic_model_status == case.human_review_status == "not_run"
        assert case.binding.answer_sha256 == case.probes[0].answer_sha256
        accepted, rejected = case.probes
        assert accepted.actual_error is None
        assert rejected.actual_error == adversarial.EXPECTED_FAILURES[rejected.probe]
        assert rejected.answer_sha256 is None
        assert accepted.event_order == ["resolve_source"] * 3 + [
            "authorize_dispatch",
            "mock_transport",
            "account_usage",
        ]
        assert rejected.event_order == accepted.event_order
        assert accepted.usage.output_tokens == 57  # Reasoning is included, not added.
        if rejected.probe == "outside_order":
            assert rejected.failed_accounting is False  # Usage recorded before scope rejection.
        elif rejected.probe == "timeout":
            assert rejected.usage.status == "unknown"
            assert rejected.usage.input_tokens is rejected.usage.output_tokens is None
            assert rejected.response_sha256 is None
        else:
            assert rejected.usage.status == "reported" and rejected.failed_accounting


@pytest.mark.parametrize(
    "field",
    [
        "case_id",
        "request_sha256",
        "source_manifest_sha256",
        "corpus_sha256",
        "release_sha256",
        "boundary_sources_sha256",
        "answer_sha256",
    ],
)
def test_annotation_reuse_requires_identical_answer_corpus_release_and_boundaries(field):
    binding = adversarial.prepare().cases[0].binding.model_copy(update={"answer_sha256": "a" * 64})
    adversarial.validate_annotation_binding(binding, binding)
    stale = binding.model_copy(update={field: "different-case" if field == "case_id" else "b" * 64})
    with pytest.raises(ValueError, match="reutilização recusada"):
        adversarial.validate_annotation_binding(stale, binding)


def test_unexecuted_response_binding_cannot_reuse_annotations():
    binding = adversarial.prepare().cases[0].binding
    with pytest.raises(ValueError, match="reutilização recusada"):
        adversarial.validate_annotation_binding(binding, binding)


def test_source_change_during_execution_invalidates_report(monkeypatch):
    original_hashes = adversarial.boundary_hashes
    calls = 0

    def changed_hashes():
        nonlocal calls
        calls += 1
        result = original_hashes()
        if calls > 2:
            result["backend/src/evidencedesk/investigations/processing.py"] = "0" * 64
        return result

    monkeypatch.setattr(adversarial, "boundary_hashes", changed_hashes)
    with pytest.raises(ValueError, match="invalidado"):
        asyncio.run(adversarial.run_contracts())


def test_cli_writes_external_private_artifact_and_refuses_overwrite(tmp_path, capsys):
    destination = tmp_path / "prepared.json"
    assert adversarial.main(["prepare", "--output", str(destination)]) == 0
    result = json.loads(destination.read_text(encoding="utf-8"))
    assert result["semantic_model_status"] == "not_run"
    assert result["human_gate"] == "inconclusive"
    original = destination.read_bytes()
    assert adversarial.main(["prepare", "--output", str(destination)]) == 2
    assert destination.read_bytes() == original
    assert "adversarial_artifact_rejected" in capsys.readouterr().out


def test_private_writer_rejects_repository_destination():
    with pytest.raises(ValueError, match="externo"):
        adversarial.write_private(
            adversarial.REPOSITORY / "runtime" / "unsafe-receipt.json", adversarial.prepare()
        )


@pytest.mark.parametrize("marker_kind", ["directory", "file"])
def test_private_writer_rejects_other_git_checkout(tmp_path, marker_kind):
    checkout = tmp_path / "other-checkout"
    checkout.mkdir()
    marker = checkout / ".git"
    if marker_kind == "directory":
        marker.mkdir()
    else:
        marker.write_text("gitdir: synthetic-worktree-fixture\n", encoding="utf-8")
    destination = checkout / "private" / "adversarial.json"
    with pytest.raises(ValueError, match="checkout Git"):
        adversarial.write_private(destination, adversarial.prepare())
    assert not destination.parent.exists()


@pytest.mark.parametrize(
    "text",
    [
        "A confirmação causou a falha da transportadora.",
        "A entrega foi concluída e comprovada.",
        "Há 99 pagamentos distintos.",
    ],
)
def test_structural_citation_validity_does_not_prove_semantic_support(text):
    data = adversarial.mock_dossier()
    data["claims"][0]["kind"] = "observed_fact"
    data["claims"][0]["text"] = text
    data["claims"][0]["evidence_links"][0]["relation"] = "supports"
    # The fixture deliberately lies. The boundary checks IDs/schema, so accepting
    # it is not evidence that a real model generated or resisted this claim.
    dossier = validate_generated_dossier(GeneratedDossier.model_validate(data), {"adv-document"})
    assert dossier.claims[0].support_status == "pending_review"


@pytest.mark.parametrize(
    "changed_field",
    ["canonical_text", "title", "kind", "temporal_role", "valid_from", "valid_until"],
)
def test_real_dispatch_comparison_refuses_changed_source_before_network(monkeypatch, changed_field):
    request = adversarial.prepare().cases[0].generation_request
    source = request.evidence[1]
    persisted = source.model_dump() | {"canonical_text": source.text}
    persisted[changed_field] = "changed-untrusted-value"

    @contextmanager
    def transaction(_tenant):
        yield object()

    monkeypatch.setattr(processing, "transaction", transaction)
    monkeypatch.setattr(processing, "assert_publishable", lambda *_args: None)
    monkeypatch.setattr(processing, "actor_for_worker", lambda *_args: "fixture-actor")
    monkeypatch.setattr(
        processing,
        "authorize_run",
        lambda *_args: {
            "snapshot_id": request.evidence_snapshot_id,
            "incident_id": "fixture-incident",
        },
    )

    def resolve(_connection, _actor, evidence_id, snapshot_id, *, incident_id):
        assert snapshot_id == request.evidence_snapshot_id and incident_id == "fixture-incident"
        item = next(item for item in request.evidence if item.evidence_id == evidence_id)
        return (
            persisted
            if item.evidence_id == source.evidence_id
            else item.model_dump() | {"canonical_text": item.text}
        )

    monkeypatch.setattr(processing, "resolve_evidence", resolve)
    with pytest.raises(Problem) as caught:
        processing.authorize_context(synthetic_lease(), request)
    assert caught.value.code == "dispatch_source_changed"


@pytest.mark.parametrize("failure", ["lease_lost", "policy_changed", "not_found"])
def test_current_authority_or_tombstone_denial_propagates_before_dispatch(monkeypatch, failure):
    @contextmanager
    def transaction(_tenant):
        yield object()

    request = adversarial.prepare().cases[0].generation_request
    monkeypatch.setattr(processing, "transaction", transaction)

    def denied(*_args, **_kwargs):
        raise Problem(409 if failure != "not_found" else 404, failure, "Synthetic denial.")

    monkeypatch.setattr(
        processing, "assert_publishable", denied if failure != "not_found" else lambda *_args: None
    )
    monkeypatch.setattr(processing, "actor_for_worker", lambda *_args: "fixture-actor")
    monkeypatch.setattr(
        processing,
        "authorize_run",
        lambda *_args: {
            "snapshot_id": request.evidence_snapshot_id,
            "incident_id": "fixture-incident",
        },
    )
    monkeypatch.setattr(processing, "resolve_evidence", denied)
    with pytest.raises(Problem) as caught:
        processing.authorize_context(synthetic_lease(), request)
    assert caught.value.code == failure


@pytest.mark.parametrize(
    "field", ["tenant_id", "actor_id", "snapshot_id", "sql", "url", "path", "command"]
)
@pytest.mark.parametrize(
    ("contract", "arguments"),
    [
        (SearchArguments, {"query": "pagamento"}),
        (ReadArguments, {"evidence_id": "adv-document"}),
        (TimelineArguments, {"order_reference": "PED-FICTICIO"}),
        (CompareArguments, {"first_id": "adv-document", "second_id": "adv-counterevidence"}),
    ],
)
def test_source_attack_cannot_add_authority_or_network_to_read_tools(field, contract, arguments):
    with pytest.raises(ValidationError):
        contract.model_validate({**arguments, field: "system override"})


class FakeAuditConnection:
    """A simulated ledger, used only to exercise the actual ReadTools boundary."""

    def __init__(self):
        self.invoked = []
        self.completed = []
        self.seconds_remaining = 120

    def execute(self, statement, parameters):
        sql = str(statement)
        if "min(created_at)" in sql:
            return SimpleNamespace(scalar_one=lambda: self.seconds_remaining)
        if "SELECT metadata" in sql:
            return SimpleNamespace(scalars=lambda: iter(self.invoked))
        if "sum((metadata->>'output_bytes')" in sql:
            return SimpleNamespace(
                scalar_one=lambda: sum(item["output_bytes"] for item in self.completed)
            )
        raise AssertionError("Unexpected query in the synthetic tool fixture.")


@pytest.fixture
def simulated_tool_ledger(monkeypatch):
    ledger = FakeAuditConnection()

    @contextmanager
    def transaction(_tenant):
        yield ledger

    def record(_connection, _actor, action, resource_id, policy_revision, metadata):
        assert resource_id == "run-fixture" and policy_revision == 1
        (ledger.invoked if action == "tool.invoked" else ledger.completed).append(metadata)

    monkeypatch.setattr(tools, "transaction", transaction)
    monkeypatch.setattr(tools, "record_action", record)
    context = SimpleNamespace(
        lease=synthetic_lease(), authorize=lambda _connection: "fixture-actor"
    )
    return ledger, context


def test_read_tool_quota_survives_recreated_executor_and_failed_attempts(simulated_tool_ledger):
    ledger, context = simulated_tool_ledger
    executed = []

    def failed_operation():
        executed.append("failed")
        raise Problem(404, "not_found", "Synthetic unavailable source.")

    for number in range(8):
        fresh = ReadTools(context)
        with pytest.raises(Problem) as caught:
            fresh._call(
                "read_evidence_span",
                ReadArguments(evidence_id=f"missing-{number}"),
                failed_operation,
            )
        assert caught.value.code == "not_found"
    assert len(ledger.invoked) == len(executed) == 8
    assert not ledger.completed
    with pytest.raises(Problem) as caught:
        ReadTools(context)._call(
            "search_evidence",
            SearchArguments(query="attempt-after-recreate"),
            lambda: executed.append("forbidden"),
        )
    assert caught.value.code == "tool_call_limit"
    assert len(executed) == 8


def test_tool_duplicate_and_output_limits_reject_before_return(simulated_tool_ledger):
    ledger, context = simulated_tool_ledger
    arguments = SearchArguments(query="same-untrusted-request")
    fresh = ReadTools(context)
    assert fresh._call("search_evidence", arguments, lambda: "bounded") == "bounded"
    with pytest.raises(Problem) as caught:
        ReadTools(context)._call(
            "search_evidence", arguments, lambda: pytest.fail("Duplicate executed")
        )
    assert caught.value.code == "tool_repeated"
    with pytest.raises(Problem) as caught:
        ReadTools(context)._call(
            "read_evidence_span",
            ReadArguments(evidence_id="too-large"),
            lambda: "x" * tools.MAX_OUTPUT_BYTES,
        )
    assert caught.value.code == "tool_output_limit"
    assert len(ledger.invoked) == 2 and len(ledger.completed) == 1


def test_durable_tool_deadline_is_not_reset_by_new_executor(simulated_tool_ledger):
    ledger, context = simulated_tool_ledger
    ledger.seconds_remaining = 0
    with pytest.raises(Problem) as caught:
        ReadTools(context)._call(
            "search_evidence",
            SearchArguments(query="untrusted text"),
            lambda: pytest.fail("Expired operation executed"),
        )
    assert caught.value.code == "tool_deadline"
    assert not ledger.invoked and not ledger.completed


def test_execution_context_cannot_change_snapshot_or_incident(monkeypatch):
    context = ExecutionContext(synthetic_lease(), "incident-fixture", "snapshot-fixture")
    monkeypatch.setattr(tools, "assert_publishable", lambda *_args: None)
    monkeypatch.setattr(tools, "actor_for_worker", lambda *_args: "actor-fixture")
    monkeypatch.setattr(
        tools,
        "authorize_run",
        lambda *_args: {"incident_id": "other-incident", "snapshot_id": "other-snapshot"},
    )
    with pytest.raises(Problem) as caught:
        context.authorize(object())
    assert caught.value.code == "tool_scope_changed"


def test_generation_context_rejects_duplicate_sources_and_undeclared_fields():
    request = adversarial.prepare().cases[0].generation_request.model_dump(mode="json")
    request["evidence"].append(copy.deepcopy(request["evidence"][0]))
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate(request)
    request["evidence"].pop()
    request["evidence"][1]["system_override"] = "malicious"
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate(request)
