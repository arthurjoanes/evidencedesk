"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { revisionSchema, type Revision, type Claim } from "@/lib/contracts";
import { request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { ErrorNotice, Loading } from "@/components/feedback";
import { label } from "@/lib/format";
import { compareClaims } from "./revision-diff";
export function RevisionComparison({
  dossierId,
  revision,
  onEvidence,
}: {
  onEvidence: (id: string) => void;
  dossierId: string;
  revision: Revision;
}) {
  const [open, setOpen] = useState(false);
  const session = useSession();
  const previous = useQuery({
    gcTime: 0,
    staleTime: 0,
    queryKey: [
      ...scopeKey(session),
      "revision",
      dossierId,
      revision.base_revision_id,
    ],
    queryFn: ({ signal }) =>
      request(
        "/api/v1/dossiers/" +
          dossierId +
          "/revisions/" +
          revision.base_revision_id,
        revisionSchema,
        { signal },
      ),
    enabled: open && !!revision.base_revision_id,
  });
  if (!revision.base_revision_id)
    return (
      <p className="revision-provenance">Primeira revisão deste dossiê.</p>
    );
  return (
    <details
      className="revision-comparison"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Comparar com a revisão-base</summary>
      {open && (previous.isPending || previous.isFetching) && (
        <Loading>Carregando revisão-base…</Loading>
      )}
      {open && previous.isError && <ErrorNotice error={previous.error} />}
      {open && !previous.isFetching && !previous.isError && previous.data && (
        <>
          <div className="review-diff">
            <section>
              <h4>Resumo anterior · revisão {previous.data.number}</h4>
              <p>{previous.data.summary}</p>
            </section>
            <section>
              <h4>Resumo selecionado · revisão {revision.number}</h4>
              <p>{revision.summary}</p>
            </section>
          </div>
          {compareClaims(previous.data.claims, revision.claims).map((item) => (
            <article className="claim-diff" key={item.id}>
              <strong>
                {item.state === "added"
                  ? "Alegação adicionada"
                  : item.state === "removed"
                    ? "Alegação removida"
                    : item.state === "changed"
                      ? "Alegação alterada"
                      : "Alegação preservada"}
              </strong>
              <div className="review-diff">
                <ClaimVersion
                  claim={item.before}
                  missing="Não existia nesta revisão."
                  onEvidence={onEvidence}
                />
                <ClaimVersion
                  claim={item.after}
                  missing="Removida desta revisão."
                  onEvidence={onEvidence}
                />
              </div>
              {item.state === "changed" && (
                <p className="muted">
                  Texto, tipo, fontes, relações ou verificações foram alterados.
                  Confira a alegação e suas citações antes de decidir.
                </p>
              )}
            </article>
          ))}
        </>
      )}
    </details>
  );
}

function ClaimVersion({
  claim,
  missing,
  onEvidence,
}: {
  claim?: Claim;
  missing: string;
  onEvidence: (id: string) => void;
}) {
  if (!claim) return <section>{missing}</section>;
  return (
    <section>
      <h4>{label(claim.kind)}</h4>
      <p>{claim.text}</p>
      {claim.order_references.length > 0 && (
        <p>Pedidos: {claim.order_references.join(", ")}</p>
      )}
      <div className="source-links">
        {claim.evidence_links.map((link, index) => (
          <button
            type="button"
            className="source-button"
            key={link.evidence_id + link.relation}
            onClick={() => onEvidence(link.evidence_id)}
            title={link.evidence_id}
          >
            {label(link.relation)} · fonte {index + 1}
          </button>
        ))}
      </div>
      {claim.missing_information.map((text, index) => (
        <p key={"gap" + index} className="claim-note">
          Falta: {text}
        </p>
      ))}
      {claim.suggested_checks.map((text, index) => (
        <p key={"check" + index} className="claim-note">
          Verificar: {text}
        </p>
      ))}
    </section>
  );
}
