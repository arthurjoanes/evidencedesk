import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

type SessionState = Awaited<ReturnType<APIRequestContext["storageState"]>>;

export const readOnlyTest = test.extend<
  Record<never, never>,
  { analystSession: SessionState }
>({
  analystSession: [
    async ({ playwright }, provide, workerInfo) => {
      const baseURL = workerInfo.project.use.baseURL;
      if (!baseURL) throw new Error("The browser project needs a baseURL.");
      const request = await playwright.request.newContext({ baseURL });
      try {
        const response = await request.post("/api/v1/auth/login", {
          headers: { Origin: new URL(baseURL).origin },
          data: {
            email: process.env.ED_E2E_ANALYST_EMAIL ?? "ana@aurora.demo",
            password: process.env.ED_E2E_PASSWORD ?? "EvidenceDesk-demo-2026!",
          },
        });
        expect(response.status()).toBe(200);
        await provide(await request.storageState());
      } finally {
        await request.dispose();
      }
    },
    { scope: "worker" },
  ],
  storageState: async ({ analystSession }, provide) => {
    await provide(analystSession);
  },
});

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
