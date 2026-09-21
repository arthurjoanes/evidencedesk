import { expect, test } from "@playwright/test";
import { createHash } from "node:crypto";
import { syntheticPdf } from "./pdf-fixture";

test("isolated real PDF import, canonical text and original rendering", async ({
  page,
}) => {
  const pdf = syntheticPdf();
  const digest = createHash("sha256").update(pdf).digest("hex");
  const title = "QA PDF " + Date.now();
  const manifest = {
    schema_version: "1",
    title,
    source_tenant: "aurora",
    coverage: [],
    entries: [
      {
        entry_id: "pdf-1",
        filename: "qa-document.pdf",
        kind: "document",
        media_type: "application/pdf",
        byte_size: pdf.length,
        sha256: digest,
        metadata: {
          title: "Documento sintético de QA",
          version: "1",
          source_system: "qa",
          temporal_role: "historical_artifact",
        },
      },
    ],
  };
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
  await page.goto("/imports/new");
  await page
    .getByRole("combobox", { name: "Coleção de destino" })
    .selectOption("qa-imports");
  await page
    .locator('input[type="file"]')
    .nth(0)
    .setInputFiles({
      name: "manifest.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(manifest)),
    });
  await page.locator('input[type="file"]').nth(1).setInputFiles({
    name: "qa-document.pdf",
    mimeType: "application/pdf",
    buffer: pdf,
  });
  await page
    .getByRole("button", { name: "Conferir e enviar", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("Pacote publicado por inteiro")).toBeVisible({
    timeout: 30_000,
  });
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const created = await page.request.post("/api/v1/incidents", {
    headers: {
      "X-CSRF-Token": session.csrf_token,
      Origin: new URL(page.url()).origin,
    },
    data: {
      title,
      collection_id: "qa-imports",
      window: {
        from: "2026-07-01T12:00:00Z",
        to: "2026-07-01T12:30:00Z",
        time_zone: "UTC",
      },
    },
  });
  expect(created.status()).toBe(201);
  const incident = await created.json();
  await page.goto("/incidents/" + incident.id + "?tab=sources");
  await page
    .getByRole("button", { name: "Conferir fonte", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("region", { name: "Texto canônico da fonte" }),
  ).toContainText("Synthetic EvidenceDesk QA document");
  await page.getByRole("button", { name: "Página PDF", exact: true }).click();
  await expect(page.getByText("Página 1 de 1", { exact: true })).toBeVisible();
  await expect
    .poll(() =>
      page.locator("canvas").evaluate((canvas: HTMLCanvasElement) => {
        const pixels = canvas
          .getContext("2d")!
          .getImageData(0, 0, canvas.width, canvas.height).data;
        let dark = 0;
        for (let offset = 0; offset < pixels.length; offset += 4)
          if (pixels[offset + 3] && pixels[offset] < 150) dark++;
        return dark;
      }),
    )
    .toBeGreaterThan(100);
  await page.screenshot({
    path:
      (process.env.ED_E2E_ARTIFACT_DIR ?? "artifacts") +
      "/screenshots/pdf-desktop.png",
  });
  const params = new URL(page.url()).searchParams;
  const source = params.get("evidence");
  const snapshot = params.get("snapshot");
  const original = await page.request.get(
    "/api/v1/evidence/" + source + "/content?evidence_snapshot_id=" + snapshot,
  );
  expect(original.status()).toBe(200);
  expect(
    createHash("sha256")
      .update(await original.body())
      .digest("hex"),
  ).toBe(digest);
});
