// Synthetic UI judgments only. This runner never imports its files into a real round.
// Usage: node evals/workbench.browser.mjs (uses the locked frontend dev dependencies).
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, writeFile, mkdir } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const evalDir = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(evalDir, "../frontend/package.json"));
const { chromium, expect } = require("@playwright/test");
const { default: AxeBuilder } = await import(
  pathToFileURL(require.resolve("@axe-core/playwright")).href
);
const artifactDir = process.env.ED_WORKBENCH_ARTIFACT_DIR
  ? path.resolve(process.env.ED_WORKBENCH_ARTIFACT_DIR)
  : await mkdtemp(path.join(os.tmpdir(), "ed-workbench-synthetic-"));
await mkdir(artifactDir, { recursive: true });
const htmlPath = path.join(evalDir, "workbench.html");
const repoDir = path.resolve(evalDir, "..");
const python =
  process.env.ED_WORKBENCH_PYTHON ??
  (existsSync(path.join(repoDir, ".venv/Scripts/python.exe"))
    ? path.join(repoDir, ".venv/Scripts/python.exe")
    : existsSync(path.join(repoDir, ".venv/bin/python"))
      ? path.join(repoDir, ".venv/bin/python")
      : "python3");
const sha = (value) => createHash("sha256").update(value, "utf8").digest("hex");
const canonical = (value) => {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object")
    return (
      "{" +
      Object.keys(value)
        .sort()
        .map((key) => JSON.stringify(key) + ":" + canonical(value[key]))
        .join(",") +
      "}"
    );
  return JSON.stringify(value);
};
const hostile =
  '</script><script>globalThis.__hostile=true</script><img src="https://invalid.example/canary" onerror="globalThis.__hostile=true">';
const source = {
  source_id: "source-synthetic",
  sha256: sha("Fonte sintética. Pagamento observado: R$ 20. " + hostile),
  text: "Fonte sintética. Pagamento observado: R$ 20. " + hostile,
  title: "Documento sintético " + hostile,
  kind: "document",
  metadata: { temporal_role: "historical_artifact", synthetic_test: true },
  locators: ["/corpus/0", "/corpus/1"],
};
const release = {
  id: "synthetic-ui-test-only",
  commit: null,
  image_id: "synthetic-fixture-only",
  corpus_sha256: sha("synthetic-ui-corpus"),
  chunk_policy: "synthetic-test-v1",
  parser_rules_version: "synthetic-test-v1",
  retrieval_profile: "lexical",
  encoder_revision: null,
  reranker_revision: null,
  generation_deployment_revision: null,
};
const makeResponse = (index, state = "answered") => {
  const answer = state === "not_run" ? null : "Resposta sintética " + hostile;
  const sources = [source];
  const source_file_sha256 = sha("synthetic-original-" + index);
  return {
    response_id: "synthetic-response-" + index,
    case_id: "synthetic-case-" + index,
    scenario_instance: "synthetic-incident-" + index,
    category: "synthetic-ui-test",
    system_code: "S" + index,
    question: "Pergunta sintética " + index,
    state,
    answer,
    answer_sha256: answer === null ? null : sha(answer),
    source_file_sha256,
    source_manifest_sha256: sha(
      canonical({
        source_file_sha256,
        sources: sources.map(({ text, ...item }) => item),
      }),
    ),
    claims:
      state === "not_run"
        ? []
        : [
            {
              claim_id: "claim-" + index + "-1",
              exact_claim: "Pagamento observado de R$ 20. " + hostile,
              references: [
                { source_id: source.source_id, locator: "/corpus/0" },
              ],
            },
            {
              claim_id: "claim-" + index + "-2",
              exact_claim: "A evidência comprova entrega.",
              references: [],
            },
          ],
    sources,
    context: { coverage: [], mappings: [], window: {}, focus_order: "test" },
    annotation_revision: 0,
    annotation_sha256: null,
    annotation: null,
  };
};
const bundle = {
  schema_version: 1,
  kind: "evidencedesk-review-bundle",
  round_id: "synthetic-browser-only",
  split: "dev",
  reviewer_id: "simulated-browser-test",
  release,
  release_sha256: sha(canonical(release)),
  rubric_version: "semantic-review-v1",
  presentation_order: [1, 2, 3].map((i) => "synthetic-response-" + i),
  responses: [makeResponse(1), makeResponse(2), makeResponse(3, "not_run")],
};
const seal = (value) => {
  const clone = structuredClone(value);
  delete clone.bundle_sha256;
  return { ...clone, bundle_sha256: sha(canonical(clone)) };
};
const bundlePath = path.join(artifactDir, "synthetic-bundle.json");
await writeFile(bundlePath, JSON.stringify(seal(bundle)));
const browser = await chromium.launch({
  ...(process.env.ED_E2E_BROWSER_CHANNEL
    ? { channel: process.env.ED_E2E_BROWSER_CHANNEL }
    : {}),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  acceptDownloads: true,
});
const page = await context.newPage();
const checks = [];
const pageErrors = [];
const networkRequests = [];
page.on("pageerror", (error) => pageErrors.push(error.message));
page.on("request", (request) => {
  if (!request.url().startsWith("file:")) networkRequests.push(request.url());
});
const check = async (name, action) => {
  await action();
  checks.push({ name, status: "passed" });
  process.stdout.write("PASS " + name + "\n");
};
const importBundle = async (file = bundlePath) => {
  await page.locator("#bundle-file").setInputFiles(file);
  await page.getByText("Bundle verificado.", { exact: false }).waitFor();
};
const exportFile = async (button, name) => {
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: button, exact: true }).click();
  const download = await downloadPromise;
  const output = path.join(artifactDir, name);
  await download.saveAs(output);
  return JSON.parse(await readFile(output, "utf8"));
};
let failure = null;
try {
  await page.goto(pathToFileURL(htmlPath).href);
  await check("empty state and disabled exports", async () => {
    assert.equal(await page.locator("#empty").isVisible(), true);
    assert.equal(await page.locator("#export-draft").isDisabled(), true);
    assert.equal(await page.locator("#export-submitted").isDisabled(), true);
  });
  await importBundle();
  let untouched;
  await check("blinded import and untouched values remain null", async () => {
    assert.equal(await page.locator("#claim-label").inputValue(), "");
    assert.equal(await page.locator("#source-select").inputValue(), "");
    assert.equal(await page.locator("#locator-select").inputValue(), "");
    untouched = await exportFile(
      "Exportar rascunho",
      "synthetic-untouched.json",
    );
    assert.equal(untouched.annotations.length, 2);
    for (const annotation of untouched.annotations) {
      assert.equal(annotation.status, "draft");
      for (const claim of annotation.claims)
        for (const key of [
          "label",
          "rationale",
          "source_id",
          "source_sha256",
          "span_or_locator",
        ])
          assert.equal(claim[key], null);
      for (const key of [
        "required_facts",
        "omitted_facts",
        "counterevidence_notes",
        "temporal_notes",
        "abstention_judgment",
        "numbers_checked",
        "numbers_matching",
        "assistance_received",
        "elapsed_seconds",
        "reviewed_at",
      ])
        assert.equal(annotation[key], null);
    }
  });
  await check(
    "hostile source/answer text is inert, no network or storage",
    async () => {
      await page.locator("#source-select").selectOption(source.source_id);
      assert.equal(
        await page.locator("#source-text").textContent(),
        source.text,
      );
      assert.equal(
        await page.locator("#source-title").textContent(),
        source.title,
      );
      assert.equal(await page.locator("script").count(), 1);
      assert.equal(await page.locator("img").count(), 0);
      assert.equal(await page.evaluate(() => globalThis.__hostile), undefined);
      assert.equal(await page.evaluate(() => localStorage.length), 0);
      assert.equal(await page.evaluate(() => sessionStorage.length), 0);
      assert.deepEqual(networkRequests, []);
    },
  );
  await check("supported cannot submit without locator/rationale", async () => {
    await page.locator("#claim-label").selectOption("supported");
    await page
      .getByRole("button", { name: "Exportar resposta submetida" })
      .click();
    assert.match(await page.locator("#notice").textContent(), /incompleta/);
    await page.locator("#locator-select").selectOption("/corpus/0");
    await page
      .locator("#rationale")
      .fill("Julgamento sintético: o valor consta na fonte.");
    assert.equal(await page.locator("#unsaved").isVisible(), true);
  });
  await check(
    "draft survives filtering, case/claim navigation and keyboard",
    async () => {
      await page.locator("#filter").fill("does-not-exist");
      assert.match(
        await page.locator("#case-list").textContent(),
        /rascunho foi preservado/,
      );
      await page.locator("#filter").fill("");
      await page
        .getByRole("button", { name: "synthetic-case-2", exact: false })
        .click();
      await page
        .getByRole("button", { name: "synthetic-case-1", exact: false })
        .click();
      assert.equal(
        await page.locator("#claim-label").inputValue(),
        "supported",
      );
      assert.equal(
        await page.locator("#rationale").inputValue(),
        "Julgamento sintético: o valor consta na fonte.",
      );
      assert.equal(
        await page.locator("#locator-select").inputValue(),
        "/corpus/0",
      );
      await page
        .getByRole("button", { name: "Alegação 2:", exact: false })
        .focus();
      await page.keyboard.press("Enter");
      assert.equal(await page.locator("#claim-label").inputValue(), "");
      assert.equal(
        await page
          .locator("#claim-label")
          .evaluate((el) => el === document.activeElement),
        true,
      );
      await page.locator("#claim-label").selectOption("insufficient");
      await page
        .locator("#rationale")
        .fill("Julgamento sintético: não há evidência de entrega.");
      assert.equal(await page.locator("#source-select").inputValue(), "");
      await page
        .locator("#assistance")
        .fill("Nenhuma. Teste automatizado sintético.");
    },
  );
  let submitted;
  await check(
    "submitted JSON preserves provenance and absence without fake source",
    async () => {
      submitted = await exportFile(
        "Exportar resposta submetida",
        "synthetic-submitted.json",
      );
      assert.equal(submitted.annotations.length, 1);
      const annotation = submitted.annotations[0];
      assert.equal(annotation.status, "submitted");
      assert.equal(annotation.reviewer_id, "simulated-browser-test");
      assert.equal(annotation.answer_sha256, bundle.responses[0].answer_sha256);
      assert.equal(annotation.release_sha256, bundle.release_sha256);
      assert.equal(annotation.claims[0].source_sha256, source.sha256);
      assert.equal(annotation.claims[1].source_id, null);
      assert.equal(annotation.claims[1].span_or_locator, null);
      assert.equal(annotation.numbers_checked, null);
      assert.equal(annotation.required_facts, null);
      assert.equal(Number.isInteger(annotation.elapsed_seconds), true);
      assert.equal(typeof annotation.reviewed_at, "string");
      assert.match(
        await page.locator("#notice").textContent(),
        /gate humano inconclusivo/,
      );
      assert.equal(await page.locator("#unsaved").isVisible(), false);
    },
  );
  await check("reload and resume own annotation", async () => {
    await page.reload();
    await importBundle();
    await page
      .locator("#annotation-file")
      .setInputFiles(path.join(artifactDir, "synthetic-submitted.json"));
    await page
      .getByText("Sua anotação foi retomada.", { exact: false })
      .waitFor();
    assert.equal(await page.locator("#claim-label").inputValue(), "supported");
    assert.equal(
      await page.locator("#locator-select").inputValue(),
      "/corpus/0",
    );
  });
  await check(
    "local draft conflict and cancel discard preserve current work",
    async () => {
      await page
        .locator("#rationale")
        .fill("Alteração sintética ainda não exportada.");
      await page
        .locator("#annotation-file")
        .setInputFiles(path.join(artifactDir, "synthetic-submitted.json"));
      await expect(page.locator("#notice")).toContainText("Conflito:");
      assert.equal(
        await page.locator("#rationale").inputValue(),
        "Alteração sintética ainda não exportada.",
      );
      page.once("dialog", (dialog) => dialog.dismiss());
      await page
        .getByRole("button", { name: "Descartar rascunho", exact: true })
        .click();
      assert.equal(
        await page.locator("#rationale").inputValue(),
        "Alteração sintética ainda não exportada.",
      );
      const replacementDialog = page.waitForEvent("dialog");
      await page.locator("#bundle-file").setInputFiles(bundlePath);
      const dialog = await replacementDialog;
      assert.match(dialog.message(), /rascunho não exportado/);
      await dialog.dismiss();
      assert.equal(
        await page.locator("#rationale").inputValue(),
        "Alteração sintética ainda não exportada.",
      );
    },
  );
  await check(
    "incompatible version, invalid JSON, hash error do not replace draft",
    async () => {
      const tampered = seal(bundle);
      tampered.responses[0].answer = "Resposta modificada sem atualizar hash";
      const tamperedPath = path.join(artifactDir, "synthetic-tampered.json");
      await writeFile(tamperedPath, JSON.stringify(tampered));
      await page.locator("#bundle-file").setInputFiles(tamperedPath);
      await expect(page.locator("#notice")).toContainText("Erro de hash");
      const incompatiblePath = path.join(
        artifactDir,
        "synthetic-incompatible.json",
      );
      await writeFile(
        incompatiblePath,
        JSON.stringify({ schema_version: 999 }),
      );
      await page.locator("#bundle-file").setInputFiles(incompatiblePath);
      await expect(page.locator("#notice")).toContainText(
        "Arquivo incompatível",
      );
      const invalidPath = path.join(artifactDir, "synthetic-invalid.json");
      await writeFile(invalidPath, "{ invalid json");
      await page.locator("#bundle-file").setInputFiles(invalidPath);
      await expect(page.locator("#notice")).toContainText("JSON inválido");
      assert.equal(
        await page.locator("#rationale").inputValue(),
        "Alteração sintética ainda não exportada.",
      );
      const conflict = structuredClone(submitted);
      conflict.annotations[0].revision = 9;
      const conflictPath = path.join(artifactDir, "synthetic-conflict.json");
      await writeFile(conflictPath, JSON.stringify(conflict));
      await page.locator("#annotation-file").setInputFiles(conflictPath);
      await expect(page.locator("#notice")).toContainText("Conflito de versão");
      for (const [name, alter, expected] of [
        [
          "source-hash",
          (value) => {
            value.responses[0].sources[0].text = "Fonte modificada";
          },
          "Erro de hash",
        ],
        [
          "answer-hash",
          (value) => {
            value.responses[0].answer = "Resposta modificada";
          },
          "Erro de hash",
        ],
        [
          "missing-source",
          (value) => {
            value.responses[0].sources[0].text = null;
          },
          "Arquivo incompatível",
        ],
        [
          "missing-release",
          (value) => {
            value.release.image_id = null;
          },
          "Arquivo incompatível",
        ],
        [
          "duplicate-id",
          (value) => {
            value.responses.push(value.responses[0]);
          },
          "IDs duplicados",
        ],
        [
          "reserved-split",
          (value) => {
            value.split = "reserved";
          },
          "Arquivo incompatível",
        ],
        [
          "prototype-state-toString",
          (value) => {
            value.responses[0].state = "toString";
          },
          "Arquivo incompatível",
        ],
        [
          "prototype-state-proto",
          (value) => {
            value.responses[0].state = "__proto__";
          },
          "Arquivo incompatível",
        ],
      ]) {
        const altered = structuredClone(bundle);
        alter(altered);
        const alteredPath = path.join(
          artifactDir,
          "synthetic-" + name + ".json",
        );
        await writeFile(alteredPath, JSON.stringify(seal(altered)));
        await page.locator("#bundle-file").setInputFiles(alteredPath);
        await expect(page.locator("#notice")).toContainText(expected);
        assert.equal(
          await page.locator("#review-heading").textContent(),
          "synthetic-case-1",
        );
        assert.equal(
          await page.locator("#rationale").inputValue(),
          "Alteração sintética ainda não exportada.",
        );
      }
      const duplicateKeyPath = path.join(
        artifactDir,
        "synthetic-duplicate-key.json",
      );
      await writeFile(
        duplicateKeyPath,
        '{"schema_version":1,"schema_version":1}',
      );
      await page.locator("#bundle-file").setInputFiles(duplicateKeyPath);
      await expect(page.locator("#notice")).toContainText("JSON inválido");
      const largePath = path.join(artifactDir, "synthetic-too-large.json");
      await writeFile(largePath, Buffer.alloc(16 * 1024 * 1024 + 1, 32));
      await page.locator("#bundle-file").setInputFiles(largePath);
      await expect(page.locator("#notice")).toContainText(
        "Arquivo grande demais",
      );
    },
  );
  await check(
    "unexecuted response is visible but cannot receive judgment",
    async () => {
      await page
        .getByRole("button", { name: "synthetic-case-3", exact: false })
        .click();
      assert.equal(await page.locator("#claim-form").isVisible(), false);
      assert.equal(await page.locator("#response-form").isVisible(), false);
      assert.equal(await page.locator("#export-submitted").isDisabled(), true);
      assert.match(
        await page.locator("#unavailable").textContent(),
        /Não há julgamento/,
      );
      await page
        .getByRole("button", { name: "synthetic-case-1", exact: false })
        .click();
    },
  );
  await check(
    "desktop, 360px, 200% reflow, focus and automated WCAG checks",
    async () => {
      await exportFile("Exportar rascunho", "synthetic-before-layout.json");
      const violations = async () =>
        (
          await new AxeBuilder({ page })
            .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
            .analyze()
        ).violations;
      assert.deepEqual(await violations(), []);
      await page.locator("#source-select").focus();
      assert.equal(
        await page
          .locator("#source-select")
          .evaluate((el) => getComputedStyle(el).outlineStyle),
        "solid",
      );
      if (process.env.ED_WORKBENCH_CAPTURE === "1")
        await page.screenshot({
          path: path.join(artifactDir, "workbench-desktop.png"),
          fullPage: true,
        });
      await page.setViewportSize({ width: 360, height: 800 });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        true,
      );
      assert.deepEqual(await violations(), []);
      if (process.env.ED_WORKBENCH_CAPTURE === "1")
        await page.screenshot({
          path: path.join(artifactDir, "workbench-mobile.png"),
          fullPage: true,
        });
      // 720px physical viewport at 200% browser scale has 360 CSS pixels.
      // Also exercise CSS zoom to check controls and wrapping under magnification.
      await page.setViewportSize({ width: 720, height: 1000 });
      await page.evaluate(() => {
        document.documentElement.style.zoom = "2";
      });
      assert.equal(
        await page.evaluate(
          () =>
            document.documentElement.getBoundingClientRect().width <=
            innerWidth,
        ),
        true,
      );
      assert.deepEqual(await violations(), []);
      if (process.env.ED_WORKBENCH_CAPTURE === "1")
        await page.screenshot({
          path: path.join(artifactDir, "workbench-zoom-200.png"),
          fullPage: true,
        });
      await page.evaluate(() => {
        document.documentElement.style.zoom = "";
      });
    },
  );
  await check("empty bundle keeps human gate inconclusive", async () => {
    await exportFile("Exportar rascunho", "synthetic-final-draft.json");
    const empty = seal({ ...bundle, responses: [], presentation_order: [] });
    const emptyPath = path.join(artifactDir, "synthetic-empty.json");
    await writeFile(emptyPath, JSON.stringify(empty));
    await page.locator("#bundle-file").setInputFiles(emptyPath);
    await expect(page.locator("#notice")).toContainText("Rodada vazia");
    assert.equal(await page.locator("#export-draft").isDisabled(), true);
    assert.equal(await page.locator("#export-submitted").isDisabled(), true);
  });
  await check(
    "unavailable parser, chunks and retrieval versions remain null",
    async () => {
      const nullable = structuredClone(bundle);
      for (const key of [
        "chunk_policy",
        "parser_rules_version",
        "retrieval_profile",
      ])
        nullable.release[key] = null;
      nullable.release_sha256 = sha(canonical(nullable.release));
      const nullablePath = path.join(
        artifactDir,
        "synthetic-null-versions.json",
      );
      await writeFile(nullablePath, JSON.stringify(seal(nullable)));
      await importBundle(nullablePath);
      const context = JSON.parse(
        await page.locator("#response-context").textContent(),
      );
      for (const key of [
        "chunk_policy",
        "parser_rules_version",
        "retrieval_profile",
      ])
        assert.equal(context.release[key], null);
      assert.equal(await page.locator("#claim-label").inputValue(), "");
    },
  );
  await check(
    "actual prepare/bundle -> browser exports -> authoritative CLI validation",
    async () => {
      const integrationDir = await mkdtemp(
        path.join(artifactDir, "cli-synthetic-"),
      );
      const integrationScript = path.join(
        integrationDir,
        "prepare-synthetic-round.py",
      );
      await writeFile(
        integrationScript,
        [
          "import sys, subprocess",
          "from pathlib import Path",
          "sys.path.insert(0, sys.argv[1])",
          "from evals.workbench import RoundSpec, Release, ResponsesInput, ResponseInput, Claim, Reference, prepare, bundle_for, write_json",
          "root, out = Path(sys.argv[1]), Path(sys.argv[2])",
          "head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()",
          "release = Release(id='synthetic-browser-cli-test', commit=head, chunk_policy='utf8-bytes-352-v2', parser_rules_version='text-pdf-v2', retrieval_profile='lexical')",
          "spec = RoundSpec(round_id='synthetic-browser-cli-test', release=release, planned_case_ids=['evaluation-dev-000'], system_codes=['S1'])",
          "claim = Claim(claim_id='synthetic-test-claim', exact_claim='Há um evento de confirmação de pagamento.', references=[Reference(source_id='evaluation-dev-000-event-0', locator='/corpus/0')])",
          "inputs = ResponsesInput(responses=[ResponseInput(case_id='evaluation-dev-000',system_code='S1',state='answered',answer=claim.exact_claim,claims=[claim])])",
          "prepare(spec, inputs, out/'round')",
          "bundle = bundle_for(out/'round', 'simulated-cli-browser-test')",
          "write_json(out/'bundle.json', bundle.model_dump())",
          "print('Synthetic CLI round prepared; no human reviews or model calls.')",
          "",
        ].join("\n"),
      );
      execFileSync(python, [integrationScript, repoDir, integrationDir], {
        cwd: repoDir,
        encoding: "utf8",
      });
      const actualBundlePath = path.join(integrationDir, "bundle.json");
      await importBundle(actualBundlePath);
      const draftPath = "synthetic-cli-draft.json";
      await exportFile("Exportar rascunho", draftPath);
      const validate = (name) =>
        JSON.parse(
          execFileSync(
            python,
            [
              path.join(evalDir, "workbench.py"),
              "validate",
              "--round",
              path.join(integrationDir, "round"),
              "--annotations",
              path.join(artifactDir, name),
            ],
            { cwd: repoDir, encoding: "utf8" },
          ),
        );
      assert.equal(validate(draftPath).valid, true);
      await page.locator("#claim-label").selectOption("supported");
      await page
        .locator("#source-select")
        .selectOption("evaluation-dev-000-event-0");
      await page.locator("#locator-select").selectOption("/corpus/0");
      await page
        .locator("#rationale")
        .fill(
          "Julgamento de teste automatizado sintético; não é revisão humana.",
        );
      await page
        .locator("#assistance")
        .fill(
          "Automação Playwright em fixture sintética, sem chamada de modelo.",
        );
      const submitted = await exportFile(
        "Exportar resposta submetida",
        "synthetic-cli-submitted.json",
      );
      assert.equal(validate("synthetic-cli-submitted.json").valid, true);
      const repeated = await exportFile(
        "Exportar resposta submetida",
        "synthetic-cli-submitted-repeat.json",
      );
      assert.deepEqual(repeated, submitted);
      // No UI export is imported as human evidence. Only a copied fixture explicitly
      // marked simulated_test enters this disposable test round to exercise a base revision.
      const simulation = structuredClone(submitted);
      simulation.annotations[0].evidence_origin = "simulated_test";
      const simulationPath = path.join(integrationDir, "simulated-import.json");
      await writeFile(simulationPath, JSON.stringify(simulation));
      execFileSync(
        python,
        [
          path.join(evalDir, "workbench.py"),
          "import",
          "--round",
          path.join(integrationDir, "round"),
          "--annotations",
          simulationPath,
        ],
        { cwd: repoDir, encoding: "utf8" },
      );
      const report = JSON.parse(
        execFileSync(
          python,
          [
            path.join(evalDir, "workbench.py"),
            "report",
            "--round",
            path.join(integrationDir, "round"),
          ],
          { cwd: repoDir, encoding: "utf8" },
        ),
      );
      assert.equal(report.human_gate, "inconclusive");
      const importedBundlePath = path.join(
        integrationDir,
        "imported-submission-bundle.json",
      );
      execFileSync(
        python,
        [
          path.join(evalDir, "workbench.py"),
          "bundle",
          "--round",
          path.join(integrationDir, "round"),
          "--reviewer",
          "simulated-cli-browser-test",
          "--output",
          importedBundlePath,
        ],
        { cwd: repoDir, encoding: "utf8" },
      );
      await importBundle(importedBundlePath);
      const importedBundle = JSON.parse(
        await readFile(importedBundlePath, "utf8"),
      );
      await expect(page.locator("#imported-submission")).toContainText(
        "registro é imutável",
      );
      await expect(page.locator("#imported-submission")).toContainText(
        "não conta como revisão humana",
      );
      for (const id of [
        "claim-label",
        "rationale",
        "required-facts",
        "omitted-facts",
        "counterevidence",
        "temporal",
        "abstention",
        "numbers-checked",
        "numbers-matching",
        "critical-flags",
        "assistance",
      ])
        assert.equal(await page.locator("#" + id).isDisabled(), true);
      assert.equal(await page.locator("#source-select").isDisabled(), false);
      await page
        .locator("#source-select")
        .selectOption("evaluation-dev-000-event-1");
      await page.locator("#locator-select").selectOption("/corpus/1");
      assert.equal(await page.locator("#unsaved").isVisible(), false);
      const immutableExport = await exportFile(
        "Exportar resposta submetida",
        "synthetic-cli-immutable.json",
      );
      assert.deepEqual(
        immutableExport.annotations[0],
        simulation.annotations[0],
      );
      assert.equal(validate("synthetic-cli-immutable.json").valid, true);
      const editAttempt = structuredClone(immutableExport);
      editAttempt.annotations[0].evidence_origin = "human_declared";
      editAttempt.annotations[0].revision += 1;
      editAttempt.annotations[0].base_annotation_sha256 =
        importedBundle.responses[0].annotation_sha256;
      editAttempt.annotations[0].claims[0].rationale =
        "Tentativa sintética de alterar submissão importada.";
      const editAttemptPath = path.join(
        integrationDir,
        "immutable-edit-attempt.json",
      );
      await writeFile(editAttemptPath, JSON.stringify(editAttempt));
      await page.locator("#annotation-file").setInputFiles(editAttemptPath);
      await expect(page.locator("#notice")).toContainText(
        "Submissão já importada é imutável",
      );
      assert.equal(
        await page.locator("#rationale").inputValue(),
        simulation.annotations[0].claims[0].rationale,
      );
      assert.equal(await page.locator("#claim-label").isDisabled(), true);
    },
  );
  assert.deepEqual(pageErrors, []);
  assert.deepEqual(networkRequests, []);
} catch (error) {
  failure = error;
  process.stderr.write(String(error.stack || error) + "\n");
} finally {
  await writeFile(
    path.join(artifactDir, "workbench-browser-receipt.json"),
    JSON.stringify(
      {
        kind: "synthetic_browser_automation",
        executed_at: new Date().toISOString(),
        workbench_sha256: sha(await readFile(htmlPath, "utf8")),
        browser_version: browser.version(),
        human_reviews_executed: 0,
        human_gate: "inconclusive",
        model_behavior: "not_run",
        screenshot_capture_enabled: process.env.ED_WORKBENCH_CAPTURE === "1",
        checks,
        page_errors: pageErrors,
        network_requests: networkRequests,
        status: failure ? "failed" : "passed",
        failure: failure ? String(failure.message) : null,
      },
      null,
      2,
    ) + "\n",
  );
  await browser.close();
  process.stdout.write("Artifacts: " + artifactDir + "\n");
}
if (failure) process.exitCode = 1;
