import json

from sqlalchemy import Connection, text


def update_steps(
    connection: Connection, tenant_id: str, run_id: str, status: str, stage: str | None = None
) -> None:
    """Update the small current-stage projection in the same transaction as the job."""
    row = (
        connection.execute(
            text(
                "SELECT steps,now() AS now FROM investigation_runs WHERE tenant_id=:tenant AND id=:id FOR UPDATE"
            ),
            {"tenant": tenant_id, "id": run_id},
        )
        .mappings()
        .one()
    )
    now = row["now"].isoformat()
    steps = row["steps"]
    for step in steps:
        if step["status"] == "running":
            step["status"] = "succeeded" if stage else status
            step["completed_at"] = now
    if stage:
        existing = next((item for item in steps if item["key"] == stage), None)
        current = {"key": stage, "status": "running", "started_at": now, "completed_at": None}
        if existing is None:
            steps.append(current)
        else:
            existing.update(current)
    connection.execute(
        text(
            "UPDATE investigation_runs SET steps=CAST(:steps AS jsonb) WHERE tenant_id=:tenant AND id=:id"
        ),
        {"tenant": tenant_id, "id": run_id, "steps": json.dumps(steps)},
    )
