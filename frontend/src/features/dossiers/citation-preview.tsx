"use client";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { dossierSchema, revisionSchema, type Claim } from "@/lib/contracts";
import { request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { label } from "@/lib/format";
import { ErrorNotice, Loading } from "@/components/feedback";
import { resolveCitation, type CitationSelection } from "./citation-context";

export function CitationPreview({
  claim,
  claimNumber,
  revisionNumber,
  relation,
}: {
  claim: Claim;
  claimNumber: number;
  revisionNumber: number;
  relation: string;
}) {
  return (
    <section className="citation-context" aria-label="Alegação citada">
      <h3>
        Alegação {claimNumber} da revisão {revisionNumber}
      </h3>
      <p className="claim-text">{claim.text}</p>
      <p className="citation-relation">
        Vínculo registrado: {label(relation)}. Confira o trecho abaixo antes de
        concluir sobre o suporte.
      </p>
    </section>
  );
}

export function AuthoritativeCitation({
  selection,
  incidentId,
  snapshotId,
  evidenceId,
  children,
}: {
  selection: CitationSelection;
  incidentId: string;
  snapshotId: string;
  evidenceId: string;
  children: (access: {
    allowed: boolean;
    notice?: ReactNode;
    preview?: ReactNode;
  }) => ReactNode;
}) {
  const session = useSession();
  // These keys match the dossier reader: requests are deduplicated by the
  // session-scoped cache. Both independent authorizations start in parallel.
  const dossier = useQuery({
    queryKey: [...scopeKey(session), "dossier", selection.dossierId],
    gcTime: 0,
    staleTime: 0,
    queryFn: ({ signal }) =>
      request(
        "/api/v1/dossiers/" + encodeURIComponent(selection.dossierId),
        dossierSchema,
        { signal },
      ),
  });
  const revision = useQuery({
    queryKey: [
      ...scopeKey(session),
      "revision",
      selection.dossierId,
      selection.revisionId,
    ],
    gcTime: 0,
    staleTime: 0,
    queryFn: ({ signal }) =>
      request(
        "/api/v1/dossiers/" +
          encodeURIComponent(selection.dossierId) +
          "/revisions/" +
          encodeURIComponent(selection.revisionId),
        revisionSchema,
        { signal },
      ),
  });
  if (
    dossier.isPending ||
    dossier.isFetching ||
    revision.isPending ||
    revision.isFetching
  )
    return children({
      allowed: false,
      notice: <Loading>Conferindo a alegação desta citação…</Loading>,
    });
  if (dossier.isError || revision.isError)
    return children({
      allowed: false,
      notice: (
        <ErrorNotice
          error={dossier.error ?? revision.error}
          retry={() => {
            void Promise.all([dossier.refetch(), revision.refetch()]);
          }}
        />
      ),
    });
  const context = resolveCitation(
    dossier.data,
    revision.data,
    selection,
    incidentId,
    snapshotId,
    evidenceId,
  );
  if (!context)
    return children({
      allowed: false,
      notice: (
        <p className="notice notice-warning" role="alert">
          A citação não pertence à alegação e ao recorte selecionados. Volte ao
          dossiê e abra uma de suas fontes.
        </p>
      ),
    });
  return children({
    allowed: true,
    preview: (
      <CitationPreview {...context} revisionNumber={revision.data.number} />
    ),
  });
}
