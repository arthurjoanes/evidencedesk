"""Exercise the Windows helper with real DPAPI and a fake startup command only."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
KEY = "fixture-only-not-a-provider-key-12345"
RUNTIME_VARIABLES = (
    "AZURE_OPENAI_API_KEY",
    "ED_AI_PROVIDER",
    "AZURE_OPENAI_BASE_URL",
    "AZURE_OPENAI_DEPLOYMENT",
    "ED_AZURE_OPENAI_ALLOWED_HOSTS",
)


@unittest.skipUnless(os.name == "nt" and PWSH, "Windows PowerShell 7 and DPAPI required")
class AzureRuntimeHelperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="ed azure helper ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env = os.environ | {
            "LOCALAPPDATA": str(self.root),
            "ED_HELPER_TEST_ROOT": str(self.root),
            "ED_HELPER_TEST_SCRIPT": str(ROOT / "scripts/azure_runtime.ps1"),
            "ED_HELPER_TEST_KEY": KEY,
            **{name: "previous-" + name for name in RUNTIME_VARIABLES},
        }
        self.metadata = self.root / "EvidenceDesk/azure-openai.runtime.json"

    def run_helper(self, *arguments, key=KEY):
        result = subprocess.run(
            [PWSH, "-NoProfile", "-File", str(ROOT / "scripts/azure_runtime.ps1"), *arguments],
            input=key + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
            timeout=30,
        )
        self.assertNotIn(KEY, result.stdout + result.stderr)
        return result

    def configure(self, endpoint="https://fixture-resource.openai.azure.com/openai/v1/"):
        result = self.run_helper(
            "-Action",
            "configure",
            "-Endpoint",
            endpoint,
            "-Deployment",
            "my-deployment",
            "-ReadKeyFromStdin",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def start_with_fake_cli(self, *, observability=False, fail=False):
        env_file = self.root / "runtime with spaces.env"
        env_file.write_text("ED_DB_APP_PASSWORD=fixture-database\n", encoding="utf-8")
        wrapper = self.root / "invoke.ps1"
        # Function resolution shadows Python; neither Docker nor a provider runs.
        wrapper.write_text(
            r"""
$ErrorActionPreference = 'Stop'
function python {
    $snapshot = @{
        Arguments = @($args)
        Endpoint = $env:AZURE_OPENAI_BASE_URL
        Deployment = $env:AZURE_OPENAI_DEPLOYMENT
        AllowedHosts = $env:ED_AZURE_OPENAI_ALLOWED_HOSTS
        Provider = $env:ED_AI_PROVIDER
        KeyMatches = ($env:AZURE_OPENAI_API_KEY -ceq $env:ED_HELPER_TEST_KEY)
    }
    $snapshot | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $env:ED_HELPER_TEST_ROOT 'invocation.json')
    $global:LASTEXITCODE = [int]$env:ED_HELPER_TEST_EXIT
}
$options = @{ Action = 'start'; EnvFile = (Join-Path $env:ED_HELPER_TEST_ROOT 'runtime with spaces.env') }
if ($env:ED_HELPER_TEST_OBSERVABILITY -eq 'true') { $options.Observability = $true }
& $env:ED_HELPER_TEST_SCRIPT @options
$result = $LASTEXITCODE
$restored = @{}
foreach ($name in @('AZURE_OPENAI_API_KEY', 'ED_AI_PROVIDER', 'AZURE_OPENAI_BASE_URL', 'AZURE_OPENAI_DEPLOYMENT', 'ED_AZURE_OPENAI_ALLOWED_HOSTS')) {
    $restored[$name] = ([Environment]::GetEnvironmentVariable($name, 'Process') -ceq ('previous-' + $name))
}
@{ ExitCode = $result; Restored = $restored } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $env:ED_HELPER_TEST_ROOT 'restored.json')
""",
            encoding="utf-8",
        )
        result = subprocess.run(
            [PWSH, "-NoProfile", "-File", str(wrapper)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env
            | {
                "ED_HELPER_TEST_EXIT": "7" if fail else "0",
                "ED_HELPER_TEST_OBSERVABILITY": "true" if observability else "false",
            },
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(KEY, result.stdout + result.stderr)
        invocation = json.loads((self.root / "invocation.json").read_text(encoding="utf-8-sig"))
        restored = json.loads((self.root / "restored.json").read_text(encoding="utf-8-sig"))
        self.assertTrue(all(restored["Restored"].values()))
        self.assertEqual(restored["ExitCode"], 7 if fail else 0)
        self.assertNotIn(KEY, " ".join(invocation["Arguments"]))
        return invocation

    def test_configuration_encrypts_key_with_endpoint_and_deployment(self):
        self.configure("https://fixture-resource.services.ai.azure.com:443/openai/v1")
        document = self.metadata.read_text(encoding="utf-8")
        self.assertNotIn(KEY, document)
        data = json.loads(document)
        self.assertEqual(
            data["Endpoint"], "https://fixture-resource.services.ai.azure.com/openai/v1/"
        )
        self.assertEqual(data["AllowedHost"], "fixture-resource.services.ai.azure.com")
        self.assertEqual(data["Deployment"], "my-deployment")
        self.assertTrue(data["ProtectedKey"])
        self.assertEqual(list(self.metadata.parent.glob("*.tmp")), [])

    def test_reconfiguration_replaces_metadata_and_key_as_one_document(self):
        self.configure()
        before = self.metadata.read_bytes()
        self.configure("https://replacement-resource.services.ai.azure.com/openai/v1/")
        self.assertNotEqual(self.metadata.read_bytes(), before)
        invocation = self.start_with_fake_cli()
        self.assertEqual(invocation["AllowedHosts"], "replacement-resource.services.ai.azure.com")
        self.assertTrue(invocation["KeyMatches"])
        self.assertEqual(list(self.metadata.parent.glob("*.tmp")), [])

    def test_failed_atomic_replacement_preserves_existing_configuration(self):
        self.configure()
        before = self.metadata.read_bytes()
        wrapper = self.root / "locked-config.ps1"
        wrapper.write_text(
            r"""
$ErrorActionPreference = 'Stop'
$path = Join-Path $env:LOCALAPPDATA 'EvidenceDesk/azure-openai.runtime.json'
$stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
try {
    & $env:ED_HELPER_TEST_SCRIPT -Action configure -Endpoint 'https://replacement-resource.openai.azure.com/openai/v1/' -Deployment 'changed-deployment' -ReadKeyFromStdin
    exit 0
} catch {
    exit 23
} finally {
    $stream.Dispose()
}
""",
            encoding="utf-8",
        )
        result = subprocess.run(
            [PWSH, "-NoProfile", "-File", str(wrapper)],
            input=KEY + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
            timeout=30,
        )
        self.assertEqual(result.returncode, 23)
        self.assertNotIn(KEY, result.stdout + result.stderr)
        self.assertEqual(self.metadata.read_bytes(), before)
        self.assertEqual(list(self.metadata.parent.glob("*.tmp")), [])

    def test_invalid_configuration_preserves_previous_key_and_metadata(self):
        self.configure()
        before = self.metadata.read_bytes()
        for endpoint in (
            "https://evil.example/openai/v1/",
            "https://fixture.openai.azure.com.evil.example/openai/v1/",
            "https://user@fixture.openai.azure.com/openai/v1/",
            "http://fixture.openai.azure.com/openai/v1/",
            "https://fixture.openai.azure.com:444/openai/v1/",
            "https://fixture.openai.azure.com/openai/v1/?proxy=other",
            "https://fixture.openai.azure.com/openai/v1/#fragment",
            "https://fixture.services.ai.azure.com/api/projects/test",
        ):
            with self.subTest(endpoint=endpoint):
                result = self.run_helper(
                    "-Action",
                    "configure",
                    "-Endpoint",
                    endpoint,
                    "-Deployment",
                    "my-deployment",
                    "-ReadKeyFromStdin",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.metadata.read_bytes(), before)
        result = self.run_helper(
            "-Action",
            "configure",
            "-Endpoint",
            "https://fixture.openai.azure.com/openai/v1/",
            "-Deployment",
            "my-deployment",
            "-ReadKeyFromStdin",
            key="short",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.metadata.read_bytes(), before)

    def test_start_passes_env_file_and_restores_all_environment_values(self):
        self.configure()
        invocation = self.start_with_fake_cli()
        self.assertEqual(
            invocation["Endpoint"], "https://fixture-resource.openai.azure.com/openai/v1/"
        )
        self.assertEqual(invocation["AllowedHosts"], "fixture-resource.openai.azure.com")
        self.assertEqual(invocation["Provider"], "azure_openai")
        self.assertTrue(invocation["KeyMatches"])
        self.assertIn("--env-file", invocation["Arguments"])
        self.assertIn(str(self.root / "runtime with spaces.env"), invocation["Arguments"])
        self.assertNotIn("--observability", invocation["Arguments"])
        self.assertEqual(invocation["Arguments"][-1], "start")

    def test_observability_is_explicit_and_failed_start_restores_environment(self):
        self.configure()
        invocation = self.start_with_fake_cli(observability=True, fail=True)
        self.assertIn("--observability", invocation["Arguments"])

    def test_legacy_key_is_not_migrated_or_replaced_implicitly(self):
        legacy = self.root / "EvidenceDesk/azure-openai.dpapi"
        legacy.parent.mkdir()
        legacy.write_text("legacy-encrypted-fixture", encoding="utf-8")
        result = self.run_helper("-Action", "start")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("configure", result.stderr)
        self.assertIn("Deployment", result.stderr)
        self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy-encrypted-fixture")
        self.assertFalse(self.metadata.exists())


if __name__ == "__main__":
    unittest.main()
