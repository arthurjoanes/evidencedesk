import unittest
from unittest.mock import patch

import prepare_review_capture as capture


class ReviewCapturePreparationTests(unittest.TestCase):
    def test_generation_enabled_refuses_before_any_domain_write(self):
        with (
            patch.object(
                capture,
                "request",
                return_value={"runtime": {"generation_enabled": True, "provider": "azure_openai"}},
            ) as request,
            self.assertRaises(ValueError),
        ):
            capture.prepare("author", "reviewer", "run-1")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[1], "GET")

    def test_real_source_quote_and_all_claims_pass_through_distinct_reviewer(self):
        events = []
        count = [0]

        def request(client, method, path, **kwargs):
            events.append((client, method, path, kwargs))
            if path == "/auth/session":
                return {"runtime": {"generation_enabled": False, "provider": "disabled"}}
            if path.endswith("/evidence?limit=30"):
                return {"items": [{"id": "source-1"}]}
            if path.startswith("/evidence/"):
                return {"id": "source-1", "canonical_text": "Trecho real sintético."}
            if path == "/incidents/demo-aurora-01":
                return {"id": "demo-aurora-01", "evidence_snapshot_id": "snapshot-1"}
            if method == "POST" and path.endswith("/dossiers"):
                count[0] += 1
                return {"id": "dossier-" + str(count[0]), "current_revision_id": "revision-1"}
            if method == "GET" and "/revisions/" in path:
                return {
                    "id": "revision-1",
                    "etag": "actual-etag",
                    "review_status": "approved",
                    "claims": [{"claim_id": "claim-1"}, {"claim_id": "claim-2"}],
                }
            return {}

        with patch.object(capture, "request", side_effect=request):
            case = capture.prepare("author", "reviewer", "run-1")
        review = next(row for row in events if row[2].endswith("/reviews"))
        self.assertEqual(review[0], "reviewer")
        self.assertEqual(review[3]["json"]["claim_ids"], ["claim-1", "claim-2"])
        self.assertEqual(review[3]["headers"], {"If-Match": "actual-etag"})
        create = next(row for row in events if row[1] == "POST" and row[2].endswith("/dossiers"))
        self.assertIn("Trecho real sintético.", create[3]["json"]["claims"][0]["text"])
        self.assertEqual(case["approved"]["expected_source_ids"], ["source-1"])
        self.assertNotEqual(case["approved"]["dossier_id"], case["conflict"]["dossier_id"])


if __name__ == "__main__":
    unittest.main()
