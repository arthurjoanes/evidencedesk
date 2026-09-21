import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
test("real workspace visual evidence and mobile source return", async ({
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
  await expect(page.locator("tbody .cell-title").first()).toBeVisible();
  await mkdir(
    (process.env.ED_E2E_ARTIFACT_DIR ?? "artifacts") + "/screenshots",
    { recursive: true },
  );
  for (const [name, width, height] of [
    ["desktop", 1440, 1000],
    ["tablet", 768, 900],
    ["mobile", 320, 800],
  ] as const) {
    await page.setViewportSize({ width, height });
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
        "/screenshots/queue-" +
        name +
        ".png",
    });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/incidents/demo-aurora-09");
  await expect(
    page.getByRole("heading", {
      name: "Pagamento confirmado e pedido pendente",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Divergências por pedido" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Evidência 1", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("region", { name: "Texto canônico da fonte" }),
  ).not.toBeEmpty();
  await page.screenshot({
    path:
      (process.env.ED_E2E_ARTIFACT_DIR ?? "artifacts") +
      "/screenshots/workspace-desktop.png",
  });
  for (const [name, width, height] of [
    ["tablet", 768, 900],
    ["mobile", 320, 800],
  ] as const) {
    await page.setViewportSize({ width, height });
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
        "/screenshots/source-" +
        name +
        ".png",
    });
  }
  await page
    .getByRole("button", { name: "Voltar à seleção", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Divergências por pedido" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Evidência 1", exact: true }).first(),
  ).toBeFocused();
  await page.screenshot({
    path:
      (process.env.ED_E2E_ARTIFACT_DIR ?? "artifacts") +
      "/screenshots/workspace-mobile.png",
  });
});
