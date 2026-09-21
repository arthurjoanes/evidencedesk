import { describe, expect, it } from "vitest";
import type { Claim } from "@/lib/contracts";
import { compareClaims } from "./revision-diff";
const first: Claim = {
  claim_id: "claim-1",
  kind: "observed_fact",
  text: "Pagamento confirmado.",
  order_references: ["ORDER-1"],
  evidence_links: [{ evidence_id: "ev-1", relation: "supports" }],
  support_status: "pending_review",
  missing_information: [],
  suggested_checks: [],
};
describe("claim comparison by stable identity", () => {
  it("does not confuse reordering with edit or replacement", () => {
    const second = { ...first, claim_id: "claim-2" };
    expect(
      compareClaims([first, second], [second, first]).map((item) => item.state),
    ).toEqual(["unchanged", "unchanged"]);
  });
  it("detects a changed evidence relationship despite identical text and link count", () => {
    expect(
      compareClaims(
        [first],
        [
          {
            ...first,
            evidence_links: [{ evidence_id: "ev-1", relation: "contradicts" }],
          },
        ],
      )[0].state,
    ).toBe("changed");
  });
  it("lists removed and newly added claims separately", () => {
    expect(
      compareClaims([first], [{ ...first, claim_id: "claim-2" }]).map(
        (item) => item.state,
      ),
    ).toEqual(["removed", "added"]);
  });
  it("does not present human review status as an authored content edit", () => {
    expect(
      compareClaims([first], [{ ...first, support_status: "reviewed" }])[0]
        .state,
    ).toBe("unchanged");
  });
});
