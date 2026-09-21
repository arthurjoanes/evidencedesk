import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "receiver", Path(__file__).resolve().parents[1] / "infra/observability/receiver.py"
)
receiver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receiver)


class ReceiverBoundaryTests(unittest.TestCase):
    def test_sensitive_and_unbounded_metadata_is_discarded(self):
        event = receiver.sanitize(
            {
                "status": "firing",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {"alertname": "Á" * 500, "authorization": "secret"},
                        "annotations": {"prompt": "private"},
                    }
                ],
            }
        )
        self.assertEqual(event["alerts"][0]["labels"], {"alertname": "Á" * 160})
        self.assertNotIn("annotations", event["alerts"][0])

    def test_invalid_webhooks_do_not_look_like_recovery(self):
        for payload in [
            None,
            [],
            {},
            {"status": "unknown", "alerts": []},
            {"status": "resolved", "alerts": []},
            {"status": "firing", "alerts": ["not an alert"]},
        ]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                receiver.sanitize(payload)


if __name__ == "__main__":
    unittest.main()
