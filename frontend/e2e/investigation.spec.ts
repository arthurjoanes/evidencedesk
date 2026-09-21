import { expect, test, type Page } from "@playwright/test";
const password = process.env.ED_E2E_PASSWORD ?? "EvidenceDesk-demo-2026!";
async function login(
  page: Page,
  email = process.env.ED_E2E_ANALYST_EMAIL ?? "ana@aurora.demo",
) {
  await page.goto("/");
  await page.getByLabel("E-mail", { exact: true }).fill(email);
  await page.getByLabel("Senha", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Incidentes", exact: true }),
  ).toBeVisible();
}
test("real session, bounded evidence reader, keyboard return and responsive queue", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page);
  for (const width of [320, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
  }
  const incident = page.locator('tbody .cell-title[href*="demo-aurora-01"]');
  await expect(incident).toBeVisible();
  await incident.click();
  await page.getByRole("link", { name: "Fontes", exact: true }).click();
  const source = page
    .getByRole("button", { name: "Conferir fonte", exact: true })
    .first();
  await expect(source).toBeVisible();
  await source.click();
  await expect(
    page.getByRole("region", { name: "Leitor de evidência" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Texto canônico da fonte" }),
  ).not.toBeEmpty();
  await page
    .getByRole("button", { name: "Voltar à seleção", exact: true })
    .click();
  await expect(source).toBeFocused();
  await page.getByRole("link", { name: "Linha do tempo", exact: true }).click();
  await expect(
    page.getByText("A sequência não comprova causalidade.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sair da sessão" }).click();
  await expect(
    page.getByRole("heading", { name: "Acessar a bancada" }),
  ).toBeVisible();
  await page.getByLabel("E-mail", { exact: true }).fill("carla@horizonte.demo");
  await page.getByLabel("Senha", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(
    page.getByText("Horizonte Varejo", { exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
test("manual abstention, independent review and authorized export", async ({
  page,
}) => {
  await login(page);
  await page
    .getByRole("button", { name: "Abrir incidente", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  const title = "QA manual " + Date.now();
  await dialog.getByLabel("Título", { exact: true }).fill(title);
  await dialog
    .getByRole("combobox", { name: "Coleção", exact: true })
    .selectOption("commerce-main");
  await dialog
    .locator('input[type="datetime-local"]')
    .nth(0)
    .fill("2026-07-01T12:00");
  await dialog
    .locator('input[type="datetime-local"]')
    .nth(1)
    .fill("2026-07-01T12:30");
  await dialog
    .getByRole("button", { name: "Abrir incidente", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await page.getByRole("link", { name: "Dossiê", exact: true }).click();
  await page.getByRole("button", { name: "Criar dossiê manual" }).click();
  await page
    .getByLabel("Resumo da investigação")
    .fill(
      "Revisão de laboratório: evidência insuficiente para atribuir uma causa ao incidente. Nenhuma alegação foi criada.",
    );
  await page
    .getByLabel("Lacunas do recorte (uma por linha)")
    .fill(
      "Falta conferir o período de cobertura e a vigência dos procedimentos.",
    );
  await page
    .getByLabel("Próximas verificações do recorte (uma por linha)")
    .fill("Conferir as fontes autorizadas com o responsável da operação.");
  await page.getByRole("button", { name: "Salvar dossiê manual" }).click();
  await expect(
    page.getByText("Elaboração manual", { exact: false }).last(),
  ).toBeVisible();
  const beforeConflict = new URL(page.url()).searchParams;
  const dossierId = beforeConflict.get("dossier");
  const revisionId = beforeConflict.get("revision");
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const originalRevision = await (
    await page.request.get(
      "/api/v1/dossiers/" + dossierId + "/revisions/" + revisionId,
    )
  ).json();
  await page.getByRole("button", { name: "Preparar revisão" }).click();
  const preservedDraft =
    "Rascunho concorrente: evidência insuficiente. As lacunas continuam explícitas e nenhuma causa foi atribuída.";
  await page.getByLabel("Resumo da investigação").fill(preservedDraft);
  // Refetching authorization and crossing the responsive boundary must not discard edits.
  for (const width of [320, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByLabel("Resumo da investigação")).toHaveValue(
      preservedDraft,
    );
  }
  const checkedDraftAccess = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/dossiers/" + dossierId) &&
      response.request().method() === "GET",
  );
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
  await checkedDraftAccess;
  await expect(page.getByLabel("Resumo da investigação")).toBeVisible();
  await expect(page.getByLabel("Resumo da investigação")).toHaveValue(
    preservedDraft,
  );
  const concurrent = await page.request.post(
    "/api/v1/dossiers/" + dossierId + "/revisions",
    {
      headers: {
        "X-CSRF-Token": session.csrf_token,
        "If-Match": originalRevision.etag,
        Origin: new URL(page.url()).origin,
      },
      data: {
        base_revision_id: originalRevision.id,
        summary:
          "Outra edição de laboratório: evidência insuficiente para concluir.",
        claims: [],
        outcome: "insufficient_evidence",
        missing_information: ["Fonte ainda precisa ser conferida."],
        suggested_checks: [],
      },
    },
  );
  expect(concurrent.status()).toBe(201);
  await page.getByRole("button", { name: "Salvar nova revisão" }).click();
  await expect(
    page.getByText("A revisão-base mudou. Seu texto foi preservado.", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(page.getByLabel("Resumo da investigação")).toHaveValue(
    preservedDraft,
  );
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Voltar", exact: true })
    .click();
  const latestRevision = await concurrent.json();
  const latestUrl = new URL(page.url());
  latestUrl.searchParams.set("revision", latestRevision.id);
  await page.goto(latestUrl.href);
  await page.getByRole("button", { name: "Preparar revisão" }).click();
  await page.getByLabel("Resumo da investigação").fill(preservedDraft);
  await page.getByRole("button", { name: "Salvar nova revisão" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "Enviar para revisão" }).click();
  await expect(
    page.getByText("Enviado para revisão", { exact: true }).last(),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Registrar decisão", exact: true }),
  ).toHaveCount(0);
  const url = page.url();
  await page.getByRole("button", { name: "Sair da sessão" }).click();
  await login(page, process.env.ED_E2E_REVIEWER_EMAIL ?? "bruno@aurora.demo");
  await page.goto(url);
  await page
    .getByRole("button", { name: "Registrar decisão", exact: true })
    .click();
  await expect(page.getByLabel("Justificativa")).toHaveAttribute(
    "maxlength",
    "3000",
  );
  await page
    .getByLabel("Justificativa")
    .fill(
      "Conferi a abstenção e os limites. A aprovação registra a revisão humana e não uma causa confirmada.",
    );
  page.once("dialog", (dialog) => dialog.dismiss());
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Voltar", exact: true })
    .click();
  await expect(page.getByLabel("Justificativa")).toHaveValue(
    "Conferi a abstenção e os limites. A aprovação registra a revisão humana e não uma causa confirmada.",
  );
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Registrar decisão", exact: true })
    .click();
  await page.getByRole("button", { name: "Preparar exportação" }).click();
  const reauthorized = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/dossiers/") &&
      response.request().method() === "GET",
  );
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
  await reauthorized;
  const download = page.getByRole("link", { name: "Baixar HTML da revisão" });
  await expect(download).toBeVisible({ timeout: 30_000 });
  const response = await page.request.get(
    (await download.getAttribute("href"))!,
  );
  expect(response.status()).toBe(200);
  expect(await response.text()).toContain("evidência insuficiente");
});
