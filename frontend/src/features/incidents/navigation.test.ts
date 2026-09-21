import { describe, expect, it } from "vitest";
import {
  queueDestination,
  incidentDestination,
  workspaceDestination,
} from "./navigation";
describe("investigation navigation", () => {
  it("preserves queue filters through an incident link", () => {
    const destination = incidentDestination(
      "case-1",
      new URLSearchParams({ q: "Pagamento confirmado", status: "open" }),
    );
    expect(
      queueDestination(
        new URL(destination, "https://test.invalid").searchParams,
      ),
    ).toBe("/?q=Pagamento+confirmado&status=open");
  });
  it("never interprets queue values as destinations", () => {
    const destination = queueDestination(
      new URLSearchParams({
        return_q: "https://evil.invalid",
        return_status: "//evil.invalid",
      }),
    );
    expect(destination).toBe("/?q=https%3A%2F%2Fevil.invalid");
  });
  it("composes rapid snapshot and tab changes without losing the snapshot", () => {
    const first = workspaceDestination(
      "/incidents/one",
      "?tab=divergences",
      "old",
      { snapshot: "active" },
    );
    const second = workspaceDestination(
      "/incidents/one",
      new URL(first, "https://test.invalid").search,
      "old",
      { tab: "sources" },
    );
    expect(second).toBe("/incidents/one?tab=sources&snapshot=active");
  });
  it("clears source selection without losing other filters", () => {
    expect(
      workspaceDestination(
        "/incidents/one",
        "?order=o1&evidence=e1&snapshot=s1&return_q=case",
        "s1",
        { evidence: null },
      ),
    ).toBe("/incidents/one?order=o1&snapshot=s1&return_q=case");
  });
});
