import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("controlled indexing capability: disabled, bounded admission, failure and invalid coverage", async ({
  page,
}) => {
  let mode = "disabled";
  const admissions: { key: string | undefined; csrf: string | undefined }[] =
    [];
  await page.route("**/api/v1/evidence-snapshots/*/index", async (route) => {
    const request = route.request();
    const snapshot = new URL(request.url()).pathname.split("/").at(-2);
    if (request.method() === "POST") {
      admissions.push({
        key: request.headers()["idempotency-key"],
        csrf: request.headers()["x-csrf-token"],
      });
      mode = "failed";
    }
    await route.fulfill({
      json: {
        evidence_snapshot_id: snapshot,
        embedding_revision: "controlled-test",
        total_documents: 8,
        indexed_documents: 2,
        complete: mode === "invalid",
        indexing_enabled: mode !== "disabled",
        disabled_reason:
          mode === "disabled"
            ? "O serviço privado de modelos não está configurado."
            : null,
        job:
          mode === "failed"
            ? {
                id: "controlled-index",
                state: "failed",
                stage: "indexing",
                attempt: 1,
                error: {
                  code: "model_service_unavailable",
                  message: "Falha controlada do serviço de modelos.",
                },
              }
            : null,
      },
    });
  });
  if (process.env.ED_E2E_AUTH_ORIGIN) {
    const origin = process.env.ED_E2E_AUTH_ORIGIN;
    const login = await page.request.post(origin + "/api/v1/auth/login", {
      headers: { Origin: origin },
      data: {
        email: process.env.ED_E2E_ANALYST_EMAIL ?? "ana@aurora.demo",
        password: process.env.ED_E2E_PASSWORD ?? "EvidenceDesk-demo-2026!",
      },
    });
    expect(login.status()).toBe(200);
  }
  await page.goto("/");
  if (!process.env.ED_E2E_AUTH_ORIGIN) {
    await page
      .getByLabel("E-mail", { exact: true })
      .fill(process.env.ED_E2E_ANALYST_EMAIL ?? "ana@aurora.demo");
    await page
      .getByLabel("Senha", { exact: true })
      .fill(process.env.ED_E2E_PASSWORD ?? "EvidenceDesk-demo-2026!");
    await page.getByRole("button", { name: "Entrar", exact: true }).click();
  }
  await expect(
    page.getByRole("heading", { name: "Incidentes", exact: true }),
  ).toBeVisible();
  await page.goto("/incidents/demo-aurora-09?tab=sources");
  const summary = page.getByText("Disponibilidade da busca semântica", {
    exact: true,
  });
  await summary.click();
  await expect(
    page.getByText("O serviço privado de modelos não está configurado.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Preparar índice" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("2 de 8 trechos documentais preparados", { exact: true }),
  ).toBeVisible();
  mode = "enabled";
  await page.reload();
  await summary.click();
  await page
    .getByRole("button", { name: "Preparar índice", exact: true })
    .click();
  await expect(
    page.getByText("Falha controlada do serviço de modelos.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Preparar índice" }),
  ).toHaveCount(0);
  expect(admissions).toHaveLength(1);
  expect(admissions[0].key).toMatch(/^[a-f0-9-]{36}$/);
  expect(admissions[0].csrf).toBeTruthy();
  await page.setViewportSize({ width: 320, height: 800 });
  if (
    !(await page
      .locator(".snapshot-index")
      .evaluate((element) => (element as HTMLDetailsElement).open))
  )
    await summary.click();
  await expect(
    page.getByText("Falha controlada do serviço de modelos.", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
  expect(
    (
      await new AxeBuilder({ page })
        .include(".snapshot-index")
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.locator(".snapshot-index").screenshot({
    path:
      (process.env.ED_E2E_ARTIFACT_DIR ?? "artifacts") +
      "/screenshots/controlled-index-mobile.png",
  });
  mode = "invalid";
  await page.reload();
  await summary.click();
  await expect(
    page.locator(".snapshot-index").getByRole("alert"),
  ).toBeVisible();
  await expect(
    page.getByText("O índice cobre os trechos deste snapshot."),
  ).toHaveCount(0);
});
