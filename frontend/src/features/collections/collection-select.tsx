"use client";
import { useId, type ComponentProps } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { collectionSchema, pageSchema } from "@/lib/contracts";
import { queryString, request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { Button } from "@/components/ui/button";
import { ErrorNotice, FieldError, Loading } from "@/components/feedback";

export function CollectionSelect({
  label,
  publishedOnly = false,
  enabled = true,
  error,
  disabled,
  ...select
}: ComponentProps<"select"> & {
  label: string;
  publishedOnly?: boolean;
  enabled?: boolean;
  error?: string;
}) {
  const session = useSession();
  const errorId = useId();
  const collections = useInfiniteQuery({
    queryKey: [...scopeKey(session), "collection-options"],
    initialPageParam: null as string | null,
    enabled,
    queryFn: ({ signal, pageParam }) =>
      request(
        "/api/v1/collections" + queryString({ limit: 100, cursor: pageParam }),
        pageSchema(collectionSchema),
        { signal },
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const options = collections.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div className="form-stack">
      <label className="field">
        {label}
        <select
          {...select}
          aria-label={label}
          disabled={disabled || collections.isPending || collections.isError}
          aria-invalid={!!error}
          aria-describedby={error ? errorId : undefined}
        >
          <option value="">
            {publishedOnly
              ? "Selecione uma coleção publicada"
              : "Selecione uma coleção"}
          </option>
          {options.map((collection) => (
            <option
              key={collection.id}
              value={collection.id}
              disabled={publishedOnly && !collection.active_snapshot_id}
            >
              {collection.name}
              {publishedOnly && !collection.active_snapshot_id
                ? " — sem publicação"
                : ""}
            </option>
          ))}
        </select>
        <FieldError id={errorId} message={error} />
      </label>
      {collections.isPending && <Loading>Carregando coleções…</Loading>}
      {collections.isError && (
        <ErrorNotice
          error={collections.error}
          retry={() => void collections.refetch()}
        />
      )}
      {!collections.isPending && !collections.isError && !options.length && (
        <p className="notice notice-info" role="status">
          Nenhuma coleção está disponível para sua conta. Solicite acesso ao
          administrador da organização.
        </p>
      )}
      {collections.hasNextPage && (
        <Button
          size="small"
          disabled={disabled || collections.isFetching}
          onClick={() => void collections.fetchNextPage()}
        >
          {collections.isFetchingNextPage
            ? "Carregando…"
            : "Carregar mais coleções"}
        </Button>
      )}
    </div>
  );
}
