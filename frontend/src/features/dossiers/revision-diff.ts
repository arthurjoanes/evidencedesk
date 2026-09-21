import type { Claim } from "@/lib/contracts";
export type ClaimChange = {
  id: string;
  state: "added" | "removed" | "changed" | "unchanged";
  before?: Claim;
  after?: Claim;
};
function content(claim: Claim) {
  return JSON.stringify({
    kind: claim.kind,
    text: claim.text,
    order_references: [...claim.order_references].sort(),
    evidence_links: claim.evidence_links
      .map((link) => link.evidence_id + ":" + link.relation)
      .sort(),
    missing_information: claim.missing_information,
    suggested_checks: claim.suggested_checks,
  });
}
export function compareClaims(before: Claim[], after: Claim[]): ClaimChange[] {
  const previous = new Map(before.map((claim) => [claim.claim_id, claim]));
  const current = new Map(after.map((claim) => [claim.claim_id, claim]));
  return [...new Set([...previous.keys(), ...current.keys()])].map((id) => {
    const left = previous.get(id);
    const right = current.get(id);
    return {
      id,
      before: left,
      after: right,
      state: !left
        ? "added"
        : !right
          ? "removed"
          : content(left) === content(right)
            ? "unchanged"
            : "changed",
    };
  });
}
