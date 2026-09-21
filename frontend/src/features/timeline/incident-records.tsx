"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import { divergencePageSchema, timelinePageSchema } from "@/lib/contracts";
import { request, queryString } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { label, eventTimestamp, number } from "@/lib/format";
import {
  EmptyState,
  ErrorNotice,
  Loading,
  Pagination,
  Status,
} from "@/components/feedback";

type Props = {
  incidentId: string;
  snapshotId: string;
  order: string;
  onEvidence: (id: string) => void;
};
export function DivergenceList({
  incidentId,
  snapshotId,
  order,
  onEvidence,
}: Props) {
  const session = useSession();
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const query = useQuery({
    queryKey: [
      ...scopeKey(session),
      "divergences",
      incidentId,
      snapshotId,
      order,
      cursors.at(-1),
    ],
    queryFn: ({ signal }) =>
      request(
        "/api/v1/incidents/" +
          incidentId +
          "/reconciliation" +
          queryString({
            evidence_snapshot_id: snapshotId,
            order_reference: order,
            cursor: cursors.at(-1),
          }),
        divergencePageSchema,
        { signal },
      ),
  });
  if (query.isPending) return <Loading>Conferindo divergências…</Loading>;
  if (query.isError)
    return (
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
    );
  if (!query.data.items.length)
    return (
      <EmptyState
        title="Nenhuma divergência neste recorte"
        description="Isso não comprova ausência de problemas. Confira a cobertura e o período das fontes."
      />
    );
  return (
    <div className="table-panel">
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Divergências por pedido"
      >
        <table style={{ minWidth: 510 }}>
          <thead>
            <tr>
              <th scope="col">Pedido / avaliação</th>
              <th scope="col">O que os registros mostram</th>
            </tr>
          </thead>
          <tbody>
            {query.data.items.map((item) => (
              <tr key={item.id}>
                <td style={{ width: 160 }}>
                  <strong className="mono">
                    {item.order_reference ?? "Sem correlação"}
                  </strong>
                  <div style={{ marginTop: 8 }}>
                    <Status value={item.status} />
                  </div>
                </td>
                <td>
                  <p>{item.summary}</p>
                  <div className="source-links">
                    {item.evidence_ids.map((id, index) => (
                      <button
                        key={id}
                        className="source-button"
                        data-evidence-id={id}
                        onClick={() => onEvidence(id)}
                      >
                        Evidência {index + 1}
                        <ArrowUpRight size={12} />
                      </button>
                    ))}
                  </div>
                  <details className="rule-detail">
                    <summary>Regra aplicada</summary>
                    <code>
                      {item.rule_code} · {item.rule_revision}
                    </code>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination
        total={query.data.total}
        count={query.data.items.length}
        page={cursors.length - 1}
        canNext={!!query.data.next_cursor}
        onPrevious={() => setCursors((previous) => previous.slice(0, -1))}
        onNext={() =>
          setCursors((previous) => [...previous, query.data.next_cursor])
        }
      />
    </div>
  );
}
export function EventTimeline({
  incidentId,
  snapshotId,
  order,
  onEvidence,
}: Props) {
  const session = useSession();
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const query = useQuery({
    queryKey: [
      ...scopeKey(session),
      "timeline",
      incidentId,
      snapshotId,
      order,
      cursors.at(-1),
    ],
    queryFn: ({ signal }) =>
      request(
        "/api/v1/incidents/" +
          incidentId +
          "/timeline" +
          queryString({
            evidence_snapshot_id: snapshotId,
            order_reference: order,
            cursor: cursors.at(-1),
          }),
        timelinePageSchema,
        { signal },
      ),
  });
  if (query.isPending)
    return <Loading>Reconstruindo a sequência observável…</Loading>;
  if (query.isError)
    return (
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
    );
  if (!query.data.items.length)
    return (
      <EmptyState
        title="Nenhum evento observado"
        description="A ausência se refere somente a este pedido, período e cobertura."
      />
    );
  return (
    <>
      <p className="timeline-caption">
        Ordenação por ocorrência; horários desconhecidos aparecem ao final. A
        sequência não comprova causalidade. Horários exibidos em Brasília, com a
        precisão declarada pela fonte.
      </p>
      <div className="table-panel">
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Timeline cronológica"
        >
          <table className="timeline-table">
            <thead>
              <tr>
                <th scope="col">Ocorrência / observação</th>
                <th scope="col">Evento e sistema</th>
                <th scope="col">Pedido / fonte</th>
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <time dateTime={item.occurred_at ?? undefined}>
                      {eventTimestamp(item.occurred_at)}
                    </time>
                    <small className="cell-description">
                      Observado: {eventTimestamp(item.observed_at)}
                    </small>
                    <details className="rule-detail">
                      <summary>Qualidade temporal</summary>
                      {label(item.temporal_quality)}
                      <br />
                      Importado: {eventTimestamp(item.ingested_at)}
                    </details>
                  </td>
                  <td>
                    <div className="timeline-event">
                      <span className="timeline-mark" />
                      <div>
                        <strong>{label(item.event_type)}</strong>
                        <small>{item.source_system}</small>
                        {item.delivery_count > 1 && (
                          <small>
                            {number(item.delivery_count)} entregas observadas
                          </small>
                        )}
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className="mono">
                      {item.order_reference ?? "Sem correlação"}
                    </span>
                    <div className="source-links">
                      <button
                        className="source-button"
                        data-evidence-id={item.evidence_id}
                        onClick={() => onEvidence(item.evidence_id)}
                      >
                        Conferir registro
                        <ArrowUpRight size={12} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination
          total={query.data.total}
          count={query.data.items.length}
          page={cursors.length - 1}
          canNext={!!query.data.next_cursor}
          onPrevious={() => setCursors((previous) => previous.slice(0, -1))}
          onNext={() =>
            setCursors((previous) => [...previous, query.data.next_cursor])
          }
        />
      </div>
    </>
  );
}
