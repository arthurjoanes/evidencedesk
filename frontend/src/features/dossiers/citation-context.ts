import type { Claim, Dossier, Revision } from "@/lib/contracts";

export type CitationSelection = {
  dossierId: string;
  revisionId: string;
  claimId: string;
};

export function resolveCitation(
  dossier: Dossier,
  revision: Revision,
  selection: CitationSelection,
  incidentId: string,
  snapshotId: string,
  evidenceId: string,
): { claim: Claim; claimNumber: number; relation: string } | null {
  if (
    dossier.id !== selection.dossierId ||
    dossier.incident_id !== incidentId ||
    dossier.evidence_snapshot_id !== snapshotId ||
    revision.id !== selection.revisionId ||
    !dossier.revisions.some((item) => item.id === revision.id)
  )
    return null;
  const index = revision.claims.findIndex(
    (claim) => claim.claim_id === selection.claimId,
  );
  const claim = revision.claims[index];
  const link = claim?.evidence_links.find(
    (item) => item.evidence_id === evidenceId,
  );
  return claim && link
    ? { claim, claimNumber: index + 1, relation: link.relation }
    : null;
}
