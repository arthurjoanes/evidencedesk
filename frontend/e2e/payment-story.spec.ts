import { expect, test } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { logout } from "./session";

// Opt-in: this story adds a manual dossier to a disposable seeded E2E project.
// No transport fixtures, DOM substitutions or generation requests are used.
test("payment story: two real sources, manual dossier and independent review", async ({
  page,
}) => {
  test.skip(
    process.env.ED_PAYMENT_STORY !== "1",
    "Requires an explicitly prepared, disposable EvidenceDesk E2E project.",
  );
  const output = process.env.ED_E2E_ARTIFACT_DIR ?? "artifacts";
  const shots = join(output, "screenshots");
  await mkdir(shots, { recursive: true });
  const seedIncidentId = "demo-aurora-09";
  const order = "PED-009-000";
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
  async function login(email: string) {
    await page.goto("/");
    await page.getByLabel("E-mail", { exact: true }).fill(email);
    await page
      .getByLabel("Senha", { exact: true })
      .fill(process.env.ED_E2E_PASSWORD ?? "EvidenceDesk-demo-2026!");
    await page.getByRole("button", { name: "Entrar", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Incidentes", exact: true }),
    ).toBeVisible();
    const response = await page.request.get("/api/v1/auth/session");
    expect(response.status()).toBe(200);
    const session = await response.json();
    expect(session.runtime.provider).toBe("disabled");
    expect(session.runtime.generation_enabled).toBe(false);
    return session;
  }
  async function get(path: string) {
    const response = await page.request.get("/api/v1" + path);
    expect(response.status(), path).toBe(200);
    return response.json();
  }
  async function capture(name: string, fullPage = true) {
    await page.evaluate(() => document.fonts.ready);
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: join(shots, name + ".png"),
      fullPage,
    });
  }
  const author = await login("ana@aurora.demo");
  const seedIncident = await get("/incidents/" + seedIncidentId);
  // A new normal application incident makes reruns independent of prior approvals.
  // The seeded source records and previous investigations are never reset.
  const created = await page.request.post("/api/v1/incidents", {
    headers: {
      "X-CSRF-Token": author.csrf_token,
      Origin: new URL(page.url()).origin,
    },
    data: {
      title: seedIncident.title,
      description:
        "Investigação sintética com as fontes e a janela de demo-aurora-09. Sem correção do pedido ou geração por modelo.",
      collection_id: seedIncident.collection_id,
      window: seedIncident.window,
    },
  });
  expect(created.status()).toBe(201);
  const incident = await created.json();
  const incidentId = incident.id;
  expect(incident.evidence_snapshot_id).toBe(seedIncident.evidence_snapshot_id);
  expect(incident.status).toBe("open");
  expect(incident.counts.orders).toBe(222);
  expect(incident.counts.divergences).toBe(2);
  const snapshotId = incident.evidence_snapshot_id;
  const query = new URLSearchParams({
    evidence_snapshot_id: snapshotId,
    order_reference: order,
  });
  const reconciliation = await get(
    `/incidents/${incidentId}/reconciliation?${query}`,
  );
  expect(
    reconciliation.items
      .map((item: { rule_code: string }) => item.rule_code)
      .sort(),
  ).toEqual(["payment_snapshot_mismatch", "transition_not_observed"]);
  expect(
    reconciliation.items.every(
      (item: { status: string }) => item.status === "divergence",
    ),
  ).toBe(true);
  const mismatch = reconciliation.items.find(
    (item: { rule_code: string }) =>
      item.rule_code === "payment_snapshot_mismatch",
  );
  expect(mismatch.evidence_ids).toHaveLength(2);
  const sources = await Promise.all(
    mismatch.evidence_ids.map((id: string) =>
      get(`/evidence/${id}?evidence_snapshot_id=${snapshotId}`),
    ),
  );
  const payment = sources.find((source) => source.kind === "source_event");
  const snapshot = sources.find((source) => source.kind === "order_snapshot");
  for (const source of sources) {
    expect(source.original).not.toBeNull();
    const original = await page.request.get(source.original.content_url);
    expect(original.status()).toBe(200);
    const bytes = await original.body();
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(
      source.sha256,
    );
    expect(bytes.length).toBe(source.original.byte_size);
  }
  const paymentRecord = JSON.parse(payment.canonical_text);
  const snapshotRecord = JSON.parse(snapshot.canonical_text);
  expect(paymentRecord.event_type).toBe("payment.confirmed");
  expect(paymentRecord.occurred_at).toBe("2026-07-09T12:00:30Z");
  expect(snapshotRecord.as_of).toBe("2026-07-09T12:10:00Z");
  expect(snapshotRecord.status).toBe("pending_payment");
  expect(snapshotRecord.order_reference).toBe("ORDERS-" + order);
  expect(paymentRecord.order_reference).toBe("PAYMENTS-" + order);
  expect(
    Date.parse(snapshotRecord.as_of) - Date.parse(paymentRecord.occurred_at),
  ).toBe(570_000);
  const timeline = await get(`/incidents/${incidentId}/timeline?${query}`);
  expect(
    timeline.items.some(
      (item: { event_type: string }) =>
        item.event_type === "order.payment_confirmed",
    ),
  ).toBe(false);
  const orderCoverage = reconciliation.coverage.filter(
    (item: { source_system: string }) => item.source_system === "orders",
  );
  expect(orderCoverage).toHaveLength(1);
  expect(orderCoverage[0].status).toBe("complete");
  expect(Date.parse(orderCoverage[0].from)).toBeLessThanOrEqual(
    Date.parse(paymentRecord.occurred_at),
  );
  expect(Date.parse(orderCoverage[0].to)).toBeGreaterThanOrEqual(
    Date.parse("2026-07-09T12:05:30Z"),
  );

  await page.setViewportSize({ width: 1440, height: 1280 });
  await page.goto(`/incidents/${incidentId}?order=${order}`);
  await expect(
    page.getByRole("heading", {
      name: "Pagamento confirmado e pedido pendente",
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Evidência 1", exact: true })
    .first()
    .click();
  const canonical = page.getByRole("region", {
    name: "Texto canônico da fonte",
    exact: true,
  });
  await expect(canonical).toHaveText(payment.canonical_text);
  await capture("01-pagamento-e-divergencias", false);
  await page
    .getByRole("button", { name: "Voltar à seleção", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Evidência 2", exact: true })
    .first()
    .click();
  await expect(canonical).toHaveText(snapshot.canonical_text);
  await capture("02-snapshot-pendente", false);
  const readerBox = await page
    .getByRole("region", { name: "Leitor de evidência" })
    .boundingBox();
  const textBox = await canonical.boundingBox();
  expect(readerBox).not.toBeNull();
  expect(textBox).not.toBeNull();
  await page.screenshot({
    path: join(shots, "02-snapshot-detalhe.png"),
    clip: {
      x: readerBox!.x,
      y: readerBox!.y,
      width: readerBox!.width,
      height: textBox!.y + textBox!.height - readerBox!.y + 40,
    },
  });
  await page
    .getByRole("button", { name: "Voltar à seleção", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Evidência 2", exact: true }).first(),
  ).toBeFocused();

  await page.getByRole("link", { name: "Dossiê", exact: true }).click();
  await page
    .getByRole("button", { name: "Criar dossiê manual", exact: true })
    .click();
  const summary =
    "PED-009-000: o pagamento foi confirmado às 12:00:30 UTC; às 12:10:00 UTC, o snapshot de pedidos ainda registra pendência. O recorte demonstra a divergência, mas não identifica sua causa nem comprova uma correção.";
  await page.getByLabel("Resumo da investigação").fill(summary);
  await page.getByLabel("Resultado do recorte").selectOption("evidence_found");
  await page
    .getByLabel("Lacunas do recorte (uma por linha)")
    .fill(
      "Não há evidência suficiente para atribuir a falha a um componente.\nNão foi consultado o estado atual do pedido fora deste snapshot.",
    );
  await page
    .getByLabel("Próximas verificações do recorte (uma por linha)")
    .fill(
      "Conferir o processamento da confirmação no serviço de pedidos, preservando os IDs e os horários das fontes.",
    );
  await page.getByRole("button", { name: "Adicionar alegação" }).click();
  await page
    .getByLabel("Texto", { exact: true })
    .fill(
      "Para PED-009-000, payments confirma o pagamento às 12:00:30 UTC de 09/07/2026; o snapshot de orders às 12:10:00 UTC ainda informa pending_payment. São registros incompatíveis neste recorte, sem causa estabelecida.",
    );
  await page
    .getByLabel("Pedidos relacionados (separados por vírgula)")
    .fill(order);
  await page.getByLabel("Localizar fontes para vincular").fill(order);
  await page
    .getByRole("checkbox", {
      name: new RegExp("payment\\.confirmed.*PAYMENTS-" + order),
    })
    .check();
  await page
    .getByRole("checkbox", {
      name: new RegExp("pending_payment.*ORDERS-" + order),
    })
    .check();
  await page.getByRole("button", { name: "Salvar dossiê manual" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect
    .poll(() => new URL(page.url()).searchParams.get("revision"))
    .toBeTruthy();
  const location = new URL(page.url());
  const dossierId = location.searchParams.get("dossier");
  const revisionId = location.searchParams.get("revision");
  expect(dossierId).toBeTruthy();
  expect(revisionId).toBeTruthy();
  const dossierPath = "/dossiers/" + dossierId;
  const revision = await get(dossierPath + "/revisions/" + revisionId);
  expect(revision.summary).toBe(summary);
  expect(revision.claims).toHaveLength(1);
  expect(
    revision.claims[0].evidence_links
      .map((link: { evidence_id: string }) => link.evidence_id)
      .sort(),
  ).toEqual([payment.id, snapshot.id].sort());
  expect(revision.review_status).toBe("draft");
  await page
    .getByRole("button", { name: "Enviar para revisão", exact: true })
    .click();
  await expect(
    page.getByText("Enviado para revisão", { exact: true }).last(),
  ).toBeVisible();
  const denial = await page.request.post("/api/v1" + dossierPath + "/reviews", {
    headers: {
      "X-CSRF-Token": author.csrf_token,
      "If-Match": revision.etag,
      Origin: location.origin,
    },
    data: {
      target_revision_id: revisionId,
      claim_ids: revision.claims.map(
        (claim: { claim_id: string }) => claim.claim_id,
      ),
      decision: "approved",
      reason: "Controle negativo: autora não pode aprovar.",
    },
  });
  expect(denial.status()).toBe(403);
  const selfReviewError = (await denial.json()).error.code;
  // Ana lacks the reviewer role. The stricter author-with-reviewer-role case
  // is separately covered by test_manual_workflow.py.
  expect(selfReviewError).toBe("reviewer_required");
  const dossierUrl = page.url();
  await logout(page);
  const reviewer = await login("bruno@aurora.demo");
  expect(reviewer.user.id).not.toBe(author.user.id);
  await page.goto(dossierUrl);
  await page
    .getByRole("button", { name: "Registrar decisão", exact: true })
    .click();
  const reason =
    "Ensaio automatizado com contas distintas. Foram conferidos o evento de pagamento, o snapshot posterior e os vínculos desta alegação. A causa e a correção do pedido permanecem não demonstradas. Esta aprovação verifica o fluxo, não substitui avaliação humana.";
  await page.getByLabel("Justificativa").fill(reason);
  await capture("03-decisao-da-revisao");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Registrar decisão", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const approved = await get(dossierPath + "/revisions/" + revisionId);
  expect(approved.review_status).toBe("approved");
  expect(approved.review.reviewed_by).toBe(reviewer.user.id);
  expect(approved.review.submitted_by).toBe(author.user.id);
  expect(approved.review.reason).toBe(reason);
  expect(approved.claims[0].support_status).toBe("reviewed");
  await capture("04-dossie-aprovado");
  await page.locator(".claim .source-button").first().click();
  await expect(canonical).not.toBeEmpty();
  await capture("05-dossie-com-fonte");
  await page.setViewportSize({ width: 390, height: 844 });
  // Responsive remount reauthorizes the source; fonts-ready alone is insufficient.
  await expect(canonical).toHaveText(payment.canonical_text);
  await capture("06-fonte-mobile");
  await page
    .getByRole("button", { name: "Voltar à seleção", exact: true })
    .click();
  await page.setViewportSize({ width: 1440, height: 1280 });
  await page
    .getByRole("button", { name: "Preparar exportação", exact: true })
    .click();
  const download = page.getByRole("link", { name: "Baixar HTML da revisão" });
  await expect(download).toBeVisible({ timeout: 30_000 });
  const exported = await page.request.get(
    (await download.getAttribute("href"))!,
  );
  expect(exported.status()).toBe(200);
  const html = await exported.text();
  expect(html).toContain(order);
  expect(html).toContain(reason);
  expect(html).toContain(payment.id);
  expect(html).toContain(snapshot.id);
  const after = await get(`/incidents/${incidentId}/reconciliation?${query}`);
  expect(after).toEqual(reconciliation);
  expect(generationPosts).toEqual([]);
  expect(errors).toEqual([]);
  await writeFile(
    join(output, "payment-story.json"),
    JSON.stringify(
      {
        recorded_at: new Date().toISOString(),
        browser_version: page.context().browser()?.version(),
        viewports: [
          { width: 1440, height: 1280 },
          { width: 390, height: 844 },
        ],
        scenario:
          "Synthetic seeded pending-payment incident; live UI/API, no provider generation",
        human_evaluation: false,
        incident_id: incidentId,
        seed_incident_id: seedIncidentId,
        source_snapshot_unchanged_from_seed: true,
        order_reference: order,
        snapshot_id: snapshotId,
        observed_counts: incident.counts,
        reconciliation,
        timeline,
        sources: sources.map((source) => ({
          ...source,
          canonical_text_sha256: createHash("sha256")
            .update(source.canonical_text)
            .digest("hex"),
        })),
        dossier_id: dossierId,
        revision: approved,
        author_id: author.user.id,
        reviewer_id: reviewer.user.id,
        self_review_status: denial.status(),
        self_review_error: selfReviewError,
        export: {
          status: exported.status(),
          sha256: createHash("sha256").update(html).digest("hex"),
          bytes: Buffer.byteLength(html),
        },
        reconciliation_unchanged_after_review: true,
        original_downloads_match_declared_hash_and_size: true,
        generation_posts: generationPosts.length,
        page_errors: errors,
        limitations: [
          "Automated use of distinct accounts is not human semantic review.",
          "Approval closes the investigation, not the operational payment mismatch.",
          "No source revocation, restore, paid generation or performance measurement in this journey.",
        ],
      },
      null,
      2,
    ) + "\n",
    "utf8",
  );
});
