"use client";
import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Check,
  Download,
  Edit3,
  FilePlus2,
  Send,
} from "lucide-react";
import {
  dossierSchema,
  exportSchema,
  revisionSchema,
  type Incident,
  type Dossier,
} from "@/lib/contracts";
import { apiUrl, request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { label, timestamp, number } from "@/lib/format";
import { Button } from "@/components/ui/button";
import {
  EmptyState,
  ErrorNotice,
  Loading,
  Status,
} from "@/components/feedback";
import { useDossierDialogs } from "./dossier-dialogs";
import { RevisionComparison } from "./revision-comparison";
import { DossierHistory } from "./dossier-history";

export function DossierView({
  incident,
  snapshotId,
  selectedDossierId,
  selectedRevisionId,
  onSelect,
  onEvidence,
}: {
  incident: Incident;
  snapshotId: string;
  selectedDossierId: string | null;
  selectedRevisionId: string | null;
  onSelect: (dossierId: string, revisionId?: string) => void;
  onEvidence: (id: string, snapshotId?: string) => void;
}) {
  const session = useSession();
  const client = useQueryClient();
  const dialogs = useDossierDialogs();
  const dossier = useQuery({
    gcTime: 0,
    staleTime: 0,
    queryKey: [...scopeKey(session), "dossier", selectedDossierId],
    queryFn: ({ signal }) =>
      request("/api/v1/dossiers/" + selectedDossierId, dossierSchema, {
        signal,
      }),
    enabled: !!selectedDossierId,
  });
  const refresh = (dossierId?: string, revisionId?: string) => {
    void client.invalidateQueries({
      predicate: (entry) =>
        entry.queryKey.includes("dossier") ||
        entry.queryKey.includes(incident.id),
    });
    if (dossierId) onSelect(dossierId, revisionId);
  };
  return (
    <>
      <DossierHistory
        incidentId={incident.id}
        selected={selectedDossierId}
        onSelect={onSelect}
      />
      {incident.permissions.includes("create_dossier") && (
        <div className="button-row" style={{ margin: "16px 0" }}>
          <Button
            size="small"
            onClick={() =>
              dialogs.open({
                kind: "edit",
                incidentId: incident.id,
                snapshotId,
              })
            }
          >
            <FilePlus2 size={14} />
            Criar dossiê manual
          </Button>
        </div>
      )}
      {!selectedDossierId ? (
        <EmptyState
          title="Selecione ou prepare um dossiê"
          description="O histórico preserva os resultados anteriores. Um novo dossiê manual pode registrar fatos, hipóteses e lacunas sem depender do gerador."
        />
      ) : dossier.isPending ? (
        <Loading>Abrindo dossiê…</Loading>
      ) : dossier.isError ? (
        <ErrorNotice
          error={dossier.error}
          retry={() => void dossier.refetch()}
        />
      ) : dossier.data.incident_id !== incident.id ? (
        <p className="notice notice-danger" role="alert">
          Este dossiê não pertence ao incidente em leitura. Selecione um
          resultado do histórico.
        </p>
      ) : (
        <>
          {dossier.isFetching && (
            <Loading>Conferindo acesso ao dossiê…</Loading>
          )}
          <div hidden={dossier.isFetching}>
            <RevisionView
              key={
                dossier.data.id +
                (selectedRevisionId ?? dossier.data.current_revision_id)
              }
              dossier={dossier.data}
              incident={incident}
              selectedRevisionId={selectedRevisionId}
              onSelect={onSelect}
              onEvidence={onEvidence}
              onSaved={refresh}
            />
          </div>
        </>
      )}
    </>
  );
}

function RevisionView({
  dossier,
  incident,
  onEvidence,
  onSaved,
  selectedRevisionId,
  onSelect,
}: {
  selectedRevisionId: string | null;
  onSelect: (dossierId: string, revisionId?: string) => void;
  dossier: Dossier;
  incident: Incident;
  onEvidence: (id: string, snapshotId?: string) => void;
  onSaved: (dossierId?: string, revisionId?: string) => void;
}) {
  const session = useSession();
  const client = useQueryClient();
  const selected = selectedRevisionId ?? dossier.current_revision_id;
  const dialogs = useDossierDialogs();
  const [actionError, setActionError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [exportId, setExportId] = useState<string | null>(null);
  const exportIntent = useRef(new Map<string, string>());
  const revisionKey = [...scopeKey(session), "revision", dossier.id, selected];
  const revision = useQuery({
    gcTime: 0,
    staleTime: 0,
    queryKey: revisionKey,
    queryFn: ({ signal }) =>
      request(
        "/api/v1/dossiers/" + dossier.id + "/revisions/" + selected,
        revisionSchema,
        { signal },
      ),
  });
  const exportJob = useQuery({
    queryKey: [...scopeKey(session), "export", exportId],
    queryFn: ({ signal }) =>
      request("/api/v1/exports/" + exportId, exportSchema, { signal }),
    enabled: !!exportId,
    refetchInterval: (query) =>
      ["succeeded", "failed", "cancelled"].includes(
        query.state.data?.state ?? "",
      )
        ? false
        : 1500,
  });
  if (revision.isPending) return <Loading>Carregando revisão…</Loading>;
  if (revision.isError)
    return (
      <ErrorNotice
        error={revision.error}
        retry={() => void revision.refetch()}
      />
    );
  const current = revision.data;
  const canEdit =
    dossier.permissions.includes("edit_dossier") &&
    selected === dossier.current_revision_id;
  async function submit() {
    setBusy(true);
    setActionError(undefined);
    try {
      const next = await request(
        "/api/v1/dossiers/" + dossier.id + "/submit",
        revisionSchema,
        {
          method: "POST",
          csrf: session.csrf_token,
          headers: { "If-Match": current.etag },
          body: { target_revision_id: current.id },
        },
      );
      client.setQueryData(revisionKey, next);
      onSaved();
    } catch (error) {
      setActionError(error);
    } finally {
      setBusy(false);
    }
  }
  async function exportRevision() {
    setBusy(true);
    setActionError(undefined);
    if (!exportIntent.current.has(current.id))
      exportIntent.current.set(current.id, crypto.randomUUID());
    try {
      const result = await request(
        "/api/v1/dossiers/" + dossier.id + "/exports",
        exportSchema,
        {
          method: "POST",
          csrf: session.csrf_token,
          headers: { "Idempotency-Key": exportIntent.current.get(current.id)! },
          body: { revision_id: current.id },
        },
      );
      setExportId(result.id);
      client.setQueryData([...scopeKey(session), "export", result.id], result);
    } catch (error) {
      setActionError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      {revision.isFetching && <Loading>Conferindo acesso à revisão…</Loading>}
      <div hidden={revision.isFetching}>
        <div className="revision-toolbar">
          <label>
            <span className="sr-only">Revisão do dossiê</span>
            <select
              className="filter-select"
              value={selected}
              onChange={(event) => {
                onSelect(dossier.id, event.target.value);
                setExportId(null);
              }}
            >
              {dossier.revisions.map((item) => (
                <option key={item.id} value={item.id}>
                  Revisão {item.number} · {label(item.review_status)}
                </option>
              ))}
            </select>
          </label>
          <Status value={current.review_status} />
        </div>
        <p className="revision-provenance">
          {label(dossier.origin)} · {timestamp(current.created_at)} ·{" "}
          {label(current.outcome)}
        </p>
        {dossier.evidence_snapshot_id !== incident.evidence_snapshot_id && (
          <p className="notice notice-info">
            Este dossiê mantém o snapshot usado na sua criação. As citações
            abrem esse recorte autorizado.
          </p>
        )}
        {current.review?.reason && (
          <div className="claim-note">
            <strong>Justificativa da decisão</strong>
            <p>{current.review.reason}</p>
            <p>
              Revisor: <code>{current.review.reviewed_by}</code> ·{" "}
              {timestamp(current.review.updated_at)}
            </p>
          </div>
        )}
        <RevisionComparison
          onEvidence={(id) => onEvidence(id, dossier.evidence_snapshot_id)}
          key={current.id}
          dossierId={dossier.id}
          revision={current}
        />
        <p className="dossier-summary">{current.summary}</p>
        {current.impact_summary && (
          <details className="coverage">
            <summary>Impacto observado no snapshot deste dossiê</summary>
            <p>
              {number(current.impact_summary.orders)} pedidos ·{" "}
              {number(current.impact_summary.divergences)} divergências ·{" "}
              {number(current.impact_summary.not_evaluable)} avaliações sem
              cobertura suficiente.
            </p>
            <p>
              {number(current.impact_summary.observations)} observações ·{" "}
              {number(current.impact_summary.logical_events)} eventos lógicos.
              Contagens calculadas pelo servidor; não estimam perdas nem
              confirmam causalidade.
            </p>
            <p>
              Regra <code>{current.impact_summary.rule_revision}</code>
            </p>
          </details>
        )}
        {current.missing_information &&
          current.missing_information.length > 0 && (
            <div className="claim-note">
              <strong>Lacunas do recorte</strong>
              <ul>
                {current.missing_information.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        {current.suggested_checks && current.suggested_checks.length > 0 && (
          <div className="claim-note">
            <strong>Próximas verificações</strong>
            <ul>
              {current.suggested_checks.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="button-row">
          {canEdit && (
            <Button
              size="small"
              onClick={() =>
                dialogs.open({
                  kind: "edit",
                  incidentId: incident.id,
                  snapshotId: dossier.evidence_snapshot_id,
                  dossierId: dossier.id,
                  base: current,
                })
              }
            >
              <Edit3 size={14} />
              Preparar revisão
            </Button>
          )}
          {dossier.permissions.includes("submit_revision") &&
            ["draft", "changes_requested"].includes(current.review_status) &&
            selected === dossier.current_revision_id && (
              <Button
                size="small"
                variant="primary"
                disabled={busy}
                onClick={() => void submit()}
              >
                <Send size={14} />
                Enviar para revisão
              </Button>
            )}
          {dossier.permissions.includes("review_revision") &&
            current.review_status === "submitted" &&
            current.created_by !== session.user.id &&
            current.review?.submitted_by !== session.user.id && (
              <Button
                size="small"
                variant="primary"
                onClick={() =>
                  dialogs.open({
                    kind: "review",
                    incidentId: incident.id,
                    dossierId: dossier.id,
                    revision: current,
                  })
                }
              >
                <Check size={14} />
                Registrar decisão
              </Button>
            )}
          {dossier.permissions.includes("export_revision") &&
            current.review_status === "approved" && (
              <Button
                size="small"
                disabled={busy}
                onClick={() => void exportRevision()}
              >
                <Download size={14} />
                Preparar exportação
              </Button>
            )}
        </div>
        {actionError !== undefined && <ErrorNotice error={actionError} />}
        {exportId && (
          <div style={{ marginTop: 15 }}>
            {exportJob.isError ? (
              <ErrorNotice error={exportJob.error} />
            ) : exportJob.data?.state === "succeeded" &&
              exportJob.data.download_url ? (
              <div className="notice notice-info">
                <div>
                  <strong>Exportação disponível</strong>
                  <p>
                    Revisão {current.number} · expira{" "}
                    {timestamp(exportJob.data.expires_at)}
                  </p>
                  <a
                    className="button button-secondary button-small"
                    href={apiUrl(exportJob.data.download_url)}
                  >
                    Baixar HTML da revisão
                  </a>
                </div>
              </div>
            ) : exportJob.data?.error ? (
              <p className="notice notice-danger">
                {exportJob.data.error.message}
              </p>
            ) : (
              <Loading>Preparando a revisão autorizada…</Loading>
            )}
          </div>
        )}
        <div className="subheading">
          <h3>Alegações para conferir</h3>
          <span className="muted" style={{ fontSize: 12 }}>
            {current.claims.length} nesta revisão
          </span>
        </div>
        {!current.claims.length && (
          <p className="notice notice-warning">
            Esta revisão não apresenta alegações sustentadas. Leia as lacunas e
            o resultado do recorte antes de avançar.
          </p>
        )}
        <div>
          {current.claims.map((claim, index) => (
            <article key={claim.claim_id} className="claim">
              <div className="claim-topline">
                <span className="claim-kind">
                  {String(index + 1).padStart(2, "0")} · {label(claim.kind)}
                </span>
                <Status value={claim.support_status} />
              </div>
              <p className="claim-text">{claim.text}</p>
              {claim.order_references.length > 0 && (
                <p className="revision-provenance">
                  Pedidos: {claim.order_references.join(", ")}
                </p>
              )}
              <div className="source-links">
                {claim.evidence_links.map((link, sourceIndex) => (
                  <button
                    key={link.evidence_id + link.relation}
                    className="source-button"
                    onClick={() =>
                      onEvidence(link.evidence_id, dossier.evidence_snapshot_id)
                    }
                  >
                    {label(link.relation)} · fonte {sourceIndex + 1}
                    <ArrowUpRight size={12} />
                  </button>
                ))}
              </div>
              {claim.missing_information.length > 0 && (
                <div className="claim-note">
                  <strong>Informação que falta</strong>
                  <ul>
                    {claim.missing_information.map((text, item) => (
                      <li key={item}>{text}</li>
                    ))}
                  </ul>
                </div>
              )}
              {claim.suggested_checks.length > 0 && (
                <div className="claim-note">
                  <strong>Próximas verificações</strong>
                  <ul>
                    {claim.suggested_checks.map((text, item) => (
                      <li key={item}>{text}</li>
                    ))}
                  </ul>
                </div>
              )}
            </article>
          ))}
        </div>
      </div>
    </>
  );
}
