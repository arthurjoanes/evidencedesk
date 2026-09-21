"use client";
import { useEffect, useState } from "react";
import { revisionSchema, type Revision } from "@/lib/contracts";
import { request } from "@/lib/http";
import { useSession } from "@/lib/session";
import { label } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorNotice, Loading } from "@/components/feedback";

export function ReviewDecision({
  accessError,
  retryAccess,
  checkingAccess,
  dossierId,
  revision,
  onClose,
  onSaved,
}: {
  accessError?: unknown;
  retryAccess: () => void;
  checkingAccess: boolean;
  dossierId: string;
  revision: Revision;
  onClose: () => void;
  onSaved: (revision: Revision) => void;
}) {
  const session = useSession();
  const [reason, setReason] = useState("");
  const [decision, setDecision] = useState("approved");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const dirty = reason.length > 0 || decision !== "approved";
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
  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next && !busy) requestClose();
      }}
      title={"Revisar a versão " + revision.number}
      description="A decisão se aplica a esta revisão e às alegações listadas. Conferir citações continua sendo uma responsabilidade humana."
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
          <p>
            {revision.claims.length} alegações · {label(revision.outcome)}
          </p>
          <label className="field">
            Decisão
            <select
              value={decision}
              onChange={(event) => setDecision(event.target.value)}
            >
              <option value="approved">Aprovar esta revisão</option>
              <option value="changes_requested">Solicitar ajustes</option>
            </select>
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
          {error !== undefined && <ErrorNotice error={error} />}
          <div className="form-actions">
            <Button disabled={busy} onClick={requestClose}>
              Voltar
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={busy || reason.trim().length < 5}
            >
              {busy ? "Registrando…" : "Registrar decisão"}
            </Button>
          </div>
        </fieldset>
      </form>
    </Dialog>
  );
}
