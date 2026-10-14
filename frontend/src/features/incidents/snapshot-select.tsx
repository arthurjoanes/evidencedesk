"use client";
import { useInfiniteQuery } from "@tanstack/react-query";
import { z } from "zod";
import { pageSchema, type Incident } from "@/lib/contracts";
import { queryString, request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { eventTimestamp } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { ErrorNotice } from "@/components/feedback";

const snapshotSchema = z.object({ id: z.string(), published_at: z.string() });

export function SnapshotSelect({
  incident,
  value,
  onChange,
}: {
  incident: Incident;
  value: string;
  onChange: (id: string) => void;
}) {
  const session = useSession();
  const pages = useInfiniteQuery({
    queryKey: [...scopeKey(session), "snapshot-options", incident.id],
    initialPageParam: null as string | null,
    enabled: incident.available_snapshots_truncated,
    queryFn: ({ signal, pageParam }) =>
      request(
        `/api/v1/incidents/${incident.id}/snapshots` +
          queryString({ cursor: pageParam, limit: 50 }),
        pageSchema(snapshotSchema),
        { signal },
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const options = [
    ...new Map(
      [
        ...incident.available_snapshots,
        ...(pages.data?.pages.flatMap((page) => page.items) ?? []),
      ].map((item) => [item.id, item]),
    ).values(),
  ];
  return (
    <>
      <select
        id="snapshot"
        className="filter-select"
        value={value}
        disabled={pages.isError}
        onChange={(event) => onChange(event.target.value)}
      >
        {!options.some((item) => item.id === value) && (
          <option value={value}>
            Recorte selecionado · {value.slice(0, 8)}
          </option>
        )}
        {options.map((item) => (
          <option key={item.id} value={item.id}>
            {eventTimestamp(item.published_at)} · {item.id.slice(0, 8)}
            {item.id === incident.evidence_snapshot_id ? " · ativo" : ""}
          </option>
        ))}
      </select>
      {incident.available_snapshots_truncated &&
        (pages.isPending || pages.hasNextPage) && (
          <p className="muted" role="status">
            Há recortes anteriores que não estão nesta lista.
          </p>
        )}
      {pages.isError && (
        <ErrorNotice error={pages.error} retry={() => void pages.refetch()} />
      )}
      {pages.hasNextPage && (
        <Button
          size="small"
          disabled={pages.isFetching}
          onClick={() => void pages.fetchNextPage()}
        >
          {pages.isFetchingNextPage
            ? "Carregando…"
            : "Carregar recortes anteriores"}
        </Button>
      )}
    </>
  );
}
