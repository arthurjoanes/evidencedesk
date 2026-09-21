import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  outputDir: process.env.ED_E2E_ARTIFACT_DIR
    ? process.env.ED_E2E_ARTIFACT_DIR + "/test-results"
    : "test-results",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 12_000 },
  reporter: [
    ["list"],
    [
      "json",
      {
        outputFile:
          (process.env.ED_E2E_ARTIFACT_DIR ?? "artifacts") +
          "/e2e-results.json",
      },
    ],
    [
      "html",
      {
        open: "never",
        outputFolder: process.env.ED_E2E_ARTIFACT_DIR
          ? process.env.ED_E2E_ARTIFACT_DIR + "/playwright-report"
          : "playwright-report",
      },
    ],
  ],
  use: {
    baseURL: process.env.ED_E2E_BASE_URL ?? "http://127.0.0.1:3106",
    channel: process.env.ED_E2E_BROWSER_CHANNEL,
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
