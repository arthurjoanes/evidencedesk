import { expect, test } from "@playwright/test";

test("controlled transport failures never become empty or successful results", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByLabel("E-mail", { exact: true })
    .fill(process.env.ED_E2E_ANALYST_EMAIL ?? "ana@aurora.demo");
  await page
    .getByLabel("Senha", { exact: true })
    .fill(process.env.ED_E2E_PASSWORD ?? "EvidenceDesk-demo-2026!");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Incidentes", exact: true }),
  ).toBeVisible();
  await page.route("**/api/v1/runs/qa-controlled/events", (route) =>
    route.abort(),
  );
  await page.route("**/api/v1/runs/qa-controlled", (route) =>
    route.fulfill({
      json: {
        id: "qa-controlled",
        state: "failed",
        stage: "generation",
        outcome: null,
        created_at: "2026-09-21T00:00:00Z",
        steps: [],
        cancel_requested: false,
        last_event_id: 1,
        evidence_snapshot_id: "qa-controlled",
        dossier_id: null,
        revision_id: null,
        error: {
          code: "provider_unavailable",
          message: "Falha controlada do provedor para teste da interface.",
        },
        started_at: "2026-09-21T00:00:00Z",
        completed_at: "2026-09-21T00:00:01Z",
        usage: { status: "unknown", input_tokens: null, output_tokens: null },
      },
    }),
  );
  await page.goto("/incidents/demo-aurora-09?run=qa-controlled");
  await expect(
    page
      .getByRole("region", { name: "Execução da investigação" })
      .getByText("Falhou", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "A revisão aprovada anterior, se houver, não representa sucesso desta tentativa.",
      { exact: false },
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Conferir rascunho" }),
  ).toHaveCount(0);
  await page.screenshot({
    path:
      (process.env.ED_E2E_ARTIFACT_DIR ?? "artifacts") +
      "/screenshots/controlled-failed-run.png",
  });
  await page.route("**/api/v1/imports", (route) =>
    route.fulfill({
      status: 200,
      json: { items: "malformed", next_cursor: null, total: 0 },
    }),
  );
  await page.goto("/imports");
  await expect(
    page.getByRole("alert").getByText("A operação não foi concluída"),
  ).toBeVisible();
  await expect(
    page.getByText("Nenhum pacote importado", { exact: true }),
  ).toHaveCount(0);
});
