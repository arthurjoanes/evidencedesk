import { expect, test, type Browser } from "@playwright/test";
import { mkdir, readFile, realpath, writeFile } from "node:fs/promises";
import { isAbsolute, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import {
  apiErrorSchema,
  dossierSchema,
  evidenceSchema,
  incidentSchema,
  revisionSchema,
  sessionSchema,
} from "../src/lib/contracts";

const identifier = z.string().min(1).max(200);
const restoreCaseSchema = z.object({
  run_id: identifier,
  target_project: z
    .string()
    .regex(/^pf-evidencedesk-restore-[a-z0-9][a-z0-9-]{0,27}$/),
  ledger_sequence: z.number().int().nonnegative(),
  survivor_incident: incidentSchema
    .partial()
    .required({ id: true, title: true }),
  erased: z.object({
    evidence: identifier,
    snapshot: identifier,
    dossier: identifier,
  }),
});

const reviewTargetSchema = z.object({
  incident_id: identifier,
  dossier_id: identifier,
  revision_id: identifier,
});
const reviewCaptureCaseSchema = z
  .object({
    run_id: identifier,
    approved: reviewTargetSchema.extend({
      expected_source_ids: z.array(identifier).optional(),
    }),
    conflict: reviewTargetSchema,
  })
  .refine((value) => value.approved.dossier_id !== value.conflict.dossier_id, {
    message:
      "Approval and edit-conflict captures require distinct existing dossiers.",
  });

async function reviewCaptureConfiguration() {
  if (process.env.ED_RESTORE_CASE_PATH) {
    throw new Error(
      "Pre-backup review captures must never run with a restore case.",
    );
  }
  const config = await captureConfiguration("ED_REVIEW_CAPTURE_CASE_PATH");
  const reviewCase = reviewCaptureCaseSchema.parse(
    JSON.parse(await readFile(config.casePath, "utf8")),
  );
  return { ...config, reviewCase };
}

function dossierLocation(target: z.infer<typeof reviewTargetSchema>) {
  return (
    "/incidents/" +
    encodeURIComponent(target.incident_id) +
    "?" +
    new URLSearchParams({
      tab: "dossier",
      dossier: target.dossier_id,
      revision: target.revision_id,
    })
  );
}

test("ED03 approved: capture an existing approved revision and its real source", async ({
  browser,
}) => {
  test.skip(
    !process.env.ED_REVIEW_CAPTURE_CASE_PATH,
    "Requires existing approved and conflict dossier cases.",
  );
  const config = await reviewCaptureConfiguration();
  const target = config.reviewCase.approved;
  const session = await freshSession(browser, config.baseURL);
  const { context, page } = session;
  try {
    const dossierPath =
      "/api/v1/dossiers/" + encodeURIComponent(target.dossier_id);
    const dossierResponse = await page.request.get(dossierPath);
    expect(dossierResponse.status()).toBe(200);
    const dossier = dossierSchema.parse(await dossierResponse.json());
    expect(dossier.incident_id).toBe(target.incident_id);
    expect(dossier.approved_revision_id).toBe(target.revision_id);
    const revisionResponse = await page.request.get(
      dossierPath + "/revisions/" + encodeURIComponent(target.revision_id),
    );
    expect(revisionResponse.status()).toBe(200);
    const revision = revisionSchema.parse(await revisionResponse.json());
    expect(revision.review_status).toBe("approved");
    const sourceIds = revision.claims.flatMap((claim) =>
      claim.evidence_links.map((link) => link.evidence_id),
    );
    expect(
      sourceIds.length,
      "The approved capture needs at least one real linked source",
    ).toBeGreaterThan(0);
    for (const expected of target.expected_source_ids ?? [])
      expect(sourceIds).toContain(expected);
    const claimIndex = revision.claims.findIndex(
      (claim) => claim.evidence_links.length > 0,
    );
    const sourceId = revision.claims[claimIndex].evidence_links[0].evidence_id;
    const sourcePath = "/api/v1/evidence/" + encodeURIComponent(sourceId);
    const sourceResponse = await page.request.get(
      sourcePath +
        "?" +
        new URLSearchParams({
          evidence_snapshot_id: dossier.evidence_snapshot_id,
        }),
    );
    expect(sourceResponse.status()).toBe(200);
    const source = evidenceSchema.parse(await sourceResponse.json());
    await page.goto(dossierLocation(target));
    await expect(
      page.getByText("Aprovado", { exact: true }).last(),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Preparar exportação", exact: true }),
    ).toBeVisible();
    const approvedImage = join(
      config.artifacts,
      "screenshots",
      "ed03-approved-desktop.png",
    );
    await page.screenshot({ path: approvedImage, fullPage: true });
    const sourceRead = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === sourcePath &&
        response.status() === 200 &&
        url.searchParams.get("evidence_snapshot_id") ===
          dossier.evidence_snapshot_id
      );
    });
    await page
      .locator(".claim")
      .nth(claimIndex)
      .locator(".source-button")
      .first()
      .click();
    await sourceRead;
    const reader = page.getByRole("region", {
      name: "Leitor de evidência",
      exact: true,
    });
    await expect(
      reader.getByRole("heading", { name: source.title, exact: true }),
    ).toBeVisible();
    await reader
      .getByRole("button", { name: "Texto canônico", exact: true })
      .click();
    await expect(
      reader.getByRole("region", {
        name: "Texto canônico da fonte",
        exact: true,
      }),
    ).toHaveText(source.canonical_text);
    const sourceImage = join(
      config.artifacts,
      "screenshots",
      "ed03-approved-source-desktop.png",
    );
    await page.screenshot({ path: sourceImage, fullPage: true });
    expect(session.generationPosts).toEqual([]);
    expect(session.blockedRequests).toEqual([]);
    expect(session.pageErrors).toEqual([]);
    await writeFile(
      join(config.artifacts, "ed03-approved-proof.json"),
      JSON.stringify(
        {
          status: "passed",
          recorded_at: new Date().toISOString(),
          run_id: config.reviewCase.run_id,
          scenario: "existing_approved_revision_with_source",
          ...target,
          evidence_snapshot_id: dossier.evidence_snapshot_id,
          opened_source_id: sourceId,
          source_sha256: source.sha256,
          generation_post_attempts: session.generationPosts,
          screenshots: [approvedImage, sourceImage],
        },
        null,
        2,
      ) + "\n",
      "utf8",
    );
  } finally {
    await context.close();
  }
});

test("ED03 conflict: real concurrent revision returns 409 and preserves the editor draft", async ({
  browser,
}) => {
  test.skip(
    !process.env.ED_REVIEW_CAPTURE_CASE_PATH,
    "Requires an existing dedicated edit-conflict case.",
  );
  if (process.env.ED_RESTORE_CASE_PATH)
    throw new Error(
      "Edit-conflict capture is forbidden during restore reading.",
    );
  test.skip(
    process.env.ED_REVIEW_CAPTURE_ALLOW_WRITE !== "1",
    "Requires explicit pre-backup ED_REVIEW_CAPTURE_ALLOW_WRITE=1.",
  );
  const config = await reviewCaptureConfiguration();
  const target = config.reviewCase.conflict;
  const dossierPath =
    "/api/v1/dossiers/" + encodeURIComponent(target.dossier_id);
  const revisionPath = dossierPath + "/revisions";
  const session = await freshSession(browser, config.baseURL, revisionPath);
  const { context, page } = session;
  try {
    const dossierResponse = await page.request.get(dossierPath);
    expect(dossierResponse.status()).toBe(200);
    const dossier = dossierSchema.parse(await dossierResponse.json());
    expect(dossier.incident_id).toBe(target.incident_id);
    expect(dossier.current_revision_id).toBe(target.revision_id);
    const baseResponse = await page.request.get(
      revisionPath + "/" + encodeURIComponent(target.revision_id),
    );
    expect(baseResponse.status()).toBe(200);
    const base = revisionSchema.parse(await baseResponse.json());
    await page.goto(dossierLocation(target));
    await page
      .getByRole("button", { name: "Preparar revisão", exact: true })
      .click();
    const dialog = page.getByRole("dialog");
    const draft =
      base.summary.slice(0, 3500) +
      "\nRascunho concorrente de verificação: preservar este texto até comparar as revisões.";
    await dialog.getByLabel("Resumo da investigação").fill(draft);
    // Same real revision contract used by investigation.spec.ts; no synthetic API response.
    const concurrentResponse = await page.request.post(revisionPath, {
      headers: {
        Origin: config.baseURL,
        "X-CSRF-Token": session.session.csrf_token,
        "If-Match": base.etag,
      },
      data: {
        base_revision_id: base.id,
        summary: base.summary,
        claims: base.claims.map((claim) => ({
          ...claim,
          support_status: "pending_review",
        })),
        outcome: base.outcome,
        missing_information: base.missing_information ?? [],
        suggested_checks: base.suggested_checks ?? [],
      },
    });
    expect(concurrentResponse.status()).toBe(201);
    const concurrent = revisionSchema.parse(await concurrentResponse.json());
    const rejectedSave = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === revisionPath &&
        response.request().method() === "POST" &&
        response.status() === 409,
    );
    await dialog
      .getByRole("button", { name: "Salvar nova revisão", exact: true })
      .click();
    const rejection = apiErrorSchema.parse(await (await rejectedSave).json());
    expect(rejection.error.code).toBe("revision_conflict");
    const preserved = dialog.getByText(
      "A revisão-base mudou. Seu texto foi preservado.",
      { exact: false },
    );
    await expect(preserved).toBeVisible();
    await expect(dialog.getByLabel("Resumo da investigação")).toHaveValue(
      draft,
    );
    const currentResponse = await page.request.get(dossierPath);
    expect(currentResponse.status()).toBe(200);
    expect(
      dossierSchema.parse(await currentResponse.json()).current_revision_id,
    ).toBe(concurrent.id);
    await preserved.scrollIntoViewIfNeeded();
    const screenshot = join(
      config.artifacts,
      "screenshots",
      "ed03-conflict-preserved-draft-desktop.png",
    );
    await page.screenshot({ path: screenshot, fullPage: true });
    expect(session.generationPosts).toEqual([]);
    expect(session.blockedRequests).toEqual([]);
    expect(session.pageErrors).toEqual([]);
    await writeFile(
      join(config.artifacts, "ed03-conflict-proof.json"),
      JSON.stringify(
        {
          status: "passed",
          recorded_at: new Date().toISOString(),
          run_id: config.reviewCase.run_id,
          scenario: "optimistic_edit_conflict",
          ...target,
          concurrent_revision_id: concurrent.id,
          rejected_status: 409,
          rejected_code: rejection.error.code,
          draft_preserved: true,
          generation_post_attempts: session.generationPosts,
          screenshots: [screenshot],
        },
        null,
        2,
      ) + "\n",
      "utf8",
    );
  } finally {
    await context.close();
  }
});
const stableIncidentFields = [
  "id",
  "title",
  "description",
  "status",
  "collection_id",
  "window",
  "evidence_snapshot_id",
  "counts",
  "coverage",
] as const;

function requiredEnvironment(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(name + " must be explicitly configured.");
  return value;
}

async function captureConfiguration(caseEnvironment: string) {
  const base = new URL(requiredEnvironment("ED_E2E_BASE_URL"));
  if (
    base.protocol !== "http:" ||
    !["127.0.0.1", "localhost", "[::1]"].includes(base.hostname) ||
    base.username ||
    base.password ||
    base.pathname !== "/" ||
    base.search ||
    base.hash
  ) {
    throw new Error("Capture requires an explicit HTTP loopback origin.");
  }
  const repository = await realpath(
    fileURLToPath(new URL("../../", import.meta.url)),
  );
  const casePath = await realpath(requiredEnvironment(caseEnvironment));
  const artifacts = await realpath(requiredEnvironment("ED_E2E_ARTIFACT_DIR"));
  for (const path of [casePath, artifacts]) {
    const fromRepository = relative(repository, path);
    if (
      path.toLowerCase().includes("onedrive") ||
      !(
        fromRepository.startsWith(
          ".." + (process.platform === "win32" ? "\\" : "/"),
        ) || isAbsolute(fromRepository)
      )
    ) {
      throw new Error(
        "Capture case and artifacts must be private, outside the repository and OneDrive.",
      );
    }
  }
  await mkdir(join(artifacts, "screenshots"), { recursive: true });
  return { baseURL: base.origin, casePath, artifacts };
}

async function freshSession(
  browser: Browser,
  baseURL: string,
  allowedWrite?: string,
) {
  const context = await browser.newContext({
    baseURL,
    viewport: { width: 1440, height: 1000 },
    serviceWorkers: "block",
    storageState: { cookies: [], origins: [] },
  });
  const blockedRequests: string[] = [];
  const generationPosts: string[] = [];
  // This guard only aborts unexpected traffic. Every displayed response remains real.
  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    if (
      method === "POST" &&
      /^\/api\/v1\/incidents\/[^/]+\/runs\/?$/.test(url.pathname)
    ) {
      generationPosts.push(url.pathname);
    }
    const allowed =
      ["GET", "HEAD", "OPTIONS"].includes(method) ||
      (method === "POST" &&
        ["/api/v1/auth/login", allowedWrite].includes(url.pathname));
    if (
      url.origin !== baseURL ||
      !allowed ||
      generationPosts.includes(url.pathname)
    ) {
      blockedRequests.push(method + " " + url.pathname);
      await route.abort("blockedbyclient");
      return;
    }
    await route.continue();
  });
  const page = await context.newPage();
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try {
    await page.goto("/");
    await page.getByLabel("E-mail", { exact: true }).fill("admin@aurora.demo");
    await page
      .getByLabel("Senha", { exact: true })
      .fill(process.env.ED_E2E_PASSWORD ?? "EvidenceDesk-demo-2026!");
    await page.getByRole("button", { name: "Entrar", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Incidentes", exact: true }),
    ).toBeVisible();
    const response = await page.request.get("/api/v1/auth/session");
    expect(response.status()).toBe(200);
    const session = sessionSchema.parse(await response.json());
    expect(session.user.role).toBe("tenant_admin");
    return {
      context,
      page,
      session,
      blockedRequests,
      generationPosts,
      pageErrors,
    };
  } catch (error) {
    await context.close();
    throw error;
  }
}

test("restore read: surviving incident and reconciled erasures through real UI and API", async ({
  browser,
}) => {
  test.skip(
    !process.env.ED_RESTORE_CASE_PATH,
    "Requires the runner's verified restore case.",
  );
  const config = await captureConfiguration("ED_RESTORE_CASE_PATH");
  const restore = restoreCaseSchema.parse(
    JSON.parse(await readFile(config.casePath, "utf8")),
  );
  const session = await freshSession(browser, config.baseURL);
  const { context, page } = session;
  try {
    expect(session.session.runtime.generation_enabled).toBe(false);
    expect(session.session.runtime.provider).toBe("disabled");
    const survivorPath =
      "/incidents/" + encodeURIComponent(restore.survivor_incident.id);
    const survivorResponse = await page.request.get("/api/v1" + survivorPath);
    expect(survivorResponse.status()).toBe(200);
    const survivor = incidentSchema.parse(await survivorResponse.json());
    const fields = stableIncidentFields.filter((field) =>
      Object.hasOwn(restore.survivor_incident, field),
    );
    const expected = Object.fromEntries(
      fields.map((field) => [field, restore.survivor_incident[field]]),
    );
    const actual = Object.fromEntries(
      fields.map((field) => [field, survivor[field]]),
    );
    expect(actual).toEqual(expected);
    await page.goto(survivorPath);
    await expect(
      page.getByRole("heading", { name: survivor.title, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByLabel("Snapshot em leitura", { exact: true }),
    ).toHaveValue(survivor.evidence_snapshot_id);
    await expect(
      page.getByRole("button", { name: "Investigar com IA", exact: true }),
    ).toBeDisabled();
    await expect(
      page
        .getByRole("region", { name: "Divergências por pedido", exact: true })
        .or(
          page.getByRole("heading", {
            name: "Nenhuma divergência neste recorte",
            exact: true,
          }),
        ),
    ).toBeVisible();
    const screenshots: string[] = [];
    const screenshot = async (name: string) => {
      const path = join(config.artifacts, "screenshots", name + ".png");
      await page.screenshot({ path, fullPage: true });
      screenshots.push(path);
    };
    await screenshot("restore-survivor-desktop");

    const snapshotQuery = new URLSearchParams({
      evidence_snapshot_id: restore.erased.snapshot,
    });
    const evidencePath =
      "/api/v1/evidence/" + encodeURIComponent(restore.erased.evidence);
    const dossierPath =
      "/api/v1/dossiers/" + encodeURIComponent(restore.erased.dossier);
    const erasedChecks = [];
    for (const [resource, path] of [
      ["evidence", evidencePath + "?" + snapshotQuery],
      ["original", evidencePath + "/content?" + snapshotQuery],
      ["dossier", dossierPath],
    ]) {
      const response = await page.request.get(path);
      expect(response.status(), resource + " must remain erased").toBe(404);
      const body = apiErrorSchema.parse(await response.json());
      // A missing original alone is insufficient: the source itself must be unauthorized.
      expect(body.error.code).toBe("resource_not_found");
      erasedChecks.push({
        resource,
        path,
        status: response.status(),
        ...body.error,
      });
    }

    const sourceDenied = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === evidencePath &&
        url.searchParams.get("evidence_snapshot_id") ===
          restore.erased.snapshot &&
        response.request().method() === "GET" &&
        response.status() === 404
      );
    });
    // These are existing IncidentWorkspace parameters, not injected application state.
    await page.goto(
      survivorPath +
        "?" +
        new URLSearchParams({
          tab: "sources",
          evidence: restore.erased.evidence,
          evidence_snapshot: restore.erased.snapshot,
        }),
    );
    const sourceProblem = apiErrorSchema.parse(
      await (await sourceDenied).json(),
    );
    const reader = page.getByRole("region", {
      name: "Leitor de evidência",
      exact: true,
    });
    await expect(reader.getByRole("alert")).toContainText(
      sourceProblem.error.message,
    );
    await expect(
      reader.getByRole("region", { name: "Texto canônico da fonte" }),
    ).toHaveCount(0);
    await screenshot("restore-erased-source-desktop");

    const dossierDenied = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === dossierPath &&
        response.request().method() === "GET" &&
        response.status() === 404,
    );
    await page.goto(
      survivorPath +
        "?" +
        new URLSearchParams({
          tab: "dossier",
          dossier: restore.erased.dossier,
        }),
    );
    const dossierProblem = apiErrorSchema.parse(
      await (await dossierDenied).json(),
    );
    await expect(
      page
        .getByRole("alert")
        .filter({ hasText: dossierProblem.error.message })
        .first(),
    ).toBeVisible();
    await screenshot("restore-erased-dossier-desktop");
    expect(session.generationPosts).toEqual([]);
    expect(session.blockedRequests).toEqual([]);
    expect(session.pageErrors).toEqual([]);
    // Deliberately exclude session cookies and CSRF tokens from the evidence record.
    await writeFile(
      join(config.artifacts, "restore-read-proof.json"),
      JSON.stringify(
        {
          status: "passed",
          recorded_at: new Date().toISOString(),
          run_id: restore.run_id,
          target_project: restore.target_project,
          ledger_sequence: restore.ledger_sequence,
          base_url: config.baseURL,
          survivor_incident: actual,
          erased_checks: erasedChecks,
          generation_post_attempts: session.generationPosts,
          blocked_requests: session.blockedRequests,
          screenshots,
        },
        null,
        2,
      ) + "\n",
      "utf8",
    );
  } finally {
    await context.close();
  }
});
