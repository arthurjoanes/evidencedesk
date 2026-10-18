from contextlib import nullcontext
from types import SimpleNamespace

from evidencedesk.incidents import routes
from evidencedesk.incidents.analysis import assessment_summary


def test_multiple_findings_do_not_count_the_same_order_twice():
    rows = [
        {"order_reference": "PED-1", "status": "divergence"},
        {"order_reference": "PED-1", "status": "divergence"},
        {"order_reference": "PED-2", "status": "observation"},
        {"order_reference": None, "status": "not_evaluable"},
    ]
    assert assessment_summary(rows) == {
        "assessments": 4,
        "orders_with_divergence": 1,
        "uncorrelated_assessments": 1,
        "by_status": {"divergence": 2, "observation": 1, "not_evaluable": 1},
    }


def test_empty_assessments_have_zero_counts():
    assert assessment_summary([]) == {
        "assessments": 0,
        "orders_with_divergence": 0,
        "uncorrelated_assessments": 0,
        "by_status": {"divergence": 0, "observation": 0, "not_evaluable": 0},
    }


def test_page_summary_uses_all_filtered_rows_before_cursor(monkeypatch):
    class Row:
        def __init__(self, identifier, order):
            self.id = identifier
            self.order_reference = order

        def model_dump(self, **kwargs):
            return {"id": self.id, "order_reference": self.order_reference, "status": "divergence"}

    result = SimpleNamespace(
        evidence_snapshot_id="snapshot",
        coverage=[],
        divergences=[Row("one", "PED-1"), Row("two", "PED-1"), Row("three", "PED-2")],
    )
    monkeypatch.setattr(routes, "transaction", lambda _: nullcontext(None))
    monkeypatch.setattr(routes, "load_reconciliation", lambda *args: result)
    monkeypatch.setattr(routes, "decode_cursor", lambda *args: "one")
    actor = SimpleNamespace(tenant_id="tenant", id="user")
    response = routes.reconciliation_page(
        "incident", actor, "snapshot", "PED-1", "cursor", 1, timeline=False
    )
    assert len(response["items"]) == 1
    assert response["total"] == 2
    assert response["summary"]["assessments"] == 2
    assert response["summary"]["orders_with_divergence"] == 1
