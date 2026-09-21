"""Accounting boundaries use real transactions and never call a provider."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from test_investigation_workflow import prepare_run

from evidencedesk.config import get_settings
from evidencedesk.database import get_engine, transaction
from evidencedesk.errors import Problem
from evidencedesk.investigations import budget
from evidencedesk.jobs.service import acquire
from evidencedesk.model_runtime.contracts import TokenUsage
from evidencedesk.model_runtime.release import load_release

pytestmark = pytest.mark.integration


def setup_budget(workspace, monkeypatch):
    _, tenant, run = prepare_run(workspace, monkeypatch)
    lease = acquire(tenant, "budget-test")
    assert lease is not None
    with transaction(tenant) as connection:
        release = load_release(
            connection.execute(
                text(
                    "SELECT model_release FROM investigation_runs WHERE tenant_id=:tenant AND id=:run"
                ),
                {"tenant": tenant, "run": run["id"]},
            ).scalar_one()
        )
    reservation = release.limits.max_input_tokens + release.limits.max_output_tokens
    monkeypatch.setenv("ED_AI_PERIOD_TOKEN_BUDGET", str(reservation))
    get_settings.cache_clear()
    return tenant, lease, release, reservation


def test_month_rollover_preserves_unknown_and_late_usage_in_original_period(workspace, monkeypatch):
    tenant, lease, release, reservation = setup_budget(workspace, monkeypatch)
    january, february, march = date(2030, 1, 1), date(2030, 2, 1), date(2030, 3, 1)
    monkeypatch.setattr(budget, "current_budget_period", lambda _: january)
    first = budget.authorize_dispatch(lease, release, 1000)
    budget.reconcile_usage(
        lease,
        first,
        TokenUsage(status="reported", input_tokens=reservation, output_tokens=0),
        "fixture",
        failed=False,
    )
    with pytest.raises(Problem) as exhausted:
        budget.authorize_dispatch(lease, release, 1000)
    assert exhausted.value.code == "token_budget_exhausted"

    monkeypatch.setattr(budget, "current_budget_period", lambda _: february)
    second = budget.authorize_dispatch(lease, release, 1000)
    budget.reconcile_usage(lease, second, None, None, failed=True, error_code="provider_timeout")
    budget.reconcile_usage(lease, second, None, None, failed=True, error_code="provider_timeout")
    monkeypatch.setattr(budget, "current_budget_period", lambda _: march)
    # Restarting client/settings connections cannot erase a persisted reservation.
    get_engine().dispose()
    get_settings.cache_clear()
    with pytest.raises(Problem) as carried:
        budget.authorize_dispatch(lease, release, 1000)
    assert carried.value.code == "token_budget_exhausted"
    with transaction(tenant) as connection:
        position = budget.budget_position(connection, tenant)
        assert position.carried_reserved_tokens == reservation
        assert position.current_reported_tokens == 0

    budget.reconcile_usage(
        lease,
        second,
        TokenUsage(status="reported", input_tokens=100, output_tokens=80),
        "late-fixture",
        failed=False,
    )
    third = budget.authorize_dispatch(lease, release, 1000)
    budget.reconcile_usage(
        lease,
        third,
        TokenUsage(status="reported", input_tokens=0, output_tokens=0),
        "third-fixture",
        failed=False,
    )
    with transaction(tenant) as connection:
        periods = connection.execute(
            text(
                "SELECT period_start,reserved_tokens,reported_tokens FROM token_budget_periods WHERE tenant_id=:tenant ORDER BY period_start"
            ),
            {"tenant": tenant},
        ).all()
        assert periods == [(january, 0, reservation), (february, 0, 180), (march, 0, 0)]
        call = connection.execute(
            text(
                "SELECT budget_period,error_code,status FROM provider_calls WHERE tenant_id=:tenant AND id=:id"
            ),
            {"tenant": tenant, "id": second},
        ).one()
        assert call == (february, "provider_timeout", "reported")
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM provider_budget_events WHERE tenant_id=:tenant AND call_id=:id AND kind='unknown'"
                ),
                {"tenant": tenant, "id": second},
            ).scalar_one()
            == 1
        )
        assert budget.budget_position(connection, tenant).committed_tokens == 0


def test_concurrent_reconciliation_is_idempotent_and_ledger_matches_balance(workspace, monkeypatch):
    tenant, lease, release, _ = setup_budget(workspace, monkeypatch)
    call = budget.authorize_dispatch(lease, release, 1000)

    def settle():
        budget.reconcile_usage(
            lease,
            call,
            TokenUsage(status="reported", input_tokens=100, output_tokens=80),
            "fixture",
            failed=False,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(settle) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)
    with transaction(tenant) as connection:
        assert budget.budget_position(connection, tenant).committed_tokens == 180
        assert connection.execute(
            text(
                "SELECT sum(reserved_delta),sum(reported_delta) FROM provider_budget_events WHERE tenant_id=:tenant"
            ),
            {"tenant": tenant},
        ).one() == (0, 180)
        assert connection.execute(
            text("SELECT token_reserved,token_reported FROM tenant_policy WHERE tenant_id=:tenant"),
            {"tenant": tenant},
        ).one() == (0, 180)
    with transaction(workspace["tenants"][1]) as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM token_budget_periods")).scalar_one() == 0
        )
        assert (
            connection.execute(text("SELECT count(*) FROM provider_budget_events")).scalar_one()
            == 0
        )


def test_app_cannot_change_accounting_history_or_move_a_call_to_another_month(
    workspace, monkeypatch
):
    tenant, lease, release, _ = setup_budget(workspace, monkeypatch)
    call = budget.authorize_dispatch(lease, release, 1000)
    budget.reconcile_usage(
        lease,
        call,
        TokenUsage(status="reported", input_tokens=1, output_tokens=1),
        "fixture",
        failed=False,
    )
    for statement in (
        "UPDATE provider_budget_events SET reserved_delta=0",
        "DELETE FROM provider_budget_events",
    ):
        with pytest.raises(ProgrammingError):
            with transaction(tenant) as connection:
                connection.execute(text(statement))
    with pytest.raises(IntegrityError):
        with transaction(tenant) as connection:
            connection.execute(
                text(
                    "UPDATE provider_calls SET budget_period=budget_period+interval '1 month' WHERE tenant_id=:tenant AND id=:id"
                ),
                {"tenant": tenant, "id": call},
            )
