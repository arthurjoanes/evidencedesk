import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("paginated collection selection, accessible validation and frozen in-flight forms", async ({
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

  // Controlled pagination fixture; selecting a real authorized collection below
  // still creates an incident and dossier through the actual API.
  const collections = await (
    await page.request.get("/api/v1/collections?limit=100")
  ).json();
  const firstPage = Array.from({ length: 100 }, (_, index) => ({
    id: "controlled-collection-" + index,
    name: "Coleção controlada " + index,
    description: "Fixture de paginação, não publicada.",
    active_snapshot_id: null,
  }));
  await page.route("**/api/v1/collections?*", async (route) => {
    const next =
      new URL(route.request().url()).searchParams.get("cursor") ===
      "controlled-next";
    await route.fulfill({
      json: {
        items: next ? collections.items : firstPage,
        next_cursor: next ? null : "controlled-next",
        total: null,
      },
    });
  });
  await page
    .getByRole("button", { name: "Abrir incidente", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "Abrir incidente", exact: true })
    .click();
  await expect(dialog.getByLabel("Título", { exact: true })).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await expect(
    dialog.getByLabel("Título", { exact: true }),
  ).toHaveAccessibleDescription(
    "Descreva o incidente em pelo menos 5 caracteres.",
  );
  await expect(
    dialog.getByLabel("Coleção", { exact: true }),
  ).toHaveAccessibleDescription("Escolha uma coleção.");
  await expect(dialog.locator('option[value="commerce-main"]')).toHaveCount(0);
  await dialog.getByRole("button", { name: "Carregar mais coleções" }).click();
  await dialog
    .getByLabel("Coleção", { exact: true })
    .selectOption("commerce-main");
  await expect(dialog.locator("select option")).toHaveCount(
    101 + collections.items.length,
  );
  await expect(
    dialog.getByRole("button", { name: "Carregar mais coleções" }),
  ).toHaveCount(0);
  expect(
    (
      await new AxeBuilder({ page })
        .include('[role="dialog"]')
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);

  const title = "QA publicação " + Date.now();
  await dialog.getByLabel("Título", { exact: true }).fill(title);
  await dialog
    .getByLabel("Início (UTC)", { exact: true })
    .fill("2026-07-01T12:00");
  await dialog
    .getByLabel("Fim (UTC)", { exact: true })
    .fill("2026-07-01T12:30");
  let releaseSave!: () => void;
  const saving = new Promise<void>((resolve) => {
    releaseSave = resolve;
  });
  await page.route("**/api/v1/incidents", async (route) => {
    if (route.request().method() === "POST") await saving;
    await route.continue();
  });
  await dialog
    .getByRole("button", { name: "Abrir incidente", exact: true })
    .click();
  try {
    await expect(dialog.getByLabel("Título", { exact: true })).toBeDisabled();
    await expect(dialog.getByLabel("Coleção", { exact: true })).toBeDisabled();
  } finally {
    releaseSave();
  }
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await page.getByRole("link", { name: "Dossiê", exact: true }).click();
  await page.getByRole("button", { name: "Criar dossiê manual" }).click();
  await page
    .getByLabel("Resumo da investigação")
    .fill("QA: evidência insuficiente para atribuir uma causa ao incidente.");
  let releaseDossier!: () => void;
  const dossierSaving = new Promise<void>((resolve) => {
    releaseDossier = resolve;
  });
  await page.route("**/api/v1/incidents/*/dossiers", async (route) => {
    if (route.request().method() === "POST") await dossierSaving;
    await route.continue();
  });
  await page.getByRole("button", { name: "Salvar dossiê manual" }).click();
  try {
    await expect(page.getByLabel("Resumo da investigação")).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Adicionar alegação" }),
    ).toBeDisabled();
  } finally {
    releaseDossier();
  }
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.goto("/imports/new");
  await expect(page.locator('option[value="commerce-main"]')).toHaveCount(0);
  await page.getByRole("button", { name: "Carregar mais coleções" }).click();
  await page
    .getByLabel("Coleção de destino", { exact: true })
    .selectOption("commerce-main");
  await expect(
    page.getByLabel("Coleção de destino", { exact: true }),
  ).toHaveValue("commerce-main");
});
