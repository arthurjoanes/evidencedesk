from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from evidencedesk import database
from evidencedesk.errors import Problem
from evidencedesk.incidents.summaries import SummaryCache


def test_summary_ttl_eviction_and_mutation_isolation():
    now = [0.0]
    cache = SummaryCache(capacity=2, ttl=10, clock=lambda: now[0])
    calls = []

    def compute():
        calls.append(1)
        return {"counts": {"orders": len(calls)}}

    cache.get(("a",), compute)["counts"]["orders"] = -1
    assert cache.get(("a",), compute)["counts"]["orders"] == 1
    cache.get(("b",), compute)
    cache.get(("c",), compute)
    assert cache.get(("a",), compute)["counts"]["orders"] == 4
    now[0] = 11
    assert cache.get(("a",), compute)["counts"]["orders"] == 5


def test_single_flight_and_failure_release():
    cache = SummaryCache()
    started, release = Event(), Event()
    calls = []

    def compute():
        calls.append(1)
        started.set()
        assert release.wait(2)
        return {"orders": 3}

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(cache.get, ("tenant", "snapshot", 1), compute) for _ in range(6)]
        assert started.wait(2)
        release.set()
        assert [future.result() for future in futures] == [{"orders": 3}] * 6
    assert len(calls) == 1

    def fail():
        raise ValueError("uncacheable failure")

    with pytest.raises(ValueError):
        cache.get(("failed",), fail)
    assert cache.get(("failed",), lambda: {"recovered": True}) == {"recovered": True}


def test_wait_is_bounded_and_oversized_results_are_not_retained():
    cache = SummaryCache(max_bytes=10, wait_seconds=0.01)
    started, release = Event(), Event()

    def compute():
        started.set()
        assert release.wait(2)
        return {"orders": 12345}

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(cache.get, ("busy",), compute)
        assert started.wait(2)
        with pytest.raises(Problem) as error:
            cache.get(("busy",), compute)
        assert error.value.status == 503 and error.value.retryable
        release.set()
        future.result()
    assert cache.get(("busy",), lambda: {"new": 1}) == {"new": 1}


def test_exhausted_real_pool_returns_safe_retryable_503(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=QueuePool, pool_size=1, max_overflow=0, pool_timeout=0.01
    )
    monkeypatch.setattr(database, "get_engine", lambda: engine)
    with engine.connect(), pytest.raises(Problem) as error, database.transaction():
        pytest.fail("An exhausted pool must not yield a connection")
    assert (error.value.status, error.value.code, error.value.retryable) == (
        503,
        "database_busy",
        True,
    )
    engine.dispose()
