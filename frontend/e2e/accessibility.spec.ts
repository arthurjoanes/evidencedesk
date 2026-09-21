import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("WCAG automated checks, keyboard resizing and unique script nonces", async ({
  page,
}) => {
  const first = await page.request.get("/");
  const second = await page.request.get("/");
  const csp = first.headers()["content-security-policy"];
  expect(csp).toContain("'strict-dynamic'");
  expect(csp.match(/script-src[^;]+/)?.[0]).not.toContain("'unsafe-inline'");
  expect(csp.match(/nonce-([^']+)/)?.[1]).not.toEqual(
    second.headers()["content-security-policy"].match(/nonce-([^']+)/)?.[1],
  );
  await page.goto("/");
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
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
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.goto("/incidents/demo-aurora-09");
  await page
    .getByRole("button", { name: "Evidência 1", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("region", { name: "Texto canônico da fonte" }),
  ).not.toBeEmpty();
  const reader = page.getByRole("region", { name: "Leitor de evidência" });
  const widthBefore = (await reader.boundingBox())!.width;
  const separator = page.getByRole("separator", {
    name: "Ajustar largura da evidência",
  });
  await separator.focus();
  await separator.press("ArrowLeft");
  await expect
    .poll(async () => (await reader.boundingBox())!.width)
    .not.toBe(widthBefore);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.setViewportSize({ width: 320, height: 800 });
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
});
