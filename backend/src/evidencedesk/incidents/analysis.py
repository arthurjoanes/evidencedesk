from collections import Counter


def assessment_summary(rows: list[dict]) -> dict:
    counts = Counter(row["status"] for row in rows)
    affected = {
        row["order_reference"]
        for row in rows
        if row["status"] == "divergence" and row["order_reference"] is not None
    }
    return {
        "assessments": len(rows),
        "orders_with_divergence": len(affected),
        "uncorrelated_assessments": sum(row["order_reference"] is None for row in rows),
        "by_status": {
            status: counts[status] for status in ("divergence", "observation", "not_evaluable")
        },
    }
