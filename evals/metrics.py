"""Metrics with explicit denominators; synthetic references never count as human review."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    scenario_instance: str
    category: str
    state: Literal["not_run", "failed", "answered", "abstained"]
    answerable: bool
    relevant_grades: Mapping[str, int] = field(default_factory=dict)
    retrieved_ids: tuple[str, ...] = ()
    human_support_labels: tuple[bool, ...] | None = None
    required_facts: int = 0
    covered_facts: int = 0
    human_adjudicated: bool = False
    invalid_citations: int = 0
    tenant_leaks: int = 0
    isolation_checked: bool = False
    citations_checked: bool = False
    deterministic_numbers_checked: int = 0
    deterministic_numbers_matching: int = 0
    latency_ms: float | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.covered_facts <= self.required_facts:
            raise ValueError("Cobertura de fatos inválida.")
        if (
            not 0
            <= self.deterministic_numbers_matching
            <= self.deterministic_numbers_checked
        ):
            raise ValueError("Contagem de números verificados inválida.")
        if self.invalid_citations < 0 or self.tenant_leaks < 0:
            raise ValueError("Contagens não podem ser negativas.")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("Latência não pode ser negativa.")


def ratio(numerator: float, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def retrieval_metrics(
    retrieved: Sequence[str], grades: Mapping[str, int], k: int = 10
) -> dict:
    if k < 1 or any(grade < 0 for grade in grades.values()):
        raise ValueError("k e graus de relevância precisam ser válidos.")
    # Duplicate IDs must not earn relevance repeatedly.
    unique = list(dict.fromkeys(retrieved))[:k]
    relevant = {item for item, grade in grades.items() if grade > 0}
    recall = len(set(unique) & relevant) / len(relevant) if relevant else None
    reciprocal = next(
        (1 / rank for rank, item in enumerate(unique, 1) if item in relevant), 0.0
    )
    dcg = sum(
        (2 ** grades.get(item, 0) - 1) / math.log2(rank + 1)
        for rank, item in enumerate(unique, 1)
    )
    ideal = sum(
        (2**grade - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(sorted(grades.values(), reverse=True)[:k], 1)
    )
    return {
        "recall": recall,
        "mrr": reciprocal if relevant else None,
        "ndcg": dcg / ideal if ideal else None,
    }


def summarize(
    results: Sequence[CaseResult], *, required_categories: set[str] | None = None
) -> dict:
    if len({result.case_id for result in results}) != len(results):
        raise ValueError("IDs de casos duplicados distorcem denominadores.")
    states = Counter(result.state for result in results)
    eligible = [
        result
        for result in results
        if any(grade > 0 for grade in result.relevant_grades.values())
    ]
    retrieved = [
        retrieval_metrics(result.retrieved_ids, result.relevant_grades)
        for result in eligible
    ]
    answerable = [result for result in results if result.answerable]
    unanswerable = [result for result in results if not result.answerable]
    adjudicated = [
        result
        for result in results
        if result.human_adjudicated and result.state == "answered"
    ]
    support_labels = [
        label for result in adjudicated for label in (result.human_support_labels or ())
    ]
    counts = {
        "planned": len(results),
        "executed": len(results) - states["not_run"],
        "failed": states["failed"],
        "answered": states["answered"],
        "abstained": states["abstained"],
        "adjudicated": len(adjudicated),
    }
    semantic_categories = required_categories or {result.category for result in results}
    human_gate_eligible = (
        len(adjudicated) >= 30
        and len({result.scenario_instance for result in adjudicated}) >= 15
        and semantic_categories <= {result.category for result in adjudicated}
        and bool(support_labels)
    )
    metrics = {
        "end_to_end_success": ratio(
            sum(
                (result.state == "answered" and result.answerable)
                or (result.state == "abstained" and not result.answerable)
                for result in results
            ),
            len(results),
        ),
        "retrieval_recall_at_10": ratio(
            sum(row["recall"] for row in retrieved), len(eligible)
        ),
        "retrieval_mrr_at_10": ratio(
            sum(row["mrr"] for row in retrieved), len(eligible)
        ),
        "retrieval_ndcg_at_10": ratio(
            sum(row["ndcg"] for row in retrieved), len(eligible)
        ),
        "correct_abstention": ratio(
            sum(result.state == "abstained" for result in unanswerable),
            len(unanswerable),
        ),
        "incorrect_abstention": ratio(
            sum(result.state == "abstained" for result in answerable), len(answerable)
        ),
        "human_support_precision": ratio(sum(support_labels), len(support_labels)),
        "human_useful_coverage": ratio(
            sum(result.covered_facts for result in adjudicated),
            sum(result.required_facts for result in adjudicated),
        ),
        "deterministic_number_agreement": ratio(
            sum(result.deterministic_numbers_matching for result in results),
            sum(result.deterministic_numbers_checked for result in results),
        ),
    }

    def gate(
        metric: str, threshold: float, *, minimum: bool = True, eligible: bool = True
    ) -> str:
        value = metrics[metric]["value"]
        if value is None or not eligible:
            return "inconclusive"
        return (
            "passed"
            if (value >= threshold if minimum else value <= threshold)
            else "failed"
        )

    # A not-run suite cannot prove that zero observed leaks means isolation works.
    executed = counts["executed"]
    gates = {
        "known_tenant_isolation": "failed"
        if any(r.tenant_leaks for r in results)
        else (
            "passed" if any(r.isolation_checked for r in results) else "inconclusive"
        ),
        "valid_citations": "failed"
        if any(r.invalid_citations for r in results)
        else (
            "passed" if any(r.citations_checked for r in results) else "inconclusive"
        ),
        "retrieval_recall": gate(
            "retrieval_recall_at_10",
            0.85,
            eligible=executed == len(results) and bool(results),
        ),
        "human_support": gate(
            "human_support_precision", 0.90, eligible=human_gate_eligible
        ),
        "correct_abstention": gate(
            "correct_abstention",
            0.80,
            eligible=executed == len(results) and bool(results),
        ),
        "incorrect_abstention": gate(
            "incorrect_abstention",
            0.20,
            minimum=False,
            eligible=executed == len(results) and bool(results),
        ),
        "useful_coverage": gate(
            "human_useful_coverage", 0.80, eligible=human_gate_eligible
        ),
        "deterministic_numbers": gate("deterministic_number_agreement", 1),
    }
    return {
        "funnel": counts,
        "metrics": metrics,
        "gates": gates,
        "human_evidence": {
            "responses": len(adjudicated),
            "independent_incidents": len({r.scenario_instance for r in adjudicated}),
            "categories": sorted({r.category for r in adjudicated}),
            "eligible": human_gate_eligible,
        },
    }


def validate_splits(cases: Sequence[dict]) -> None:
    seen: dict[tuple[str, str], str] = {}
    ids = set()
    for case in cases:
        if case["case_id"] in ids:
            raise ValueError("case_id duplicado.")
        ids.add(case["case_id"])
        for key in ("scenario_instance", "query_group", "document_lineage"):
            values = case[key] if isinstance(case[key], list) else [case[key]]
            for value in values:
                identity = key, value
                if identity in seen and seen[identity] != case["split"]:
                    raise ValueError(f"Vazamento de grupo entre splits: {key}.")
                seen[identity] = case["split"]
