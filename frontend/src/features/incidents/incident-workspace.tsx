"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { Group, Panel, Separator, usePanelRef } from "react-resizable-panels";
import { ArrowLeft, Search, ScanText } from "lucide-react";
import { incidentSchema, type Incident } from "@/lib/contracts";
import { request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { number, timestamp, eventTimestamp, label } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { ErrorNotice, Loading, Status } from "@/components/feedback";
import { EvidenceReader } from "@/features/evidence/evidence-reader";
import { SourceList } from "@/features/evidence/source-list";
import { DossierDialogs } from "@/features/dossiers/dossier-dialogs";
import { DossierView } from "@/features/dossiers/dossier-view";
import {
  DivergenceList,
  EventTimeline,
} from "@/features/timeline/incident-records";
import { queueDestination, workspaceDestination } from "./navigation";
import { RunPanel, StartInvestigation } from "./run-panel";

const tabs = [
  { id: "divergences", name: "Divergências" },
  { id: "timeline", name: "Linha do tempo" },
  { id: "dossier", name: "Dossiê" },
  { id: "sources", name: "Fontes" },
];
function subscribeWidth(callback: () => void) {
  const media = window.matchMedia("(min-width: 1100px)");
  media.addEventListener("change", callback);
  return () => media.removeEventListener("change", callback);
}
export function IncidentWorkspace({ id }: { id: string }) {
  const session = useSession();
  const incident = useQuery({
    queryKey: [...scopeKey(session), "incident", id],
    queryFn: ({ signal }) =>
      request("/api/v1/incidents/" + encodeURIComponent(id), incidentSchema, {
        signal,
      }),
  });
  if (incident.isPending) return <Loading>Abrindo o incidente…</Loading>;
  if (incident.isError)
    return (
      <ErrorNotice
        error={incident.error}
        retry={() => void incident.refetch()}
      />
    );
  return <Workspace key={id} incident={incident.data} />;
}
function Workspace({ incident }: { incident: Incident }) {
  const session = useSession();
  const pathname = usePathname();
  const params = useSearchParams();
  const [initialSnapshot] = useState(incident.evidence_snapshot_id);
  const [initialDossier] = useState(incident.dossier_id);
  const [starting, setStarting] = useState(false);
  const selectedSourceTrigger = useRef<HTMLElement | null>(null);
  const selectedSourceId = useRef<string | null>(null);
  const content = useRef<HTMLDivElement>(null);
  const reader = usePanelRef();
  const desktop = useSyncExternalStore(
    subscribeWidth,
    () => window.matchMedia("(min-width: 1100px)").matches,
    () => false,
  );
  const snapshot = params.get("snapshot") ?? initialSnapshot;
  const evidenceId = params.get("evidence");
  const evidenceSnapshot = params.get("evidence_snapshot") ?? snapshot;
  const tab = tabs.some((entry) => entry.id === params.get("tab"))
    ? params.get("tab")!
    : "divergences";
  const order = params.get("order") ?? "";
  const runId = params.get("run") ?? incident.latest_run?.id;
  function destination(changes: Record<string, string | null>) {
    return workspaceDestination(pathname, params.toString(), snapshot, changes);
  }
  function navigate(changes: Record<string, string | null>) {
    // Query-only client state: read the live URL so successive actions compose,
    // even when React has not rendered the preceding selection yet.
    window.history.pushState(
      null,
      "",
      workspaceDestination(pathname, window.location.search, snapshot, changes),
    );
  }
  function openEvidence(id: string, sourceSnapshot = snapshot) {
    selectedSourceId.current = id;
    selectedSourceTrigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    navigate({ evidence: id, evidence_snapshot: sourceSnapshot });
  }
  function closeEvidence() {
    navigate({ evidence: null, evidence_snapshot: null });
  }
  useEffect(() => {
    if (evidenceId || !selectedSourceTrigger.current) return;
    const target = selectedSourceTrigger.current;
    if (target.isConnected) target.focus();
    else {
      const replacement = selectedSourceId.current
        ? document.querySelector<HTMLElement>(
            `[data-evidence-id="${CSS.escape(selectedSourceId.current)}"]`,
          )
        : null;
      (replacement ?? content.current)?.focus();
    }
  }, [evidenceId]);
  const workspace = (
    <div
      ref={content}
      tabIndex={-1}
      className="work-content"
      hidden={!desktop && !!evidenceId}
    >
      <nav className="workspace-tabs" aria-label="Conteúdo do incidente">
        {tabs.map((entry) => (
          <Link
            key={entry.id}
            href={destination({ tab: entry.id })}
            scroll={false}
            onClick={(event) => {
              if (
                !event.metaKey &&
                !event.ctrlKey &&
                !event.shiftKey &&
                !event.altKey &&
                event.button === 0
              ) {
                event.preventDefault();
                navigate({ tab: entry.id });
              }
            }}
            aria-current={tab === entry.id ? "page" : undefined}
          >
            {entry.name}
          </Link>
        ))}
      </nav>
      {["divergences", "timeline"].includes(tab) && (
        <form
          key={order}
          className="filter-form"
          style={{ marginBottom: 18 }}
          onSubmit={(event) => {
            event.preventDefault();
            navigate({
              order: String(
                new FormData(event.currentTarget).get("order") ?? "",
              ).trim(),
            });
          }}
        >
          <label className="search-field">
            <Search size={16} />
            <span className="sr-only">Referência exata do pedido</span>
            <input
              className="search-input"
              name="order"
              defaultValue={order}
              placeholder="Referência exata do pedido"
            />
          </label>
          <Button type="submit">Filtrar</Button>
          {order && (
            <Button variant="ghost" onClick={() => navigate({ order: null })}>
              Limpar
            </Button>
          )}
        </form>
      )}
      {tab === "divergences" && (
        <DivergenceList
          key={snapshot + order}
          incidentId={incident.id}
          snapshotId={snapshot}
          order={order}
          onEvidence={openEvidence}
        />
      )}
      {tab === "timeline" && (
        <EventTimeline
          key={snapshot + order}
          incidentId={incident.id}
          snapshotId={snapshot}
          order={order}
          onEvidence={openEvidence}
        />
      )}
      {tab === "dossier" && (
        <DossierView
          selectedDossierId={params.get("dossier") ?? initialDossier}
          selectedRevisionId={params.get("revision")}
          onSelect={(dossierId, revisionId) =>
            navigate({ dossier: dossierId, revision: revisionId ?? null })
          }
          incident={incident}
          snapshotId={snapshot}
          onEvidence={openEvidence}
        />
      )}
      {tab === "sources" && (
        <SourceList
          key={snapshot}
          incidentId={incident.id}
          snapshotId={snapshot}
          onEvidence={openEvidence}
        />
      )}
    </div>
  );
  const evidence = evidenceId && (
    <EvidenceReader
      key={evidenceId + evidenceSnapshot}
      id={evidenceId}
      snapshotId={evidenceSnapshot}
      onClose={closeEvidence}
      onResize={(size) => reader.current?.resize(size + "%")}
    />
  );
  return (
    <DossierDialogs
      onSaved={(dossierId, revisionId) =>
        navigate({
          tab: "dossier",
          dossier: dossierId,
          revision: revisionId ?? null,
        })
      }
    >
      <div hidden={!desktop && !!evidenceId}>
        <Link href={queueDestination(params)} className="back-link">
          <ArrowLeft size={14} />
          Incidentes
        </Link>
        <div className="page-heading incident-heading">
          <div>
            <h1>{incident.title}</h1>
            <p>{incident.description}</p>
            <div className="page-title-meta">
              <Status value={incident.status} />
              <span>Atualizado {timestamp(incident.updated_at)}</span>
            </div>
          </div>
          {incident.permissions.includes("create_run") && (
            <Button
              variant="primary"
              disabled={!session.runtime.generation_enabled}
              onClick={() => setStarting(true)}
            >
              <ScanText size={16} />
              Investigar com IA
            </Button>
          )}
        </div>
        {!session.runtime.generation_enabled && (
          <p className="notice notice-info" style={{ marginBottom: 16 }}>
            {session.runtime.disabled_reason ??
              "O gerador está indisponível. A leitura de fontes e a revisão manual continuam disponíveis."}
          </p>
        )}
        <dl className="scope-strip">
          <div className="scope-item">
            <dt>Período do incidente</dt>
            <dd>
              {timestamp(incident.window.from)} →{" "}
              {timestamp(incident.window.to)}
            </dd>
            <dd>Exibição em Brasília · recorte {incident.window.time_zone}</dd>
          </div>
          <div className="scope-item">
            <dt>Pedidos no snapshot ativo</dt>
            <dd>
              <strong>{number(incident.counts.orders)}</strong>
            </dd>
          </div>
          <div className="scope-item">
            <dt>Divergências no snapshot ativo</dt>
            <dd>
              <strong>{number(incident.counts.divergences)}</strong>
            </dd>
          </div>
          <div className="scope-item">
            <dt>
              <label htmlFor="snapshot">Snapshot em leitura</label>
            </dt>
            <dd>
              <select
                id="snapshot"
                className="filter-select"
                value={snapshot}
                onChange={(event) =>
                  navigate({
                    snapshot: event.target.value,
                    evidence: null,
                    evidence_snapshot: null,
                  })
                }
              >
                {incident.available_snapshots.map((item) => (
                  <option key={item.id} value={item.id}>
                    {eventTimestamp(item.published_at)} · {item.id.slice(0, 8)}
                    {item.id === incident.evidence_snapshot_id
                      ? " · ativo"
                      : ""}
                  </option>
                ))}
              </select>
            </dd>
          </div>
        </dl>
        {snapshot !== incident.evidence_snapshot_id && (
          <p className="notice notice-warning">
            Você está lendo um snapshot anterior. As contagens e a cobertura
            geral acima se referem ao snapshot ativo; os registros abaixo seguem
            o recorte selecionado.
          </p>
        )}
        <details className="coverage">
          <summary>
            Cobertura declarada do snapshot ativo ·{" "}
            {new Set(incident.coverage.map((item) => item.source_system)).size}{" "}
            sistemas · {incident.coverage.length} janelas
          </summary>
          <div className="coverage-list">
            {incident.coverage.map((source, index) => (
              <div
                className="coverage-source"
                key={source.source_system + index}
              >
                <strong>{source.source_system}</strong> · {label(source.status)}
                <p>
                  {timestamp(source.from)} → {timestamp(source.to)}
                </p>
                {source.gaps.map((gap, position) => (
                  <p key={position}>{gap}</p>
                ))}
              </div>
            ))}
          </div>
          <p>
            A ausência de um evento só pode ser interpretada dentro desta
            cobertura.
          </p>
        </details>
        {runId && (
          <RunPanel
            key={runId}
            runId={runId}
            incidentId={incident.id}
            onResult={(dossierId, revisionId) =>
              navigate({
                tab: "dossier",
                dossier: dossierId,
                revision: revisionId,
              })
            }
          />
        )}
      </div>
      {!desktop && evidenceId && (
        <p className="mobile-reading-context">
          Conferindo fonte de <strong>{incident.title}</strong>
        </p>
      )}
      {desktop ? (
        <Group className="work-area" orientation="horizontal">
          <Panel
            id="investigation"
            minSize="35%"
            defaultSize={evidenceId ? "58%" : "100%"}
          >
            {workspace}
          </Panel>
          {evidenceId && (
            <>
              <Separator
                className="evidence-separator"
                aria-label="Ajustar largura da evidência"
              />
              <Panel
                id="evidence"
                panelRef={reader}
                minSize="30%"
                defaultSize="42%"
              >
                {evidence}
              </Panel>
            </>
          )}
        </Group>
      ) : (
        <div className="work-area">
          {workspace}
          {evidence}
        </div>
      )}
      {starting && (
        <StartInvestigation
          incident={incident}
          snapshotId={snapshot}
          open
          onClose={() => setStarting(false)}
          onStarted={(id) => navigate({ run: id })}
        />
      )}
    </DossierDialogs>
  );
}
