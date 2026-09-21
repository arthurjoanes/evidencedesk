"use client";
import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Search } from "lucide-react";
import { evidenceSummarySchema, pageSchema } from "@/lib/contracts";
import { queryString, request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { label } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { SnapshotIndex } from "./snapshot-index";
import {
  EmptyState,
  ErrorNotice,
  Loading,
  Pagination,
} from "@/components/feedback";

export function SourceList({
  incidentId,
  snapshotId,
  onEvidence,
}: {
  incidentId: string;
  snapshotId: string;
  onEvidence: (id: string) => void;
}) {
  const [search, setSearch] = useState("");
  return (
    <>
      <SnapshotIndex key={snapshotId} snapshotId={snapshotId} />
      <form
        className="filter-form"
        style={{ marginBottom: 22 }}
        onSubmit={(event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          setSearch(String(new FormData(event.currentTarget).get("q") ?? ""));
        }}
      >
        <label className="search-field">
          <Search size={16} />
          <span className="sr-only">Buscar nas fontes</span>
          <input
            className="search-input"
            name="q"
            placeholder="Buscar título ou trecho"
          />
        </label>
        <Button type="submit">Buscar</Button>
      </form>
      <SourceResults
        key={snapshotId + search}
        incidentId={incidentId}
        snapshotId={snapshotId}
        search={search}
        onEvidence={onEvidence}
      />
    </>
  );
}
function SourceResults({
  incidentId,
  snapshotId,
  search,
  onEvidence,
}: {
  incidentId: string;
  snapshotId: string;
  search: string;
  onEvidence: (id: string) => void;
}) {
  const session = useSession();
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const query = useQuery({
    queryKey: [
      ...scopeKey(session),
      "sources",
      incidentId,
      snapshotId,
      search,
      cursors.at(-1),
    ],
    queryFn: ({ signal }) =>
      request(
        "/api/v1/incidents/" +
          incidentId +
          "/evidence" +
          queryString({
            evidence_snapshot_id: snapshotId,
            q: search,
            cursor: cursors.at(-1),
            limit: 20,
          }),
        pageSchema(evidenceSummarySchema),
        { signal },
      ),
  });
  if (query.isPending) return <Loading>Localizando fontes…</Loading>;
  if (query.isError)
    return (
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
    );
  if (!query.data.items.length)
    return (
      <EmptyState
        title="Nenhuma fonte neste recorte"
        description={
          search
            ? "Tente outro termo ou retire o filtro."
            : "Confira o snapshot e a cobertura do incidente."
        }
      />
    );
  return (
    <>
      <div className="source-list">
        {query.data.items.map((source) => (
          <article
            className={
              "source-entry" +
              (source.kind !== "document_span" ? " source-entry-compact" : "")
            }
            key={source.id}
          >
            <div className="source-entry-meta">
              <span>{label(source.kind)}</span>
              <span>{source.source_system}</span>
              <span>Versão {source.version}</span>
            </div>
            <h3>{source.title}</h3>
            {source.kind === "document_span" && <p>{source.excerpt}</p>}
            <div className="source-links">
              <button
                className="source-button"
                data-evidence-id={source.id}
                onClick={() => onEvidence(source.id)}
              >
                Conferir fonte
                <ArrowUpRight size={13} />
              </button>
              {source.temporal_role && (
                <span className="source-entry-meta">
                  {label(source.temporal_role)}
                </span>
              )}
            </div>
          </article>
        ))}
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
    </>
  );
}
