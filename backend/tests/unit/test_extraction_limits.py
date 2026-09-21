import pytest

from evidencedesk.errors import Problem
from evidencedesk.ingestion.limits import ExtractionBudget


def test_valid_files_cannot_exceed_aggregate_row_limit():
    budget = ExtractionBudget()
    budget.include({"rows": [None] * 30_000})
    with pytest.raises(Problem, match="extraction_budget_exceeded"):
        budget.include({"rows": [None] * 20_001})
    assert budget.rows == 30_000


def test_text_limit_counts_utf8_bytes_across_pages_and_files():
    budget = ExtractionBudget()
    page = "á" * 524_288
    for _ in range(8):
        budget.include({"pages": [page]})
    with pytest.raises(Problem, match="extraction_budget_exceeded"):
        budget.include({"pages": ["x"]})


def test_derived_chunk_count_has_its_own_limit():
    budget = ExtractionBudget()
    budget.include({}, 49_999)
    budget.include({}, 1)
    with pytest.raises(Problem, match="extraction_budget_exceeded"):
        budget.include({}, 1)
