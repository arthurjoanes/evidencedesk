"use client";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileText, X } from "lucide-react";
import { evidenceSchema } from "@/lib/contracts";
import { request, queryString, apiUrl } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { label, timestamp } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { ErrorNotice, Loading } from "@/components/feedback";
import { CanonicalContent } from "./canonical-content";
import { readReconciliation } from "./reconciliation-content";
import { ReconciliationSummary } from "./reconciliation-summary";

const PdfViewer = dynamic(
  () => import("./pdf-viewer").then((module) => module.PdfViewer),
  { ssr: false, loading: () => <Loading>Preparando leitor PDF…</Loading> },
);
export function EvidenceReader({
  id,
  snapshotId,
  onClose,
  onResize,
}: {
  id: string;
  snapshotId: string;
  onClose: () => void;
  onResize: (size: number) => void;
}) {
  const session = useSession();
  const heading = useRef<HTMLHeadingElement>(null);
  const [mode, setMode] = useState<"summary" | "text" | "pdf">("summary");
  const query = useQuery({
    gcTime: 0,
    staleTime: 0,
    queryKey: [...scopeKey(session), "evidence", id, snapshotId],
    queryFn: ({ signal }) =>
      request(
        "/api/v1/evidence/" +
          encodeURIComponent(id) +
          queryString({ evidence_snapshot_id: snapshotId }),
        evidenceSchema,
        { signal },
      ),
  });
  const evidence = query.isError || query.isFetching ? undefined : query.data;
  const reconciliation = useMemo(
    () =>
      evidence?.kind === "reconciliation_result"
        ? readReconciliation(evidence.canonical_text)
        : null,
    [evidence],
  );
  const visibleMode = mode === "summary" && !reconciliation ? "text" : mode;
  useEffect(() => {
    heading.current?.focus({ preventScroll: false });
  }, [id]);
  return (
    <section className="evidence-panel" aria-label="Leitor de evidência">
      <div className="evidence-heading">
        <div className="evidence-heading-top">
          <span className="section-kicker">FONTE SELECIONADA</span>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Fechar fonte e voltar à seleção"
            onClick={onClose}
          >
            <X size={17} />
          </Button>
        </div>
        <h2 ref={heading} tabIndex={-1}>
          {evidence?.title ?? "Conferir evidência"}
        </h2>
        {evidence && (
          <div className="evidence-metadata">
            <span>{label(evidence.kind)}</span>
            <span>Versão {evidence.version}</span>
            {evidence.locator.page && (
              <span>Página {evidence.locator.page}</span>
            )}
            {evidence.locator.line_start && (
              <span>
                Linha {evidence.locator.line_start}
                {evidence.locator.line_end !== evidence.locator.line_start &&
                evidence.locator.line_end
                  ? "–" + evidence.locator.line_end
                  : ""}
              </span>
            )}
          </div>
        )}
      </div>
      <div className="evidence-tools">
        <Button size="small" variant="ghost" onClick={onClose}>
          <ArrowLeft size={14} />
          Voltar à seleção
        </Button>
        <Button
          className="desktop-resize"
          size="small"
          onClick={() => onResize(50)}
        >
          Dividir ao meio
        </Button>
      </div>
      {(query.isPending || query.isFetching) && (
        <Loading>Consultando a fonte autorizada…</Loading>
      )}
      {query.isError && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {evidence && (
        <>
          <div className="evidence-tools">
            {reconciliation && (
              <Button
                size="small"
                variant={visibleMode === "summary" ? "primary" : "secondary"}
                onClick={() => setMode("summary")}
                aria-pressed={visibleMode === "summary"}
              >
                Leitura estruturada
              </Button>
            )}
            <Button
              size="small"
              variant={visibleMode === "text" ? "primary" : "secondary"}
              onClick={() => setMode("text")}
              aria-pressed={visibleMode === "text"}
            >
              Texto canônico
            </Button>
            {evidence.original?.media_type === "application/pdf" && (
              <Button
                size="small"
                variant={mode === "pdf" ? "primary" : "secondary"}
                onClick={() => setMode("pdf")}
                aria-pressed={mode === "pdf"}
              >
                <FileText size={13} />
                Página PDF
              </Button>
            )}
          </div>
          {evidence.temporal_role && (
            <p className="evidence-role">{label(evidence.temporal_role)}</p>
          )}
          {visibleMode === "summary" && reconciliation ? (
            <ReconciliationSummary content={reconciliation} />
          ) : visibleMode === "pdf" && evidence.original ? (
            <>
              <PdfViewer
                key={evidence.original.content_url}
                url={(() => {
                  const content = new URL(
                    apiUrl(evidence.original.content_url),
                    "https://evidencedesk.invalid",
                  );
                  content.searchParams.set("evidence_snapshot_id", snapshotId);
                  return content.pathname + content.search;
                })()}
                initialPage={evidence.locator.page ?? 1}
              />
              <p className="evidence-role">
                A página preserva o original. O trecho citado é o texto
                canônico; não há destaque visual aproximado.
              </p>
            </>
          ) : (
            <>
              {evidence.kind === "reconciliation_result" && !reconciliation && (
                <p className="evidence-role">
                  O formato da conciliação não pôde ser validado para leitura
                  estruturada. Confira o conteúdo original abaixo; nenhum valor
                  foi inferido.
                </p>
              )}
              <CanonicalContent
                key={evidence.id}
                text={evidence.canonical_text}
              />
            </>
          )}
          <details className="evidence-technical">
            <summary>Proveniência e detalhes técnicos</summary>
            <dl>
              <dt>Sistema</dt>
              <dd>{evidence.source_system}</dd>
              <dt>Vigência</dt>
              <dd>
                {timestamp(evidence.valid_from)} →{" "}
                {timestamp(evidence.valid_until)}
              </dd>
              <dt>SHA-256</dt>
              <dd>
                <code>{evidence.sha256}</code>
              </dd>
              <dt>Evidência</dt>
              <dd>
                <code>{evidence.id}</code>
              </dd>
              <dt>Snapshot</dt>
              <dd>
                <code>{snapshotId}</code>
              </dd>
            </dl>
          </details>
        </>
      )}
    </section>
  );
}
