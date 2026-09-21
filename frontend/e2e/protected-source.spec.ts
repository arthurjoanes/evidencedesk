import { expect, test } from "@playwright/test";

test("reopened source waits for current authorization and hides cached text after denial", async ({
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
  await page.goto("/incidents/demo-aurora-09?tab=sources");
  const source = page
    .getByRole("button", { name: "Conferir fonte", exact: true })
    .first();
  await source.click();
  const canonical = page.getByRole("region", {
    name: "Texto canônico da fonte",
    exact: true,
  });
  await expect(canonical).toBeVisible();
  await expect(canonical).not.toBeEmpty();
  await expect(
    page.getByText("Proveniência e detalhes técnicos", { exact: true }),
  ).toBeVisible();
  const selected = new URL(page.url()).searchParams.get("evidence");
  expect(selected).toBeTruthy();
  await page
    .getByRole("button", { name: "Voltar à seleção", exact: true })
    .click();

  let release: () => void = () => undefined;
  const authorization = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requests = 0;
  // Transport fixture: deny only this resource after its first real authorized read.
  await page.route("**/api/v1/evidence/" + selected + "?*", async (route) => {
    requests += 1;
    await authorization;
    await route.fulfill({
      status: 404,
      json: {
        error: {
          code: "not_found",
          message: "Fonte indisponível após revogação controlada.",
          request_id: "controlled-revocation",
          retryable: false,
        },
      },
    });
  });
  await source.click();
  await expect.poll(() => requests).toBe(1);
  await expect(
    page.getByText("Consultando a fonte autorizada…", { exact: true }),
  ).toBeVisible();
  await expect(canonical).toHaveCount(0);
  release();
  await expect(
    page
      .getByRole("region", { name: "Leitor de evidência" })
      .getByRole("alert"),
  ).toContainText("Fonte indisponível após revogação controlada.");
  await expect(canonical).toHaveCount(0);
  await expect(
    page.getByText("Proveniência e detalhes técnicos", { exact: true }),
  ).toHaveCount(0);
  expect(requests).toBe(1);
});
