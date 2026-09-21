import unittest

import httpx
from check_observability import wait_for_trace


class TraceProbeTests(unittest.TestCase):
    def test_log_can_arrive_before_its_trace(self):
        statuses = iter([404, 404, 200])
        pauses = []
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(next(statuses), json={"batches": []})
            )
        ) as client:
            self.assertEqual(
                wait_for_trace(client, "0" * 32, attempts=3, pause=pauses.append).status_code, 200
            )
        self.assertEqual(pauses, [2, 2])

    def test_missing_trace_and_real_server_error_remain_failures(self):
        for status in [404, 503]:
            calls = []

            def handler(request, calls=calls, status=status):
                calls.append(1)
                return httpx.Response(status)

            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(httpx.HTTPStatusError):
                    wait_for_trace(client, "0" * 32, attempts=3, pause=lambda _: None)
            self.assertEqual(len(calls), 3 if status == 404 else 1)
