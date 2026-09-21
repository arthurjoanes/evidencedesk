"""Small, process-local summaries; authorization and mutable metadata stay outside."""

import json
from collections import OrderedDict
from collections.abc import Callable
from threading import Event, Lock
from time import monotonic

from evidencedesk.errors import Problem


class SummaryCache:
    def __init__(
        self,
        *,
        capacity: int = 128,
        max_bytes: int = 65536,
        ttl: float = 60,
        wait_seconds: float = 5,
        clock: Callable[[], float] = monotonic,
    ):
        self.capacity = capacity
        self.max_bytes = max_bytes
        self.ttl = ttl
        self.wait_seconds = wait_seconds
        self.clock = clock
        self._lock = Lock()
        self._entries: OrderedDict[tuple, tuple[float, bytes]] = OrderedDict()
        self._pending: dict[tuple, Event] = {}

    def get(self, key: tuple, compute: Callable[[], dict]) -> dict:
        while True:
            with self._lock:
                cached = self._entries.get(key)
                if cached is not None:
                    expires_at, encoded = cached
                    if expires_at > self.clock():
                        self._entries.move_to_end(key)
                        return json.loads(encoded)
                    del self._entries[key]
                pending = self._pending.get(key)
                if pending is None:
                    if len(self._pending) >= 32:
                        raise self._busy()
                    pending = self._pending[key] = Event()
                    break
            # Only identical work waits. Different tenants never share a computation lock.
            if not pending.wait(self.wait_seconds):
                raise self._busy()
        try:
            value = compute()
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
            if len(encoded) <= self.max_bytes:
                with self._lock:
                    self._entries[key] = (self.clock() + self.ttl, encoded)
                    while len(self._entries) > self.capacity:
                        self._entries.popitem(last=False)
            return value
        finally:
            with self._lock:
                del self._pending[key]
                pending.set()

    @staticmethod
    def _busy() -> Problem:
        return Problem(
            503, "summary_busy", "Resumo ocupado. Tente novamente depois.", retryable=True
        )


summaries = SummaryCache()
