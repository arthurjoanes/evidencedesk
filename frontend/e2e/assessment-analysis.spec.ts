import { expect } from "@playwright/test";
import { readOnlyTest as test } from "./session";

test("resumo conta pedidos distintos e preserva o total entre páginas", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Incidentes", exact: true }),
  ).toBeVisible();
  const response = await page.request.get(
    "/api/v1/incidents/demo-aurora-09/reconciliation?limit=1",
  );
  expect(response.ok()).toBe(true);
  const first = await response.json();
  expect(first.items).toHaveLength(1);
  expect(first.summary.orders_with_divergence).toBe(1);
  expect(first.summary.by_status.divergence).toBe(2);
  const second = await (
    await page.request.get(
      `/api/v1/incidents/demo-aurora-09/reconciliation?limit=1&cursor=${encodeURIComponent(first.next_cursor)}`,
    )
  ).json();
  expect(second.summary).toEqual(first.summary);
  await page.goto("/incidents/demo-aurora-09");
  const chart = page.getByRole("region", { name: "Resumo das avaliações" });
  await expect(chart).toContainText("1 pedido com divergência");
  await expect(chart.locator("li").first()).toHaveText("Divergências2");
  await page.getByLabel("Referência exata do pedido").fill("PED-009-000");
  await page.getByRole("button", { name: "Filtrar", exact: true }).click();
  await expect(chart).toContainText("1 pedido com divergência");
  await page.getByLabel("Referência exata do pedido").fill("PED-INEXISTENTE");
  await page.getByRole("button", { name: "Filtrar", exact: true }).click();
  await expect(
    page.getByText("Nenhuma divergência neste recorte", { exact: true }),
  ).toBeVisible();
  await expect(chart).toHaveCount(0);
  await page.getByRole("button", { name: "Limpar", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(chart).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(
    await chart
      .locator(".assessment-bar")
      .first()
      .evaluate((element) => getComputedStyle(element).transitionDuration),
  ).toBe("0s");
});
