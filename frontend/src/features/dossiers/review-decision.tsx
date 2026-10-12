"use client";
import { useEffect, useRef, useState } from "react";
import { revisionSchema, type Revision } from "@/lib/contracts";
import { request } from "@/lib/http";
import { useSession } from "@/lib/session";
import { label } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorNotice, Loading } from "@/components/feedback";
import { EvidenceReader } from "@/features/evidence/evidence-reader";
import { CitationPreview } from "./citation-preview";
import { reviewReadiness, type Decision } from "./review-readiness";

export function ReviewDecision({
  accessError,
  retryAccess,
  checkingAccess,
  dossierId,
  snapshotId,
  revision,
  onClose,
  onSaved,
  onCloseAutoFocus,
}: {
  accessError?: unknown;
  retryAccess: () => void;
  checkingAccess: boolean;
  dossierId: string;
  snapshotId: string;
  revision: Revision;
  onClose: () => void;
  onSaved: (revision: Revision) => void;
  onCloseAutoFocus?: (event: Event) => void;
}) {
  const session = useSession();
  const [reason, setReason] = useState("");
  const [decision, setDecision] = useState<Decision>("");
  const [confirmed, setConfirmed] = useState<Set<string>>(() => new Set());
  const [abstentionConfirmed, setAbstentionConfirmed] = useState(false);
  const [selected, setSelected] = useState<{
    claimId: string;
    evidenceId: string;
  } | null>(null);
  const sourceTrigger = useRef<HTMLElement | null>(null);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const dirty =
    reason.length > 0 ||
    decision !== "" ||
    confirmed.size > 0 ||
    abstentionConfirmed;
  const readiness = reviewReadiness(
    decision,
    reason,
    revision.claims.map((claim) => claim.claim_id),
    confirmed,
    abstentionConfirmed,
  );
  const selectedIndex = revision.claims.findIndex(
    (claim) => claim.claim_id === selected?.claimId,
  );
  const selectedClaim = revision.claims[selectedIndex];
  const selectedLink = selectedClaim?.evidence_links.find(
    (link) => link.evidence_id === selected?.evidenceId,
  );
  useEffect(() => {
    if (!dirty) return;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
  function requestClose() {
    if (!dirty || window.confirm("Descartar esta decisão não registrada?"))
      onClose();
  }
  function closeSource() {
    setSelected(null);
    const original = sourceTrigger.current;
    const replacement = selected
      ? document.querySelector<HTMLElement>(
          `.review-claims [data-evidence-id="${CSS.escape(selected.evidenceId)}"][data-claim-id="${CSS.escape(selected.claimId)}"]`,
        )
      : null;
    const target =
      original?.isConnected &&
      original.getClientRects().length &&
      original.dataset.evidenceId === selected?.evidenceId &&
      original.dataset.claimId === selected?.claimId
        ? original
        : replacement;
    if (target?.isConnected && target.getClientRects().length) target.focus();
  }
  return (
    <Dialog
      open
      wide
      onCloseAutoFocus={onCloseAutoFocus}
      onOpenChange={(next) => {
        if (!next && !busy) requestClose();
      }}
      title={"Revisar a versão " + revision.number}
      description="Confira as alegações e suas fontes. Sua decisão se aplica somente a esta revisão do dossiê."
    >
      {accessError !== undefined && (
        <ErrorNotice error={accessError} retry={retryAccess} />
      )}
      {checkingAccess && accessError === undefined && (
        <Loading>Conferindo acesso…</Loading>
      )}
      <form
        hidden={checkingAccess}
        className="form-stack"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!readiness.canRecord || busy || checkingAccess) return;
          setBusy(true);
          setError(undefined);
          try {
            const next = await request(
              "/api/v1/dossiers/" + dossierId + "/reviews",
              revisionSchema,
              {
                method: "POST",
                csrf: session.csrf_token,
                headers: { "If-Match": revision.etag },
                body: {
                  target_revision_id: revision.id,
                  claim_ids: revision.claims.map((claim) => claim.claim_id),
                  decision,
                  reason,
                },
              },
            );
            onSaved(next);
            onClose();
          } catch (failure) {
            setError(failure);
          } finally {
            setBusy(false);
          }
        }}
      >
        <fieldset className="form-stack form-fields" disabled={busy}>
          <section
            className="review-summary"
            aria-label="Revisão em conferência"
          >
            <h3>Resultado do recorte: {label(revision.outcome)}</h3>
            <p>{revision.summary}</p>
            {revision.missing_information?.length ? (
              <div className="claim-note">
                <strong>Lacunas do recorte</strong>
                <ul>
                  {revision.missing_information.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </section>
          <div
            className={
              "review-layout" +
              (selected && selectedClaim && selectedLink
                ? " review-layout-with-source"
                : "")
            }
          >
            <section
              className="review-claims"
              aria-labelledby="review-claims-heading"
            >
              <h3 id="review-claims-heading">Conferir antes de decidir</h3>
              <p className="review-help">
                Uma fonte vinculada não comprova suporte. Confira o trecho, o
                pedido e o período de cada alegação.
              </p>
              {revision.claims.map((claim, index) => (
                <article className="review-claim" key={claim.claim_id}>
                  <h4>
                    Alegação {index + 1} · {label(claim.kind)}
                  </h4>
                  <p className="claim-text">{claim.text}</p>
                  <div className="source-links">
                    {claim.evidence_links.map((link, sourceIndex) => (
                      <button
                        type="button"
                        className="source-button"
                        data-evidence-id={link.evidence_id}
                        data-claim-id={claim.claim_id}
                        key={link.evidence_id + link.relation}
                        aria-label={`Conferir fonte ${sourceIndex + 1} da alegação ${index + 1}`}
                        aria-pressed={
                          selected?.claimId === claim.claim_id &&
                          selected.evidenceId === link.evidence_id
                        }
                        onClick={(event) => {
                          sourceTrigger.current = event.currentTarget;
                          setSelected({
                            claimId: claim.claim_id,
                            evidenceId: link.evidence_id,
                          });
                        }}
                      >
                        Conferir fonte {sourceIndex + 1}
                        <span className="citation-link-relation">
                          {label(link.relation)}
                        </span>
                      </button>
                    ))}
                  </div>
                  {!claim.evidence_links.length && (
                    <p className="review-help">
                      Sem fonte vinculada. Confira os limites desta alegação;
                      não atribua suporte que não foi demonstrado.
                    </p>
                  )}
                  {claim.missing_information.length ? (
                    <div className="claim-note">
                      <strong>Informação que falta</strong>
                      <ul>
                        {claim.missing_information.map((item, index) => (
                          <li key={index}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  <label className="review-confirmation">
                    <input
                      type="checkbox"
                      aria-label={`Conferi a alegação ${index + 1}`}
                      checked={confirmed.has(claim.claim_id)}
                      onChange={(event) => {
                        const checked = event.target.checked;
                        setConfirmed((previous) => {
                          const next = new Set(previous);
                          if (checked) next.add(claim.claim_id);
                          else next.delete(claim.claim_id);
                          return next;
                        });
                      }}
                    />
                    <span>Conferi a alegação {index + 1}</span>
                  </label>
                </article>
              ))}
              {!revision.claims.length && (
                <div className="review-claim">
                  <p>
                    Esta revisão não apresenta alegações. Confira se a abstenção
                    corresponde ao resumo e às lacunas indicadas.
                  </p>
                  <label className="review-confirmation">
                    <input
                      type="checkbox"
                      aria-label="Conferi a abstenção e as lacunas desta revisão"
                      checked={abstentionConfirmed}
                      onChange={(event) =>
                        setAbstentionConfirmed(event.target.checked)
                      }
                    />
                    <span>Conferi a abstenção e as lacunas desta revisão.</span>
                  </label>
                </div>
              )}
              <p className="review-progress" role="status">
                {revision.claims.length
                  ? `${revision.claims.length - readiness.remaining} de ${revision.claims.length} alegações conferidas.`
                  : abstentionConfirmed
                    ? "Abstenção e lacunas conferidas."
                    : "Abstenção e lacunas ainda não conferidas."}{" "}
                Conferência não registra aprovação.
              </p>
            </section>
            {selected && selectedClaim && selectedLink && (
              <div className="review-source">
                <EvidenceReader
                  key={selected.evidenceId + selected.claimId}
                  id={selected.evidenceId}
                  snapshotId={snapshotId}
                  onClose={closeSource}
                  renderCitation={(sourceAvailable) =>
                    sourceAvailable ? (
                      <CitationPreview
                        claim={selectedClaim}
                        claimNumber={selectedIndex + 1}
                        revisionNumber={revision.number}
                        relation={selectedLink.relation}
                      />
                    ) : null
                  }
                />
              </div>
            )}
          </div>
          <label className="field">
            Decisão
            <select
              value={decision}
              required
              aria-describedby="review-decision-help"
              onChange={(event) => setDecision(event.target.value as Decision)}
            >
              <option value="">Escolha a decisão…</option>
              <option value="approved">Aprovar esta revisão</option>
              <option value="changes_requested">Solicitar ajustes</option>
            </select>
            <small id="review-decision-help" className="muted">
              Aprovar exige a conferência de todas as alegações ou da abstenção.
              Solicitar ajustes mantém esta revisão sem aprovação e se aplica a
              todas as alegações, incluindo as ainda não conferidas.
            </small>
          </label>
          <label className="field">
            Justificativa
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              required
              minLength={5}
              maxLength={3000}
              aria-describedby="review-reason-help"
              placeholder="O que foi conferido e quais limites permanecem?"
            />
            <small id="review-reason-help" className="muted">
              De 5 a 3.000 caracteres.
            </small>
          </label>
          {decision && (
            <p className="review-consequence">
              {decision === "approved"
                ? `Você vai aprovar a revisão ${revision.number}. A exportação continuará sujeita à autorização atual das fontes.`
                : `Você vai solicitar ajustes na revisão ${revision.number}. Solicitar ajustes se aplica a todas as alegações desta revisão, incluindo as ainda não conferidas. O autor poderá preparar outra revisão, preservando esta.`}
            </p>
          )}
          {error !== undefined && <ErrorNotice error={error} />}
          <div className="form-actions">
            <Button disabled={busy} onClick={requestClose}>
              Voltar
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={busy || !readiness.canRecord}
            >
              {busy ? "Registrando…" : "Registrar decisão"}
            </Button>
          </div>
        </fieldset>
      </form>
    </Dialog>
  );
}
