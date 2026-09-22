import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir } from "node:fs/promises";

test("JSON colors preserve the canonical source and readable view", async ({
  page,
}) => {
  const generationPosts: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
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
  await page.goto("/incidents/demo-aurora-09");
  const response = page.waitForResponse(
    (result) =>
      result.url().includes("/api/v1/evidence/") && result.status() === 200,
  );
  await page
    .getByRole("button", { name: "Evidência 1", exact: true })
    .first()
    .click();
  const evidence = await (await response).json();
  const original = evidence.canonical_text as string;
  const parsed = JSON.parse(original);
  const source = page.getByRole("region", { name: "Texto canônico da fonte" });
  const code = source.locator("code.language-json");
  await expect(code).toBeVisible();
  expect(await code.textContent()).toBe(original);

  const selected = await code.evaluate((element) => {
    const range = document.createRange();
    range.selectNodeContents(element);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    const text = selection.toString();
    selection.removeAllRanges();
    return text;
  });
  expect(selected).toBe(original);
  const colors = await code
    .locator("span")
    .evaluateAll((spans) =>
      spans.map((span) => ({
        text: span.textContent,
        color: getComputedStyle(span).color,
      })),
    );
  const keyColor = colors.find(
    (token) => token.text === '"source_system"',
  )?.color;
  const stringColor = colors.find(
    (token) => token.text === JSON.stringify(parsed.source_system),
  )?.color;
  expect(keyColor).toBeDefined();
  expect(stringColor).toBeDefined();
  expect(keyColor).not.toBe(stringColor);
  expect(
    new Set(colors.map((token) => token.color)).size,
  ).toBeGreaterThanOrEqual(3);

  const output = process.env.ED_E2E_ARTIFACT_DIR ?? "artifacts";
  await mkdir(output + "/screenshots", { recursive: true });
  for (const [name, width, height] of [
    ["desktop", 1440, 1000],
    ["mobile", 320, 800],
  ] as const) {
    await page.setViewportSize({ width, height });
    await expect(code).toHaveText(original);
    await page.evaluate(() => document.fonts.ready);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await source.screenshot({
      path: output + "/screenshots/source-json-" + name + ".png",
    });
  }
  expect(
    (
      await new AxeBuilder({ page })
        .include(".evidence-text")
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page
    .getByRole("button", { name: "Formatar JSON para leitura" })
    .click();
  expect(JSON.parse((await code.textContent())!)).toEqual(parsed);
  await expect(code.locator("span").first()).toBeVisible();
  await page.getByRole("button", { name: "Mostrar JSON original" }).click();
  expect(await code.textContent()).toBe(original);
  await page.emulateMedia({ forcedColors: "active" });
  expect(await code.textContent()).toBe(original);
  const forcedColors = await code
    .locator("span")
    .evaluateAll(
      (spans) =>
        new Set(spans.map((span) => getComputedStyle(span).color)).size,
    );
  expect(forcedColors).toBe(1);
  expect(generationPosts).toEqual([]);
  expect(errors).toEqual([]);
});
