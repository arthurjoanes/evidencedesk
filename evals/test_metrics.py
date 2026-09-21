import pytest

from evals.build_dataset import build_cases
from evals.metrics import CaseResult, retrieval_metrics, summarize, validate_splits


def test_failed_cases_do_not_disappear_from_end_to_end_denominator():
    result = summarize(
        [
            CaseResult("1", "incident-a", "known", "answered", True),
            CaseResult("2", "incident-b", "known", "failed", True),
        ]
    )
    assert result["metrics"]["end_to_end_success"] == {
        "numerator": 1,
        "denominator": 2,
        "value": 0.5,
    }
    assert result["funnel"]["failed"] == 1


def test_empty_or_unadjudicated_data_cannot_pass_human_gate():
    assert summarize([])["gates"]["human_support"] == "inconclusive"
    rows = [
        CaseResult(
            str(i),
            str(i),
            "category",
            "answered",
            True,
            human_support_labels=(True,),
            human_adjudicated=False,
        )
        for i in range(40)
    ]
    assert summarize(rows)["gates"]["human_support"] == "inconclusive"


def test_duplicate_retrieved_ids_do_not_inflate_metrics():
    result = retrieval_metrics(["a", "a"], {"a": 2, "b": 2})
    assert result["recall"] == 0.5
    assert result["ndcg"] <= 1


def test_correct_and_incorrect_abstention_use_distinct_denominators():
    result = summarize(
        [
            CaseResult("1", "a", "known", "abstained", False),
            CaseResult("2", "b", "known", "abstained", True),
            CaseResult("3", "c", "known", "answered", True),
        ]
    )
    assert result["metrics"]["correct_abstention"]["value"] == 1
    assert result["metrics"]["incorrect_abstention"]["value"] == 0.5


def test_semantic_sample_must_have_independent_incidents_and_category_coverage():
    rows = [
        CaseResult(
            str(i),
            "same-incident",
            "a",
            "answered",
            True,
            human_support_labels=(True,),
            human_adjudicated=True,
        )
        for i in range(30)
    ]
    assert summarize(rows)["gates"]["human_support"] == "inconclusive"


def test_dataset_groups_are_isolated_and_reserved_families_absent_from_dev():
    rows = build_cases()
    validate_splits(rows)
    dev_families = {row["scenario_family"] for row in rows if row["split"] == "dev"}
    new_families = {
        row["scenario_family"]
        for row in rows
        if row["generalization"] == "unseen_family"
    }
    assert dev_families.isdisjoint(new_families)
    assert len(rows) == 120


def test_split_validator_rejects_document_lineage_crossing_splits():
    rows = build_cases()
    rows[-1]["document_lineage"] = rows[0]["document_lineage"]
    with pytest.raises(ValueError, match="Vazamento"):
        validate_splits(rows)
