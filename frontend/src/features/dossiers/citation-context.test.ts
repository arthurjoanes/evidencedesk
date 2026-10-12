import { describe, expect, it } from "vitest";
import { dossierSchema, revisionSchema } from "@/lib/contracts";
import { resolveCitation } from "./citation-context";

const dossier = dossierSchema.parse({
  id: "dossier-a",
  incident_id: "incident-a",
  evidence_snapshot_id: "snapshot-cited",
  origin: "manual",
  current_revision_id: "revision-new",
  approved_revision_id: null,
  permissions: [],
  revisions: [
    {
      id: "revision-cited",
      number: 1,
      author: "author-a",
      created_at: "2026-10-12T10:00:00Z",
      review_status: "submitted",
    },
  ],
});
const revision = revisionSchema.parse({
  id: "revision-cited",
  number: 1,
  base_revision_id: null,
  summary: "Há uma observação, sem causa comprovada.",
  outcome: "evidence_found",
  created_by: "author-a",
  created_at: "2026-10-12T10:00:00Z",
  review_status: "submitted",
  etag: '"revision-cited"',
  claims: [
    {
      claim_id: "claim-a",
      kind: "observed_fact",
      text: "Pagamento observado.",
      order_references: [],
      evidence_links: [{ evidence_id: "source-a", relation: "supports" }],
      support_status: "pending_review",
      missing_information: [],
      suggested_checks: [],
    },
  ],
});
const selection = {
  dossierId: "dossier-a",
  revisionId: "revision-cited",
  claimId: "claim-a",
};

describe("citation provenance joins", () => {
  it("uses the cited dossier snapshot and selected historical revision", () => {
    expect(
      resolveCitation(
        dossier,
        revision,
        selection,
        "incident-a",
        "snapshot-cited",
        "source-a",
      ),
    ).toMatchObject({
      claimNumber: 1,
      relation: "supports",
      claim: { text: "Pagamento observado." },
    });
  });
  it.each([
    ["foreign incident", "incident-foreign", "snapshot-cited", "source-a"],
    [
      "current snapshot replacing cited snapshot",
      "incident-a",
      "snapshot-new",
      "source-a",
    ],
    ["unlinked source", "incident-a", "snapshot-cited", "source-foreign"],
  ])("refuses %s", (_name, incident, snapshot, source) => {
    expect(
      resolveCitation(dossier, revision, selection, incident, snapshot, source),
    ).toBeNull();
  });
  it("does not interpret URL claim/revision/dossier IDs as trusted associations", () => {
    for (const changed of [
      { ...selection, claimId: "claim-foreign" },
      { ...selection, revisionId: "revision-foreign" },
      { ...selection, dossierId: "dossier-foreign" },
    ]) {
      expect(
        resolveCitation(
          dossier,
          revision,
          changed,
          "incident-a",
          "snapshot-cited",
          "source-a",
        ),
      ).toBeNull();
    }
  });
  it("rejects a revision absent from the authorized dossier history", () => {
    expect(
      resolveCitation(
        { ...dossier, revisions: [] },
        revision,
        selection,
        "incident-a",
        "snapshot-cited",
        "source-a",
      ),
    ).toBeNull();
  });
});
