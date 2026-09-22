import { expect, test } from "@playwright/test";
import { logout } from "./session";

test("account switch waits for a pending real logout before navigation", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByLabel("E-mail", { exact: true })
    .fill(process.env.ED_E2E_SESSION_EMAIL ?? "carla@horizonte.demo");
  await page
    .getByLabel("Senha", { exact: true })
    .fill(process.env.ED_E2E_PASSWORD ?? "EvidenceDesk-demo-2026!");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Incidentes", exact: true }),
  ).toBeVisible();

  let releaseLogout!: () => void;
  const allowed = new Promise<void>((resolve) => {
    releaseLogout = resolve;
  });
  let observeLogout!: () => void;
  const intercepted = new Promise<void>((resolve) => {
    observeLogout = resolve;
  });
  // Retain the request until the pending UI is checked, then use the real API.
  await page.route("**/api/v1/auth/logout", async (route) => {
    observeLogout();
    await allowed;
    await route.continue();
  });
  let completed = false;
  const switching = (async () => {
    await logout(page);
    completed = true;
    await page.goto("/");
  })();
  try {
    await intercepted;
    await expect(
      page.getByRole("button", { name: "Sair da sessão" }),
    ).toBeDisabled();
    await expect(
      page.getByRole("heading", { name: "Acessar a bancada" }),
    ).toHaveCount(0);
    expect(completed).toBe(false);
  } finally {
    releaseLogout();
    await switching;
  }
  await expect(
    page.getByRole("heading", { name: "Acessar a bancada" }),
  ).toBeVisible();
  expect((await page.request.get("/api/v1/auth/session")).status()).toBe(401);
});
