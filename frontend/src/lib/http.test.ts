import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { apiUrl, ApiError, queryString, request } from "./http";
afterEach(() => vi.unstubAllGlobals());
describe("API boundary", () => {
  it.each([
    "https://other.test/api/v1/x",
    "//other.test/api/v1/x",
    "/api/v1/../private",
    "/api/v1/%2e%2e/private",
    "/api/v1/a\\b",
    "/public",
  ])("rejects non-API and traversal URL %s", (path) =>
    expect(() => apiUrl(path)).toThrow(),
  );
  it("preserves an authorized API URL and encodes query values", () => {
    expect(
      apiUrl("/api/v1/evidence/a/content?evidence_snapshot_id=s1"),
    ).toContain("snapshot_id=s1");
    expect(queryString({ q: "x & y", cursor: null, limit: 0 })).toBe(
      "?q=x+%26+y&limit=0",
    );
  });
  it("sends CSRF with same-origin credentials and no-store", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ id: "r1" })));
    vi.stubGlobal("fetch", fetchMock);
    await request("/api/v1/incidents/x/runs", z.object({ id: z.string() }), {
      method: "POST",
      body: { evidence_snapshot_id: "s1" },
      csrf: "csrf-value",
      headers: { "Idempotency-Key": "intent-1" },
    });
    const options = fetchMock.mock.calls[0][1];
    expect(options.credentials).toBe("same-origin");
    expect(options.cache).toBe("no-store");
    expect(options.headers.get("X-CSRF-Token")).toBe("csrf-value");
    expect(options.headers.get("Idempotency-Key")).toBe("intent-1");
    expect(JSON.parse(options.body)).toEqual({ evidence_snapshot_id: "s1" });
  });
  it("rejects malformed successful data instead of displaying it", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(new Response(JSON.stringify({ state: "approved" }))),
    );
    await expect(
      request(
        "/api/v1/runs/x",
        z.object({ state: z.enum(["succeeded", "failed"]) }),
      ),
    ).rejects.toMatchObject({ code: "invalid_response", status: 502 });
  });
  it("preserves conflict status, request identity, and field errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "revision_conflict",
              message: "A base mudou.",
              request_id: "request-42",
              retryable: false,
              field_errors: { base_revision_id: ["Antiga"] },
            },
          }),
          { status: 409 },
        ),
      ),
    );
    const failure = await request(
      "/api/v1/dossiers/x/revisions",
      z.unknown(),
    ).catch((error: ApiError) => error);
    expect(failure).toMatchObject({
      status: 409,
      code: "revision_conflict",
      requestId: "request-42",
      fields: { base_revision_id: ["Antiga"] },
    });
  });
  it("accepts a true empty logout response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
    );
    await expect(request("/api/v1/auth/logout", z.null())).resolves.toBeNull();
  });
});
