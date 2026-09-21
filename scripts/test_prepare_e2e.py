import os
import unittest
from unittest.mock import patch

import prepare_e2e


class BrowserFixtureBoundaryTests(unittest.TestCase):
    def test_missing_isolation_or_provider_key_rejects_before_database_access(self):
        for environment in [
            {},
            {"ED_E2E_MODE": "true", "ED_AI_PROVIDER": "azure_openai"},
            {
                "ED_E2E_MODE": "true",
                "ED_AI_PROVIDER": "disabled",
                "AZURE_OPENAI_API_KEY": "synthetic",
            },
        ]:
            with (
                self.subTest(environment=environment),
                patch.dict(os.environ, environment, clear=True),
                patch.object(prepare_e2e, "transaction") as transaction,
            ):
                with self.assertRaises(RuntimeError):
                    prepare_e2e.main()
                transaction.assert_not_called()
