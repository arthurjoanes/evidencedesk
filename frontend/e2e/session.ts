import { expect, type Page } from "@playwright/test";

export async function logout(page: Page) {
  // A click completes before the async handler; navigation could cancel logout.
  const response = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/v1/auth/logout" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sair da sessão" }).click();
  expect((await response).status()).toBe(204);
  await expect(
    page.getByRole("heading", { name: "Acessar a bancada" }),
  ).toBeVisible();
}
