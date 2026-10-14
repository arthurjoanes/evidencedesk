import { expect, test, type Page } from "@playwright/test";

const now = "2026-10-13T12:00:00Z";
const permissions = [
  "create_dossier",
  "edit_dossier",
  "submit_revision",
  "export_revision",
  "create_import",
];
const incident = {
  id: "i",
  title: "Incidente sintético",
  description: "",
  status: "open",
  collection_id: "c",
  window: { from: now, to: now, time_zone: "UTC" },
  created_at: now,
  updated_at: now,
  evidence_snapshot_id: "s",
  available_snapshots: [{ id: "s", published_at: now }],
  available_snapshots_truncated: true,
  coverage: [],
  counts: { orders: 1, divergences: 0 },
  latest_run: null,
  dossier_id: "d",
  permissions,
};
function revision(state: string) {
  return {
    id: "r",
    number: 1,
    base_revision_id: null,
    summary: "Resumo sintético da revisão",
    claims: [],
    outcome: "insufficient_evidence",
    created_by: "author",
    created_at: now,
    review_status: state,
    etag: "r1",
    review: {
      submitted_by: "author",
      reviewed_by: "reviewer",
      reason: "Conferir identidade dos eventos.",
      claim_ids: [],
      updated_at: now,
    },
    impact_summary: {
      source: "deterministic_reconciliation",
      evidence_snapshot_id: "s",
      rule_revision: "v1",
      observations: 2,
      logical_events: 1,
      orders: 1,
      divergences: 0,
      not_evaluable: 1,
    },
  };
}

test("EVD-03: the first import POST retains its key after a lost response", async ({
  page,
}) => {
  await mockWorkspace(page);
  await page.route("**/api/v1/collections?*", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: "c",
            name: "Coleção sintética",
            description: "",
            active_snapshot_id: "s",
          },
        ],
        next_cursor: null,
        total: 1,
      },
    }),
  );
  let posts = 0;
  const keys: string[] = [];
  const batch = {
    id: "batch",
    collection_id: "c",
    title: "Pacote sintético",
    state: "receiving",
    created_at: now,
    evidence_snapshot_id: null,
    entries: [
      {
        entry_id: "exemplo-documento",
        filename: "documento-exemplo.md",
        kind: "document",
        byte_size: 245,
        sha256:
          "c9cfaf82c3c6d2082896ceee04b875ea51b5fbe8f306d0b6318e38cbae345a6b",
        state: "pending",
        error: null,
      },
    ],
    error: null,
  };
  await page.route("**/api/v1/imports", async (route) => {
    keys.push(route.request().headers()["idempotency-key"]);
    posts++;
    if (posts === 1) return route.abort("failed");
    await route.fulfill({ status: 201, json: batch });
  });
  await page.route("**/api/v1/imports/batch/**", async (route) => {
    batch.entries[0].state = "uploaded";
    if (route.request().url().endsWith("/finalize")) batch.state = "sealed";
    await route.fulfill({ json: batch });
  });
  await page.route("**/api/v1/imports/batch", (route) =>
    route.fulfill({ json: batch }),
  );
  await page.goto("/imports/new");
  await page.getByLabel("Coleção de destino").selectOption("c");
  await page
    .getByLabel("1. Manifesto do pacote")
    .setInputFiles("public/examples/manifesto-exemplo.json");
  await page
    .getByLabel("2. Arquivos descritos no manifesto")
    .setInputFiles("public/examples/documento-exemplo.md");
  await page.getByRole("button", { name: "Conferir e enviar" }).click();
  await expect(
    page.getByRole("button", { name: "Conferir e enviar" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Conferir e enviar" }).click();
  await expect(page).toHaveURL(/\/imports\/batch$/);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[1]).toBe(keys[0]);
});

async function mockWorkspace(page: Page, state = "changes_requested") {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let payload: unknown = {
      items: [],
      next_cursor: null,
      total: 0,
      coverage: [],
    };
    if (path.endsWith("/auth/session"))
      payload = {
        user: { id: "author", name: "Pessoa sintética", role: "reviewer" },
        tenant: { id: "t", name: "Tenant sintético" },
        csrf_token: "synthetic",
        expires_at: "2099-01-01T00:00:00Z",
        permissions,
        runtime: {
          generation_enabled: false,
          provider: "disabled",
          model_display_name: "Desabilitado",
          disabled_reason: "Teste sem provedor",
        },
      };
    else if (path === "/api/v1/incidents/i") payload = incident;
    else if (path === "/api/v1/dossiers/d")
      payload = {
        id: "d",
        incident_id: "i",
        origin: "manual",
        evidence_snapshot_id: "s",
        current_revision_id: "r",
        approved_revision_id: state === "approved" ? "r" : null,
        revisions: [
          {
            id: "r",
            number: 1,
            author: "author",
            created_at: now,
            review_status: state,
          },
        ],
        permissions,
      };
    else if (path === "/api/v1/dossiers/d/revisions/r")
      payload = revision(state);
    else if (path === "/api/v1/incidents/i/snapshots")
      payload = url.searchParams.has("cursor")
        ? {
            items: [
              { id: "old-snapshot", published_at: "2020-01-01T00:00:00Z" },
            ],
            next_cursor: null,
            total: null,
          }
        : {
            items: Array.from({ length: 50 }, (_, i) => ({
              id: "page-" + i,
              published_at: now,
            })),
            next_cursor: "older",
            total: null,
          };
    await route.fulfill({ json: payload });
  });
  await page.goto("/incidents/i?tab=dossier");
  await expect(
    page.getByRole("heading", { name: "Incidente sintético" }),
  ).toBeVisible();
}

test("EVD-01/04/05/06: returned review, older snapshots and errors identify their controls", async ({
  page,
}) => {
  await mockWorkspace(page);
  await expect(
    page.getByRole("button", { name: "Enviar para revisão" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Conferir identidade dos eventos."),
  ).toBeVisible();
  await page
    .getByText("Impacto observado no snapshot deste dossiê", { exact: true })
    .click();
  await expect(page.getByText(/1 avaliações inconclusivas/)).toBeVisible();
  await expect(
    page.getByText(/avaliações sem cobertura suficiente/),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Carregar recortes anteriores" })
    .click();
  await page.locator("#snapshot").selectOption("old-snapshot");
  await expect(page.locator("#snapshot")).toHaveValue("old-snapshot");
  await page.getByRole("button", { name: "Preparar nova revisão" }).click();
  const dialog = page.getByRole("dialog");
  const missing = dialog.getByLabel("Lacunas do recorte (uma por linha)");
  await missing.fill(Array(21).fill("linha").join("\n"));
  await dialog.getByRole("button", { name: "Salvar nova revisão" }).click();
  await expect(missing).toHaveAttribute("aria-invalid", "true");
  await expect(missing).toHaveAccessibleDescription(
    /Lacunas do recorte: Use no máximo 20 linhas/,
  );
  await expect(missing).toBeFocused();
  await missing.fill("Lacuna preservada");
  await dialog.getByRole("button", { name: "Adicionar alegação" }).click();
  await dialog.getByRole("button", { name: "Adicionar alegação" }).click();
  const second = dialog.getByLabel(
    "Alegação 2 — Informação que falta (uma por linha)",
  );
  await second.fill("x".repeat(1001));
  await dialog.getByRole("button", { name: "Salvar nova revisão" }).click();
  await expect(second).toHaveAccessibleDescription(
    /Alegação 2 — Informação que falta: Cada linha/,
  );
  await dialog
    .getByRole("button", {
      name: /Alegação 2 — Informação que falta: Cada linha/,
    })
    .click();
  await expect(second).toBeFocused();
  await expect(missing).toHaveValue("Lacuna preservada");
});

test("EVD-05: related-order errors focus the input and preserve the draft", async ({
  page,
}) => {
  await mockWorkspace(page);
  await page.route("**/api/v1/incidents/i/evidence?*", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: "source",
            kind: "document_span",
            title: "Fonte sintética",
            version: "1",
            source_system: "qa",
            temporal_role: "context",
            excerpt: "Trecho sintético",
          },
        ],
        next_cursor: null,
        total: 1,
      },
    }),
  );
  await page.getByRole("button", { name: "Preparar nova revisão" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Adicionar alegação" }).click();
  await dialog
    .getByLabel("Texto", { exact: true })
    .fill("Alegação sintética preservada.");
  await dialog.getByRole("checkbox", { name: /Fonte sintética/ }).check();
  const orders = dialog.getByLabel(
    "Pedidos relacionados (separados por vírgula)",
  );
  await orders.fill("P".repeat(201));
  await dialog.getByRole("button", { name: "Salvar nova revisão" }).click();
  await expect(orders).toHaveAttribute("aria-invalid", "true");
  await expect(orders).toHaveAccessibleDescription(
    /Alegação 1 — Pedidos relacionados: Cada referência de pedido aceita até 200 caracteres/,
  );
  await expect(orders).toBeFocused();
  await dialog.getByLabel("Texto", { exact: true }).focus();
  await dialog
    .getByRole("button", {
      name: /Alegação 1 — Pedidos relacionados: Cada referência de pedido/,
    })
    .click();
  await expect(orders).toBeFocused();
  await expect(orders).toHaveValue("P".repeat(201));
  await expect(dialog.getByLabel("Texto", { exact: true })).toHaveValue(
    "Alegação sintética preservada.",
  );
});

for (const terminal of ["failed", "cancelled", "expired"]) {
  test(`EVD-02: ${terminal} permits a new intention; uncertain delivery reuses its key`, async ({
    page,
  }) => {
    await mockWorkspace(page, "approved");
    const keys: string[] = [];
    let posts = 0;
    await page.route("**/api/v1/dossiers/d/exports", async (route) => {
      keys.push(route.request().headers()["idempotency-key"]);
      posts++;
      if (posts === 1 || posts === 3) return route.abort("failed");
      await route.fulfill({
        json: {
          id: posts === 2 ? "first" : "second",
          state: terminal,
          revision_id: "r",
          download_url: null,
          expires_at: null,
          error: null,
        },
      });
    });
    await page.route("**/api/v1/exports/*", (route) =>
      route.fulfill({
        json: {
          id: route.request().url().split("/").at(-1),
          state: terminal,
          revision_id: "r",
          download_url: null,
          expires_at: null,
          error: null,
        },
      }),
    );
    await page
      .getByRole("button", { name: "Preparar exportação", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Preparar exportação", exact: true }),
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "Preparar exportação", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Preparar nova exportação" })
      .click();
    const retry = page.getByRole("button", {
      name: "Preparar exportação",
      exact: true,
    });
    await expect(retry).toBeEnabled();
    await retry.click();
    expect(keys).toHaveLength(4);
    expect(keys[0]).toBe(keys[1]);
    expect(keys[2]).not.toBe(keys[1]);
    expect(keys[3]).toBe(keys[2]);
    await expect(
      page.getByText("Preparando a revisão autorizada…"),
    ).toHaveCount(0);
  });
}
