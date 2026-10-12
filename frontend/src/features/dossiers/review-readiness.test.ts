import { describe, expect, it } from "vitest";
import { reviewReadiness } from "./review-readiness";

describe("explicit dossier review", () => {
  const reason =
    "Conferi as fontes e o período; a causa permanece desconhecida.";
  it("does not turn a filled reason into a default approval", () => {
    expect(
      reviewReadiness("", reason, ["claim-a"], new Set(["claim-a"]), false)
        .canRecord,
    ).toBe(false);
  });
  it("requires the actual claim IDs, not a matching count of unrelated confirmations", () => {
    expect(
      reviewReadiness(
        "approved",
        reason,
        ["a", "b"],
        new Set(["a", "foreign"]),
        false,
      ),
    ).toMatchObject({ remaining: 1, canRecord: false });
    expect(
      reviewReadiness(
        "approved",
        reason,
        ["a", "b"],
        new Set(["a", "b"]),
        false,
      ).canRecord,
    ).toBe(true);
  });
  it("preserves honest abstention without invented claims or citations", () => {
    expect(
      reviewReadiness("approved", reason, [], new Set(), false).canRecord,
    ).toBe(false);
    expect(
      reviewReadiness("approved", reason, [], new Set(), true).canRecord,
    ).toBe(true);
  });
  it("allows explicit adjustment requests without pretending every claim was supported", () => {
    expect(
      reviewReadiness("changes_requested", reason, ["a", "b"], new Set(), false)
        .canRecord,
    ).toBe(true);
  });
  it("rejects blank, short and oversized reasons and counts Unicode code points", () => {
    for (const invalid of [" ", "abcd", "x".repeat(3001), "😀😀😀"]) {
      expect(
        reviewReadiness("approved", invalid, [], new Set(), true).canRecord,
      ).toBe(false);
    }
    expect(
      reviewReadiness("approved", "😀😀😀😀😀", [], new Set(), true).canRecord,
    ).toBe(true);
  });
});
