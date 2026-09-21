import { expect, test, type Page } from "@playwright/test";

async function refocusAfterStale(page: Page) {
  await page.clock.fastForward(31_000);
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
}

test("session revalidation hides portals, preserves draft on 503/network, resets on replacement and removes on 401", async ({
  page,
}) => {
  await page.clock.install();
  const email = process.env.ED_E2E_SESSION_EMAIL ?? "carla@horizonte.demo";
  const password = process.env.ED_E2E_PASSWORD ?? "EvidenceDesk-demo-2026!";
  await page.goto("/");
  await page.getByLabel("E-mail", { exact: true }).fill(email);
  await page.getByLabel("Senha", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Incidentes", exact: true }),
  ).toBeVisible();
  await page.goto("/incidents/demo-horizonte-01?tab=dossier");
  await page.getByRole("button", { name: "Criar dossiê manual" }).click();
  const draft =
    "Rascunho local de regressão: preservar texto após indisponibilidade transitória da sessão.";
  await page.getByLabel("Resumo da investigação").fill(draft);
  let mode: "ok" | "unavailable" | "offline" | "expired" = "ok";
  let checked = 0;
  await page.route("**/api/v1/auth/session", async (route) => {
    checked++;
    if (mode === "ok") {
      await route.continue();
      return;
    }
    if (mode === "offline") {
      await route.abort("failed");
      return;
    }
    await route.fulfill({
      status: mode === "expired" ? 401 : 503,
      json: {
        error: {
          code: "controlled_session_state",
          message: "Indisponibilidade de sessão controlada no QA.",
          request_id: "qa-session-review",
          retryable: mode !== "expired",
        },
      },
    });
  });
  for (const failure of ["unavailable", "offline"] as const) {
    mode = failure;
    const before = checked;
    await refocusAfterStale(page);
    await expect.poll(() => checked).toBeGreaterThan(before);
    const blocked = page.getByRole("region", { name: "Verificação da sessão" });
    await expect(blocked.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByLabel("Resumo da investigação")).toHaveCount(0);
    await expect(page.locator(".authenticated-content")).toBeHidden();
    expect(await page.locator("body").innerText()).not.toContain(draft);
    const retry = blocked.getByRole("button", { name: "Tentar novamente" });
    await retry.focus();
    await expect(retry).toBeFocused();
    await page.screenshot({
      path:
        (process.env.ED_E2E_ARTIFACT_DIR ?? "artifacts") +
        "/screenshots/session-" +
        failure +
        ".png",
    });
    mode = "ok";
    await retry.press("Enter");
    await expect(page.getByLabel("Resumo da investigação")).toBeVisible();
    await expect(page.getByLabel("Resumo da investigação")).toHaveValue(draft);
  }
  // A real replacement session for the same person must reset local unsaved work.
  const original = await (
    await page.request.get("/api/v1/auth/session")
  ).json();
  const replacement = await page.request.post("/api/v1/auth/login", {
    data: { email, password },
    headers: { Origin: new URL(page.url()).origin },
  });
  expect(replacement.status()).toBe(200);
  expect((await replacement.json()).csrf_token).not.toBe(original.csrf_token);
  await refocusAfterStale(page);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "Criar dossiê manual" }).click();
  await expect(page.getByLabel("Resumo da investigação")).toHaveValue("");
  await page
    .getByLabel("Resumo da investigação")
    .fill("Novo rascunho deve desaparecer quando a sessão terminar.");
  mode = "expired";
  await refocusAfterStale(page);
  await expect(
    page.getByRole("heading", { name: "Acessar a bancada" }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".authenticated-content")).toHaveCount(0);
  await expect(page.getByLabel("Resumo da investigação")).toHaveCount(0);
});
