import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import type {
  Dossier,
  Evidence,
  Incident,
  Revision,
  Session,
} from "../src/lib/contracts";

const password = process.env.ED_E2E_PASSWORD ?? "EvidenceDesk-demo-2026!";
const paymentOrder = "PED-009-000";

async function login(page: Page, email: string): Promise<Session> {
  await page.goto("/");
  await page.getByLabel("E-mail", { exact: true }).fill(email);
  await page.getByLabel("Senha", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Incidentes", exact: true }),
  ).toBeVisible();
  const session = await get<Session>(page, "/auth/session");
  expect(session.runtime.provider).toBe("disabled");
  expect(session.runtime.generation_enabled).toBe(false);
  return session;
}

async function get<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get("/api/v1" + path);
  expect(response.status(), path).toBe(200);
  return response.json() as Promise<T>;
}

async function post<T>(
  page: Page,
  session: Session,
  path: string,
  data: unknown,
  status: number,
  etag?: string,
): Promise<T> {
  const response = await page.request.post("/api/v1" + path, {
    data,
    headers: {
      Origin: new URL(page.url()).origin,
      "X-CSRF-Token": session.csrf_token,
      ...(etag ? { "If-Match": etag } : {}),
    },
  });
  expect(response.status(), path).toBe(status);
  return response.json() as Promise<T>;
}

type ReviewFixture = {
  incident: Incident;
  dossier: Dossier;
  revision: Revision;
};

async function prepareReview(
  page: Page,
  session: Session,
  seed: Incident,
  claims: {
    text: string;
    kind: "observed_fact" | "hypothesis";
    source: string;
    order?: string;
  }[],
  title: string,
  submit = true,
): Promise<ReviewFixture> {
  // These are fresh, normal API resources in the disposable test project.
  // The pinned before/after fixtures and seeded operational records stay intact.
  const incident = await post<Incident>(
    page,
    session,
    "/incidents",
    {
      title,
      description:
        "Fixture funcional sintética de UI/UX; aprovação por automação não equivale a avaliação humana.",
      collection_id: seed.collection_id,
      window: seed.window,
    },
    201,
  );
  const dossier = await post<Dossier>(
    page,
    session,
    "/incidents/" + incident.id + "/dossiers",
    {
      evidence_snapshot_id: seed.evidence_snapshot_id,
      summary: claims.length
        ? "A confirmação e o estado posterior divergem; a causa e a correção permanecem não demonstradas."
        : "A evidência é insuficiente para atribuir uma causa; nenhuma alegação foi criada.",
      outcome: claims.length ? "conflicting_evidence" : "insufficient_evidence",
      claims: claims.map((claim) => ({
        claim_id: null,
        kind: claim.kind,
        text: claim.text,
        order_references: claim.order ? [claim.order] : [],
        evidence_links: [{ evidence_id: claim.source, relation: "supports" }],
        support_status: "pending_review",
        missing_information: [],
        suggested_checks: [],
      })),
      missing_information: [
        "A causa e o estado atual precisam de confirmação.",
      ],
      suggested_checks: ["Conferir as fontes e a cobertura do recorte."],
    },
    201,
  );
  let revision = await get<Revision>(
    page,
    "/dossiers/" + dossier.id + "/revisions/" + dossier.current_revision_id,
  );
  if (submit) {
    revision = await post<Revision>(
      page,
      session,
      "/dossiers/" + dossier.id + "/submit",
      { target_revision_id: revision.id },
      200,
      revision.etag,
    );
    expect(revision.review_status).toBe("submitted");
  }
  return { incident, dossier, revision };
}

function dossierURL(fixture: ReviewFixture) {
  const query = new URLSearchParams({
    tab: "dossier",
    dossier: fixture.dossier.id,
    revision: fixture.revision.id,
    snapshot: fixture.dossier.evidence_snapshot_id,
  });
  return "/incidents/" + fixture.incident.id + "?" + query;
}

async function closeSource(page: Page) {
  await page
    .getByRole("button", { name: "Voltar à seleção", exact: true })
    .press("Enter");
  await expect
    .poll(() => new URL(page.url()).searchParams.get("evidence"))
    .toBeNull();
  await expect
    .poll(() =>
      page.evaluate(() => !!document.activeElement?.closest(".work-content")),
    )
    .toBe(true);
}

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

test("source search survives tabs and reload; direct source links close by keyboard at mobile and desktop", async ({
  page,
}) => {
  await login(page, "ana@aurora.demo");
  const seed = await get<Incident>(page, "/incidents/demo-aurora-09");
  const route =
    "/incidents/" +
    seed.id +
    "?" +
    new URLSearchParams({
      tab: "sources",
      snapshot: seed.evidence_snapshot_id,
      order: paymentOrder,
      q: "Pagamento",
    });
  await page.goto(route);
  const search = page.getByRole("textbox", { name: "Buscar nas fontes" });
  await search.fill(paymentOrder);
  await search.press("Enter");
  await expect
    .poll(() => new URL(page.url()).searchParams.get("source_q"))
    .toBe(paymentOrder);
  expect(new URL(page.url()).searchParams.get("snapshot")).toBe(
    seed.evidence_snapshot_id,
  );
  expect(new URL(page.url()).searchParams.get("order")).toBe(paymentOrder);
  expect(new URL(page.url()).searchParams.get("q")).toBe("Pagamento");
  await expect(
    page.getByRole("button", { name: "Conferir fonte", exact: true }).first(),
  ).toBeVisible();
  await page.getByRole("link", { name: "Linha do tempo", exact: true }).click();
  await page.getByRole("link", { name: "Fontes", exact: true }).click();
  await expect(search).toHaveValue(paymentOrder);
  await page.reload();
  await expect(search).toHaveValue(paymentOrder);
  await search.fill("QA-UIUX-sem-fonte-62a4");
  await search.press("Enter");
  await expect(
    page.getByText("Nenhuma fonte encontrada", { exact: true }),
  ).toBeVisible();
  await search.fill(paymentOrder);
  await search.press("Enter");
  const trigger = page
    .getByRole("button", { name: "Conferir fonte", exact: true })
    .first();
  await trigger.focus();
  await trigger.press("Enter");
  const canonical = page.getByRole("region", {
    name: "Texto canônico da fonte",
    exact: true,
  });
  await expect(canonical).not.toBeEmpty();
  const sourceURL = page.url();
  const id = new URL(sourceURL).searchParams.get("evidence");
  const source = await get<Evidence>(
    page,
    "/evidence/" + id + "?evidence_snapshot_id=" + seed.evidence_snapshot_id,
  );
  for (const width of [320, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(sourceURL); // A new document has no captured source opener.
    await expect(canonical).toHaveText(source.canonical_text!);
    await closeSource(page);
    await expect(search).toHaveValue(paymentOrder);
  }
  await page.goto(route);
  await expect(search).toBeVisible();
  await expect(page.locator(".work-content")).not.toBeFocused();
});

test("two claims and abstention require explicit review; citation context rejects wrong association and fresh revision denial", async ({
  page,
  browser,
}, testInfo) => {
  test.setTimeout(120_000);
  await page.clock.install();
  const authorContext = await browser.newContext({
    baseURL: testInfo.project.use.baseURL,
  });
  try {
    const author = await authorContext.newPage();
    const authorSession = await login(author, "ana@aurora.demo");
    const reviewerSession = await login(page, "bruno@aurora.demo");
    expect(reviewerSession.user.id).not.toBe(authorSession.user.id);
    const seed = await get<Incident>(author, "/incidents/demo-aurora-09");
    const reconciliation = await get<{
      items: { rule_code: string; evidence_ids: string[] }[];
    }>(
      author,
      "/incidents/" +
        seed.id +
        "/reconciliation?" +
        new URLSearchParams({
          evidence_snapshot_id: seed.evidence_snapshot_id,
          order_reference: paymentOrder,
        }),
    );
    const mismatch = reconciliation.items.find(
      (item) => item.rule_code === "payment_snapshot_mismatch",
    )!;
    expect(mismatch.evidence_ids).toHaveLength(2);
    const sources = await Promise.all(
      mismatch.evidence_ids.map((id) =>
        get<Evidence>(
          author,
          "/evidence/" +
            id +
            "?evidence_snapshot_id=" +
            seed.evidence_snapshot_id,
        ),
      ),
    );
    const payment = sources.find((source) => source.kind === "source_event")!;
    const snapshot = sources.find(
      (source) => source.kind === "order_snapshot",
    )!;
    const fixture = await prepareReview(
      author,
      authorSession,
      seed,
      [
        {
          text: "QA UIUX: payments registra a confirmação do pedido sintético neste recorte.",
          kind: "observed_fact",
          source: payment.id,
          order: paymentOrder,
        },
        {
          text: "QA UIUX: o snapshot posterior de orders mantém pending_payment; a causa permanece desconhecida.",
          kind: "observed_fact",
          source: snapshot.id,
          order: paymentOrder,
        },
      ],
      "QA UIUX revisão independente de duas alegações",
    );
    await page.goto(dossierURL(fixture));
    const reviewTrigger = page.getByRole("button", {
      name: "Registrar decisão",
      exact: true,
    });
    await reviewTrigger.focus();
    await reviewTrigger.press("Enter");
    const dialog = page.getByRole("dialog");
    const submit = dialog.getByRole("button", {
      name: "Registrar decisão",
      exact: true,
    });
    await expect(dialog.getByLabel("Decisão")).toHaveValue("");
    await expect(dialog.getByRole("checkbox")).toHaveCount(2);
    await expect(dialog.getByRole("checkbox").first()).not.toBeChecked();
    const modalSource = dialog.getByRole("button", {
      name: "Conferir fonte 1 da alegação 1",
      exact: true,
    });
    await modalSource.press("Enter");
    await expect(
      dialog.getByRole("region", { name: "Alegação citada" }),
    ).toContainText(fixture.revision.claims[0].text);
    await expect(
      dialog.getByRole("region", { name: "Texto canônico da fonte" }),
    ).toHaveText(payment.canonical_text!);
    // A controlled temporary session failure remounts the portal; recovery
    // still checks the actual session and source without a replacement login.
    let unavailable = true;
    let sessionChecks = 0;
    await page.route("**/api/v1/auth/session", async (route) => {
      sessionChecks++;
      if (!unavailable) {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 503,
        json: {
          error: {
            code: "controlled_session_state",
            message: "Indisponibilidade temporária controlada no QA de foco.",
            request_id: "qa-uiux-focus-revalidation",
            retryable: true,
          },
        },
      });
    });
    await refocusAfterStale(page);
    await expect.poll(() => sessionChecks).toBeGreaterThan(0);
    const blocked = page.getByRole("region", { name: "Verificação da sessão" });
    await expect(blocked.getByRole("alert")).toBeVisible();
    await expect(dialog).toHaveCount(0);
    await expect(page.locator(".authenticated-content")).toBeHidden();
    unavailable = false;
    await blocked
      .getByRole("button", { name: "Tentar novamente", exact: true })
      .press("Enter");
    await expect(
      dialog.getByRole("region", { name: "Texto canônico da fonte" }),
    ).toHaveText(payment.canonical_text!);
    await dialog
      .getByRole("button", { name: "Voltar à seleção", exact: true })
      .press("Enter");
    await expect(modalSource).toBeFocused();
    await page.unroute("**/api/v1/auth/session");
    await dialog
      .getByLabel("Justificativa")
      .fill("Rascunho descartável de QA.");
    page.once("dialog", (confirmation) => void confirmation.accept());
    await dialog.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(reviewTrigger).toBeFocused();
    await reviewTrigger.press("Enter");
    await expect(dialog.getByLabel("Decisão")).toHaveValue("");
    await expect(dialog.getByRole("checkbox").first()).not.toBeChecked();
    await dialog
      .getByLabel("Justificativa")
      .fill(
        "Ensaio automatizado das fontes e da independência; não é avaliação humana.",
      );
    await expect(submit).toBeDisabled();
    await dialog.getByLabel("Decisão").selectOption("approved");
    await expect(submit).toBeDisabled();
    const first = dialog.getByRole("checkbox", {
      name: "Conferi a alegação 1",
      exact: true,
    });
    const second = dialog.getByRole("checkbox", {
      name: "Conferi a alegação 2",
      exact: true,
    });
    await first.check();
    await expect(submit).toBeDisabled();
    await second.check();
    await expect(submit).toBeEnabled();
    await first.uncheck();
    await expect(submit).toBeDisabled();
    await first.check();
    const approved = page.waitForResponse(
      (response) =>
        response
          .url()
          .endsWith("/api/v1/dossiers/" + fixture.dossier.id + "/reviews") &&
        response.request().method() === "POST",
    );
    await submit.click();
    const reviewResponse = await approved;
    expect(reviewResponse.status()).toBe(200);
    const payload = reviewResponse.request().postDataJSON();
    expect(payload.target_revision_id).toBe(fixture.revision.id);
    expect(payload.claim_ids.sort()).toEqual(
      fixture.revision.claims.map((claim) => claim.claim_id).sort(),
    );
    expect(reviewResponse.request().headers()["if-match"]).toBe(
      fixture.revision.etag,
    );
    await expect(dialog).toHaveCount(0);
    await expect(reviewTrigger).toHaveCount(0);
    await expect(page.locator("#main-content")).toBeFocused();
    const reviewed = await get<Revision>(
      page,
      "/dossiers/" + fixture.dossier.id + "/revisions/" + fixture.revision.id,
    );
    expect(reviewed.review_status).toBe("approved");
    expect(reviewed.review!.reviewed_by).toBe(reviewerSession.user.id);
    const citation = page.locator(".claim .source-button").first();
    await citation.focus();
    await citation.press("Enter");
    const quote = page.getByRole("region", { name: "Alegação citada" });
    const canonical = page.getByRole("region", {
      name: "Texto canônico da fonte",
      exact: true,
    });
    await expect(quote).toContainText(reviewed.claims[0].text);
    await expect(canonical).toHaveText(payment.canonical_text!);
    const citedURL = new URL(page.url());
    expect(citedURL.searchParams.get("citation_dossier")).toBe(
      fixture.dossier.id,
    );
    expect(citedURL.searchParams.get("citation_revision")).toBe(reviewed.id);
    expect(citedURL.searchParams.get("citation_claim")).toBe(
      reviewed.claims[0].claim_id,
    );
    expect(citedURL.searchParams.get("evidence_snapshot")).toBe(
      fixture.dossier.evidence_snapshot_id,
    );
    const otherCitation = page.getByRole("button", {
      name: "Conferir fonte 1 da alegação 2",
      exact: true,
    });
    await otherCitation.press("Enter");
    await expect(quote).toContainText(reviewed.claims[1].text);
    await expect(canonical).toHaveText(snapshot.canonical_text!);
    await page.goBack();
    await expect(quote).toContainText(reviewed.claims[0].text);
    await expect(canonical).toHaveText(payment.canonical_text!);
    await page
      .getByRole("button", { name: "Voltar à seleção", exact: true })
      .press("Enter");
    await expect(citation).toBeFocused();
    await expect(otherCitation).not.toBeFocused();
    for (const width of [320, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(citedURL.href);
      await expect(quote).toContainText(reviewed.claims[0].text);
      await expect(canonical).toHaveText(payment.canonical_text!);
      await closeSource(page);
    }
    const unrelated = new URL(citedURL.href);
    unrelated.searchParams.set("citation_claim", reviewed.claims[1].claim_id);
    await page.goto(unrelated.href);
    await expect(
      page
        .getByRole("region", { name: "Leitor de evidência", exact: true })
        .getByRole("alert"),
    ).toContainText("A citação não pertence");
    await expect(quote).toHaveCount(0);
    await expect(canonical).toHaveCount(0);
    await page.goto(citedURL.href);
    await expect(quote).toContainText(reviewed.claims[0].text);
    await closeSource(page);
    // Controlled transport denial after a real authorized read: the test proves
    // the UI's revalidation boundary, not an actual ACL change or API outage.
    let requests = 0;
    let release!: () => void;
    const waiting = new Promise<void>((resolve) => {
      release = resolve;
    });
    const revisionRoute =
      "**/api/v1/dossiers/" + fixture.dossier.id + "/revisions/" + reviewed.id;
    await page.route(revisionRoute, async (route) => {
      requests++;
      await waiting;
      await route.fulfill({
        status: 403,
        json: {
          error: {
            code: "controlled_citation_denied",
            message: "Revisão indisponível no cenário controlado.",
            request_id: "qa-citation-revalidation",
            retryable: false,
          },
        },
      });
    });
    await citation.press("Enter");
    try {
      await expect.poll(() => requests).toBeGreaterThan(0);
      await expect(quote).toHaveCount(0);
      await expect(canonical).toHaveCount(0);
    } finally {
      release();
    }
    await expect(
      page
        .getByRole("region", { name: "Leitor de evidência", exact: true })
        .getByRole("alert"),
    ).toContainText("Revisão indisponível no cenário controlado.");
    await expect(quote).toHaveCount(0);
    await expect(canonical).toHaveCount(0);
    await page.unroute(revisionRoute);
    const abstention = await prepareReview(
      author,
      authorSession,
      seed,
      [],
      "QA UIUX confirmação explícita da abstenção",
    );
    await page.goto(dossierURL(abstention));
    await page
      .getByRole("button", { name: "Registrar decisão", exact: true })
      .click();
    await expect(dialog.getByRole("checkbox")).toHaveCount(1);
    await dialog
      .getByLabel("Justificativa")
      .fill(
        "Ensaio automatizado: foram lidas a abstenção e as lacunas; não demonstra qualidade semântica.",
      );
    await dialog.getByLabel("Decisão").selectOption("approved");
    await expect(submit).toBeDisabled();
    await dialog
      .getByRole("checkbox", {
        name: "Conferi a abstenção e as lacunas desta revisão",
        exact: true,
      })
      .check();
    expect(
      (
        await new AxeBuilder({ page })
          .include('[role="dialog"]')
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
          .analyze()
      ).violations,
    ).toEqual([]);
    const approvedAbstention = page.waitForResponse(
      (response) =>
        response
          .url()
          .endsWith("/api/v1/dossiers/" + abstention.dossier.id + "/reviews") &&
        response.request().method() === "POST",
    );
    await submit.click();
    const abstentionResponse = await approvedAbstention;
    expect(abstentionResponse.status()).toBe(200);
    expect(abstentionResponse.request().postDataJSON().claim_ids).toEqual([]);
    expect((await abstentionResponse.json()).review_status).toBe("approved");
  } finally {
    await authorContext.close();
  }
});

test("a citation deep link cannot disclose a real dossier from another tenant", async ({
  page,
  browser,
}, testInfo) => {
  const otherContext = await browser.newContext({
    baseURL: testInfo.project.use.baseURL,
  });
  try {
    const other = await otherContext.newPage();
    const otherSession = await login(other, "carla@horizonte.demo");
    const otherSeed = await get<Incident>(
      other,
      "/incidents/demo-horizonte-01",
    );
    const otherSources = await get<{ items: { id: string }[] }>(
      other,
      "/incidents/" +
        otherSeed.id +
        "/evidence?" +
        new URLSearchParams({
          evidence_snapshot_id: otherSeed.evidence_snapshot_id,
          limit: "1",
        }),
    );
    expect(otherSources.items).toHaveLength(1);
    const privateText =
      "QA UIUX: hipótese sintética do tenant Horizonte, inacessível a Aurora.";
    const otherFixture = await prepareReview(
      other,
      otherSession,
      otherSeed,
      [
        {
          text: privateText,
          kind: "hypothesis",
          source: otherSources.items[0].id,
        },
      ],
      "QA UIUX outro tenant",
      false,
    );
    const reviewer = await login(page, "bruno@aurora.demo");
    expect(reviewer.tenant.id).not.toBe(otherSession.tenant.id);
    const ownSeed = await get<Incident>(page, "/incidents/demo-aurora-09");
    const ownSources = await get<{ items: { id: string }[] }>(
      page,
      "/incidents/" +
        ownSeed.id +
        "/evidence?" +
        new URLSearchParams({
          evidence_snapshot_id: ownSeed.evidence_snapshot_id,
          limit: "1",
        }),
    );
    const denied = page.waitForResponse(
      (response) =>
        response
          .url()
          .endsWith("/api/v1/dossiers/" + otherFixture.dossier.id) &&
        response.status() === 404,
    );
    await page.goto(
      "/incidents/" +
        ownSeed.id +
        "?" +
        new URLSearchParams({
          tab: "sources",
          snapshot: ownSeed.evidence_snapshot_id,
          evidence: ownSources.items[0].id,
          evidence_snapshot: ownSeed.evidence_snapshot_id,
          citation_dossier: otherFixture.dossier.id,
          citation_revision: otherFixture.revision.id,
          citation_claim: otherFixture.revision.claims[0].claim_id,
        }),
    );
    await denied;
    await expect(
      page
        .getByRole("region", { name: "Leitor de evidência", exact: true })
        .getByRole("alert"),
    ).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Alegação citada" }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("region", {
        name: "Texto canônico da fonte",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(await page.locator("body").innerText()).not.toContain(privateText);
    const forbidden = await page.request.get(
      "/api/v1/dossiers/" +
        otherFixture.dossier.id +
        "/revisions/" +
        otherFixture.revision.id,
    );
    expect(forbidden.status()).toBe(404);
    expect(await forbidden.text()).not.toContain(privateText);
  } finally {
    await otherContext.close();
  }
});
