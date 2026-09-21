import { expect, test } from "@playwright/test";
test("review regressions: queue context, successive navigation, form errors and revoked editor", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(page.getByLabel("E-mail", { exact: true })).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await page
    .getByLabel("E-mail", { exact: true })
    .fill(process.env.ED_E2E_REVIEWER_EMAIL ?? "bruno@aurora.demo");
  await page
    .getByLabel("Senha", { exact: true })
    .fill(process.env.ED_E2E_PASSWORD ?? "EvidenceDesk-demo-2026!");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Incidentes", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "Buscar incidentes" })
    .fill("Pagamento");
  await page.getByRole("button", { name: "Aplicar", exact: true }).click();
  await page.locator("tbody .cell-title").first().click();
  await expect(
    page.getByRole("link", { name: "Incidentes", exact: true }).last(),
  ).toHaveAttribute("href", "/?q=Pagamento");
  const snapshots = await page
    .locator("#snapshot option")
    .evaluateAll((options) =>
      options.map((option) => (option as HTMLOptionElement).value),
    );
  const labels = await page.locator("#snapshot option").allTextContents();
  expect(new Set(labels).size).toBe(labels.length);
  await page.locator("#snapshot").selectOption(snapshots[0]);
  await page.getByRole("link", { name: "Fontes", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Fontes", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  expect(new URL(page.url()).searchParams.get("snapshot")).toBe(snapshots[0]);
  await page.getByRole("link", { name: "Dossiê", exact: true }).click();
  await page.getByRole("button", { name: "Criar dossiê manual" }).click();
  await page
    .getByLabel("Resumo da investigação")
    .fill("Rascunho de QA: nenhuma causa foi confirmada.");
  await expect(page.getByLabel("Localizar fontes para vincular")).toHaveCount(
    0,
  );
  await page
    .getByLabel("Lacunas do recorte (uma por linha)")
    .fill("linha\n".repeat(21));
  await page.getByRole("button", { name: "Salvar dossiê manual" }).click();
  await expect(
    page.getByText(
      "Use no máximo 20 linhas por lista de lacunas ou verificações.",
    ),
  ).toBeVisible();
  const incident = new URL(page.url()).pathname.split("/").at(-1);
  await page.route("**/api/v1/incidents/" + incident, async (route) => {
    await route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "revoked",
          message: "Acesso revogado no cenário controlado.",
          request_id: "qa-editor-review",
          retryable: false,
        },
      }),
    });
  });
  const denied = page.waitForResponse((response) => response.status() === 403);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    window.dispatchEvent(new Event("visibilitychange"));
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    window.dispatchEvent(new Event("visibilitychange"));
  });
  await denied;
  await expect(page.getByLabel("Resumo da investigação")).toHaveCount(0);
  await expect(
    page.getByText("Acesso revogado no cenário controlado.").first(),
  ).toBeVisible();
});
