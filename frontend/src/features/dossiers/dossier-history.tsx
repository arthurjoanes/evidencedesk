"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { dossierSummarySchema, pageSchema } from "@/lib/contracts";
import { queryString, request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { label, timestamp } from "@/lib/format";
import { ErrorNotice, Loading, Pagination } from "@/components/feedback";
export function DossierHistory({
  incidentId,
  selected,
  onSelect,
}: {
  incidentId: string;
  selected: string | null;
  onSelect: (dossierId: string, revisionId?: string) => void;
}) {
  const session = useSession();
  const [open, setOpen] = useState(false);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const query = useQuery({
    gcTime: 0,
    staleTime: 0,
    enabled: open,
    queryKey: [
      ...scopeKey(session),
      "dossier-history",
      incidentId,
      cursors.at(-1),
    ],
    queryFn: ({ signal }) =>
      request(
        "/api/v1/incidents/" +
          incidentId +
          "/dossiers" +
          queryString({ cursor: cursors.at(-1) }),
        pageSchema(dossierSummarySchema),
        { signal },
      ),
  });
  return (
    <details
      className="dossier-history"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Histórico de dossiês · selecione um resultado anterior</summary>
      {open && (query.isPending || query.isFetching) && (
        <Loading>Consultando histórico de dossiês…</Loading>
      )}
      {open && query.isError && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {open && !query.isFetching && !query.isError && query.data && (
        <>
          {!query.data.items.length && (
            <p className="revision-provenance">
              Nenhum dossiê disponível neste histórico.
            </p>
          )}
          <ul>
            {query.data.items.map((item) => (
              <li key={item.id}>
                <button
                  className="history-selection"
                  aria-current={item.id === selected ? "true" : undefined}
                  onClick={() => onSelect(item.id, item.current_revision_id)}
                >
                  <span>
                    {label(item.origin)} · {timestamp(item.created_at)}
                  </span>
                  <small>
                    {item.approved_revision_id
                      ? "Possui revisão aprovada"
                      : "Sem revisão aprovada"}
                  </small>
                </button>
                {item.approved_revision_id && (
                  <button
                    className="source-button"
                    onClick={() =>
                      onSelect(item.id, item.approved_revision_id!)
                    }
                  >
                    Abrir revisão aprovada
                  </button>
                )}
              </li>
            ))}
          </ul>
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
        </>
      )}
    </details>
  );
}
