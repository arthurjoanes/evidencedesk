"""Tool authority and budgets use the same real application role as HTTP jobs."""

from dataclasses import replace

import pytest
from sqlalchemy import text
from test_investigation_workflow import prepare_run

from evidencedesk.database import get_engine, transaction
from evidencedesk.errors import Problem
from evidencedesk.investigations.tools import (
    Arguments,
    ExecutionContext,
    ReadArguments,
    ReadTools,
    SearchArguments,
)
from evidencedesk.jobs.service import acquire

pytestmark = pytest.mark.integration


def setup_tools(workspace, monkeypatch):
    client, tenant, run = prepare_run(workspace, monkeypatch)
    lease = acquire(tenant, "tool-test")
    assert lease is not None
    context = ExecutionContext.from_lease(lease)
    return client, tenant, run, context


def test_tools_preserve_authority_and_count_failed_attempts_across_executors(
    workspace, monkeypatch
):
    _, tenant, run, context = setup_tools(workspace, monkeypatch)
    tool = ReadTools(context)
    results = tool.search(SearchArguments(query="pagamento"))
    assert results and "pagamento" in results[0].text
    with pytest.raises(Problem, match="tool_repeated") as repeated:
        ReadTools(context).search(SearchArguments(query="pagamento"))
    assert repeated.value.code == "tool_repeated"
    for offset in range(7):
        with pytest.raises(Problem) as missing:
            ReadTools(context).read_span(ReadArguments(evidence_id=f"foreign-or-missing-{offset}"))
        assert missing.value.status == 404
    with pytest.raises(Problem) as exhausted:
        ReadTools(context).search(SearchArguments(query="pedido"))
    assert exhausted.value.code == "tool_call_limit"
    with transaction(tenant) as connection:
        metadata = (
            connection.execute(
                text(
                    "SELECT metadata FROM audit_events WHERE tenant_id=:tenant AND resource_id=:run AND action='tool.invoked'"
                ),
                {"tenant": tenant, "run": run["id"]},
            )
            .scalars()
            .all()
        )
    assert len(metadata) == 8
    assert all(set(item) == {"tool", "fingerprint", "attempt"} for item in metadata)


def test_revocation_during_model_call_prevents_tool_output_and_holds_no_pool(
    workspace, monkeypatch
):
    _, tenant, _, context = setup_tools(workspace, monkeypatch)

    class RevokeDuringEncode:
        def encode_query(self, query):
            assert get_engine().pool.checkedout() == 0
            with workspace["admin"].begin() as connection:
                connection.execute(
                    text("UPDATE tenant_policy SET revision=revision+1 WHERE tenant_id=:tenant"),
                    {"tenant": tenant},
                )
                connection.execute(
                    text("DELETE FROM collection_grants WHERE tenant_id=:tenant AND user_id=:user"),
                    {"tenant": tenant, "user": context.lease.actor_id},
                )
            return [1.0] + [0.0] * 383

    with pytest.raises(Problem) as denied:
        ReadTools(context, mode="hybrid", models=RevokeDuringEncode()).search(
            SearchArguments(query="pagamento")
        )
    assert denied.value.code in {"policy_changed", "access_changed", "not_found"}
    with transaction(tenant) as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM audit_events WHERE tenant_id=:tenant AND action='tool.completed'"
                ),
                {"tenant": tenant},
            ).scalar_one()
            == 0
        )


def test_tool_does_not_accept_a_forged_snapshot_context(workspace, monkeypatch):
    _, _, _, context = setup_tools(workspace, monkeypatch)
    forged = ExecutionContext(context.lease, context.incident_id, "different-snapshot")
    with pytest.raises(Problem) as denied:
        ReadTools(forged).search(SearchArguments(query="pagamento"))
    assert denied.value.code == "tool_scope_changed"


def test_tool_deadline_survives_executor_restart(workspace, monkeypatch):
    _, tenant, run, context = setup_tools(workspace, monkeypatch)
    ReadTools(context).search(SearchArguments(query="pagamento"))
    with workspace["admin"].begin() as connection:
        connection.execute(
            text(
                "UPDATE audit_events SET created_at=now()-interval '121 seconds' WHERE tenant_id=:tenant AND resource_id=:run AND action='tool.invoked'"
            ),
            {"tenant": tenant, "run": run["id"]},
        )
        connection.execute(
            text(
                "UPDATE jobs SET fencing_token=fencing_token+1 WHERE tenant_id=:tenant AND id=:id"
            ),
            {"tenant": tenant, "id": context.lease.job_id},
        )
    context = replace(context, lease=replace(context.lease, token=context.lease.token + 1))
    with pytest.raises(Problem) as caught:
        ReadTools(context).search(SearchArguments(query="pedido"))
    assert caught.value.code == "tool_deadline"


def test_tool_bytes_accumulate_across_executors_and_reject_before_return(workspace, monkeypatch):
    _, _, _, context = setup_tools(workspace, monkeypatch)
    assert len(ReadTools(context)._call("fixture_first", Arguments(), lambda: "x" * 40000)) == 40000
    with pytest.raises(Problem) as caught:
        ReadTools(context)._call("fixture_second", Arguments(), lambda: "x" * 25000)
    assert caught.value.code == "tool_output_limit"
