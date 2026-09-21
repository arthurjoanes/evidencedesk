import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("read an existing real generation without admitting a new job", async ({
  page,
}) => {
  const run = process.env.ED_E2E_EXISTING_RUN_ID;
  const incident = process.env.ED_E2E_EXISTING_INCIDENT_ID;
  test.skip(
    !run || !incident,
    "Requires an explicitly provided, already completed laboratory run.",
  );
  const generationPosts: string[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/incidents\/[^/]+\/runs$/.test(request.url())
    )
      generationPosts.push(request.url());
  });
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
  await page.goto("/incidents/" + incident + "?run=" + run);
  await page
    .getByRole("button", { name: "Conferir rascunho", exact: true })
    .click();
  await expect(
    page.getByText("Gerado por IA", { exact: false }).last(),
  ).toBeVisible();
  await expect(
    page.getByText("Rascunho", { exact: true }).last(),
  ).toBeVisible();
  await expect(page.locator(".claim")).toHaveCount(3);
  await expect(
    page.getByRole("button", { name: "Preparar exportação" }),
  ).toHaveCount(0);
  await page.screenshot({
    path:
      (process.env.ED_E2E_ARTIFACT_DIR ?? "artifacts") +
      "/screenshots/azure-result-desktop.png",
    fullPage: true,
  });
  const evidenceResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/evidence/") && response.status() === 200,
  );
  await page.locator(".claim .source-button").first().click();
  const evidence = await (await evidenceResponse).json();
  const aggregate = JSON.parse(evidence.canonical_text);
  const structured = page.getByRole("region", {
    name: "Conciliação estruturada",
  });
  await expect(structured).toBeVisible();
  await expect(
    structured
      .locator(".reconciliation-measures > div")
      .filter({ has: page.getByText("Pedidos", { exact: true }) })
      .locator("dd"),
  ).toHaveText(new Intl.NumberFormat("pt-BR").format(aggregate.counts.orders));
  await page.setViewportSize({ width: 320, height: 800 });
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path:
      (process.env.ED_E2E_ARTIFACT_DIR ?? "artifacts") +
      "/screenshots/azure-source-mobile.png",
  });
  expect(
    (
      await new AxeBuilder({ page })
        .include(".evidence-panel")
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page
    .getByRole("button", { name: "Texto canônico", exact: true })
    .click();
  const original = page.getByRole("region", {
    name: "Texto canônico da fonte",
  });
  await expect(original).toHaveText(evidence.canonical_text);
  await page
    .getByRole("button", { name: "Formatar JSON para leitura" })
    .click();
  expect(JSON.parse((await original.textContent())!)).toEqual(aggregate);
  await page.screenshot({
    path:
      (process.env.ED_E2E_ARTIFACT_DIR ?? "artifacts") +
      "/screenshots/azure-source-json-mobile.png",
  });
  await page.getByRole("button", { name: "Mostrar JSON original" }).click();
  await expect(original).toHaveText(evidence.canonical_text);
  expect(generationPosts).toEqual([]);
});
