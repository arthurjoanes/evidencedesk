import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";

// Opt-in laboratory measurement. It reads the existing demo and never admits runs.
const baseUrl = process.env.ED_E2E_BASE_URL ?? "http://127.0.0.1:3106";
if (!new Set(["127.0.0.1", "localhost"]).has(new URL(baseUrl).hostname)) {
  throw new Error("This measurement is restricted to the local laboratory.");
}
const browser = await chromium.launch({ channel: "msedge", headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
});
const page = await context.newPage();
const session = await context.newCDPSession(page);
const generationRequests = [];
page.on("request", (request) => {
  if (
    request.method() === "POST" &&
    /\/incidents\/[^/]+\/runs$/.test(request.url())
  ) {
    generationRequests.push(new URL(request.url()).pathname);
  }
});
await session.send("Network.enable");
await session.send("Network.setCacheDisabled", { cacheDisabled: true });
await session.send("Performance.enable");
await page.addInitScript(() => {
  globalThis.edLab = { lcp: null, cls: 0, events: [] };
  new PerformanceObserver((list) => {
    for (const item of list.getEntries()) globalThis.edLab.lcp = item.startTime;
  }).observe({ type: "largest-contentful-paint", buffered: true });
  new PerformanceObserver((list) => {
    for (const item of list.getEntries()) {
      if (!item.hadRecentInput) globalThis.edLab.cls += item.value;
    }
  }).observe({ type: "layout-shift", buffered: true });
  new PerformanceObserver((list) => {
    for (const item of list.getEntries()) {
      if (item.interactionId) globalThis.edLab.events.push(item.duration);
    }
  }).observe({ type: "event", buffered: true, durationThreshold: 16 });
});

async function measureRoute(name, url, ready) {
  const started = performance.now();
  await page.goto(url);
  await ready();
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
  const usableMs = performance.now() - started;
  const measurements = await page.evaluate(() => {
    const scripts = performance
      .getEntriesByType("resource")
      .filter((item) => new URL(item.name).pathname.endsWith(".js"))
      .map((item) => ({
        path: new URL(item.name).pathname,
        encoded: item.encodedBodySize,
        decoded: item.decodedBodySize,
        transfer: item.transferSize,
      }));
    return {
      lcp_ms: globalThis.edLab.lcp,
      cls_observed_sum: globalThis.edLab.cls,
      scripts,
    };
  });
  return { name, usable_ms: usableMs, ...measurements };
}

try {
  await page.goto(baseUrl);
  await page.getByLabel("E-mail", { exact: true }).fill("carla@horizonte.demo");
  await page
    .getByLabel("Senha", { exact: true })
    .fill(process.env.ED_E2E_PASSWORD ?? "EvidenceDesk-demo-2026!");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page
    .getByRole("heading", { name: "Incidentes", exact: true })
    .waitFor();
  await page.locator("tbody .cell-title").first().waitFor();
  const queueUrl = page.url();
  await page.locator("tbody .cell-title").first().click();
  await page.getByRole("link", { name: "Fontes", exact: true }).waitFor();
  const incidentUrl = page.url();
  const routes = [];
  for (let sample = 1; sample <= 3; sample++) {
    routes.push({
      sample,
      ...(await measureRoute("queue", queueUrl, () =>
        page.locator("tbody .cell-title").first().waitFor(),
      )),
    });
    routes.push({
      sample,
      ...(await measureRoute("incident", incidentUrl, () =>
        page.getByRole("region", { name: "Divergências por pedido" }).waitFor(),
      )),
    });
  }
  await page.getByRole("link", { name: "Linha do tempo", exact: true }).click();
  await page
    .getByText("A sequência não comprova causalidade.", { exact: false })
    .waitFor();
  const timelineRows = await page.locator("tbody tr").count();
  await page.getByRole("link", { name: "Fontes", exact: true }).click();
  const open = page
    .getByRole("button", { name: "Conferir fonte", exact: true })
    .first();
  await open.waitFor();
  const reader = [];
  for (let cycle = 1; cycle <= 8; cycle++) {
    const started = performance.now();
    await open.click();
    const text = page.getByRole("region", { name: "Texto canônico da fonte" });
    await text.waitFor();
    const characters = (await text.textContent()).length;
    const openMs = performance.now() - started;
    const metrics = await session.send("Performance.getMetrics");
    reader.push({
      cycle,
      open_ms: openMs,
      characters,
      heap_used_bytes: metrics.metrics.find(
        (item) => item.name === "JSHeapUsedSize",
      )?.value,
    });
    await page
      .getByRole("button", { name: "Voltar à seleção", exact: true })
      .click();
  }
  if (generationRequests.length)
    throw new Error("Unexpected generation request");
  const events = await page.evaluate(() => globalThis.edLab.events);
  const report = {
    recorded_at: new Date().toISOString(),
    browser: browser.version(),
    base_url: baseUrl,
    conditions:
      "Next production Docker; 1440x1000; browser HTTP cache disabled; no CPU/network throttle; shared Windows host with other workloads; one synthetic user session",
    limitations:
      "Three navigations per route, not field percentiles. LCP sampled after content becomes usable; CLS is observed sum, not full session-window metric. Event timing is not INP. Heap samples do not prove absence of leaks. Timeline is bounded/paginated, not a huge-table stress test.",
    routes,
    timeline_rendered_rows: timelineRows,
    reader,
    event_duration_ms: events,
    new_generation_requests: generationRequests.length,
  };
  await mkdir("artifacts", { recursive: true });
  await writeFile(
    "artifacts/performance-lab.json",
    JSON.stringify(report, null, 2) + "\n",
  );
  console.log(
    JSON.stringify({
      routes: routes.map(
        ({ name, sample, usable_ms, lcp_ms, cls_observed_sum, scripts }) => ({
          name,
          sample,
          usable_ms,
          lcp_ms,
          cls_observed_sum,
          javascript_encoded_bytes: scripts.reduce(
            (sum, item) => sum + item.encoded,
            0,
          ),
        }),
      ),
      timelineRows,
      reader,
      new_generation_requests: 0,
    }),
  );
} finally {
  await browser.close();
}
