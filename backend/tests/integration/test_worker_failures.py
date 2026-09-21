"""Two OS processes acquire the same real queue; expiration uses a controlled DB clock."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from test_monthly_budget import setup_budget

from evidencedesk.database import lock_policy, transaction
from evidencedesk.errors import Problem
from evidencedesk.identity.service import actor_for_worker
from evidencedesk.investigations.budget import authorize_dispatch, reconcile_usage
from evidencedesk.investigations.processing import checkpoint
from evidencedesk.jobs.service import Lease, acquire, assert_publishable, complete, enqueue
from evidencedesk.model_runtime.contracts import TokenUsage

pytestmark = pytest.mark.integration


def test_dead_process_is_reacquired_and_late_worker_cannot_complete(workspace):
    tenant = workspace["tenants"][0]
    with transaction(tenant) as connection:
        policy = lock_policy(connection, tenant, mutation=True)
        actor = actor_for_worker(connection, tenant, tenant + "-author")
        enqueue(connection, actor, "ingestion", "isolated-lease-fixture", policy)
    script = """
import json, os, sys
from dataclasses import asdict
from evidencedesk.jobs.service import acquire
lease = acquire(sys.argv[1], sys.argv[2])
print(json.dumps(asdict(lease) if lease else None), flush=True)
os._exit(17)
"""

    def child(number):
        result = subprocess.run(
            [sys.executable, "-c", script, tenant, f"child-{number}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert result.returncode == 17, result.stderr
        return json.loads(result.stdout)

    with ThreadPoolExecutor(2) as pool:
        acquired = [result for result in pool.map(child, range(2)) if result]
    assert len(acquired) == 1
    old = Lease(**acquired[0])
    with workspace["admin"].begin() as connection:
        connection.execute(
            text(
                "UPDATE jobs SET lease_until=now()-interval '1 second' WHERE tenant_id=:tenant AND id=:id"
            ),
            {"tenant": tenant, "id": old.job_id},
        )
    replacement = acquire(tenant, "replacement")
    assert replacement is not None and replacement.token == old.token + 1
    with transaction(tenant) as connection, pytest.raises(Problem, match="lease_lost"):
        complete(connection, old)
    with transaction(tenant) as connection:
        complete(connection, replacement)
    with transaction(tenant) as connection, pytest.raises(Problem, match="lease_lost"):
        assert_publishable(connection, old)


@pytest.mark.parametrize("reported", [False, True])
def test_expired_paid_attempt_is_not_repeated_even_after_usage_was_reported(
    workspace, monkeypatch, reported
):
    tenant, lease, release, _ = setup_budget(workspace, monkeypatch)
    checkpoint(lease, "generation")
    call = authorize_dispatch(lease, release, 1000)
    if reported:
        reconcile_usage(
            lease,
            call,
            TokenUsage(status="reported", input_tokens=50, output_tokens=20),
            "fixture-only",
            failed=False,
        )
    with workspace["admin"].begin() as connection:
        connection.execute(
            text(
                "UPDATE jobs SET lease_until=now()-interval '1 second' WHERE tenant_id=:tenant AND id=:id"
            ),
            {"tenant": tenant, "id": lease.job_id},
        )
    assert acquire(tenant, "replacement") is None
    with transaction(tenant) as connection:
        state = (
            connection.execute(
                text("SELECT state,error FROM jobs WHERE tenant_id=:tenant AND id=:id"),
                {"tenant": tenant, "id": lease.job_id},
            )
            .mappings()
            .one()
        )
        assert (
            state["state"] == "failed" and state["error"]["code"] == "provider_result_unpublished"
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM provider_calls WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            ).scalar_one()
            == 1
        )
        steps = connection.execute(
            text("SELECT steps FROM investigation_runs WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": tenant, "id": lease.resource_id},
        ).scalar_one()
        assert steps[0]["status"] == "failed"
        assert (
            connection.execute(
                text("SELECT count(*) FROM run_events WHERE tenant_id=:tenant AND type='terminal'"),
                {"tenant": tenant},
            ).scalar_one()
            == 1
        )
