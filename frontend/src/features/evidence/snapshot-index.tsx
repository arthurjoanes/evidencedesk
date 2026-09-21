"use client";
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { ErrorNotice, Loading, Status } from "@/components/feedback";
import { ApiError, request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { label, number } from "@/lib/format";
import { indexSchema } from "./index-contract";

export function SnapshotIndex({ snapshotId }: { snapshotId: string }) {
  const [open, setOpen] = useState(false);
  const session = useSession();
  const client = useQueryClient();
  const intention = useRef<string | null>(null);
  const key = [...scopeKey(session), "snapshot-index", snapshotId];
  const endpoint =
    "/api/v1/evidence-snapshots/" + encodeURIComponent(snapshotId) + "/index";
  const query = useQuery({
    queryKey: key,
    enabled: open,
    queryFn: async ({ signal }) => {
      const value = await request(endpoint, indexSchema, { signal });
      if (value.evidence_snapshot_id !== snapshotId)
        throw new ApiError(
          502,
          "invalid_response",
          "O índice recebido pertence a outro snapshot.",
        );
      return value;
    },
    refetchInterval: (query) =>
      open &&
      ["queued", "running", "retry_wait"].includes(
        query.state.data?.job?.state ?? "",
      )
        ? 1500
        : false,
  });
  const create = useMutation({
    mutationFn: async () => {
      intention.current ??= crypto.randomUUID();
      const value = await request(endpoint, indexSchema, {
        method: "POST",
        csrf: session.csrf_token,
        headers: { "Idempotency-Key": intention.current },
      });
      if (value.evidence_snapshot_id !== snapshotId)
        throw new ApiError(
          502,
          "invalid_response",
          "O índice recebido pertence a outro snapshot.",
        );
      return value;
    },
    onSuccess: (value) => {
      client.setQueryData(key, value);
      intention.current = null;
    },
  });
  const state = query.isError ? undefined : query.data;
  return (
    <details
      className="snapshot-index"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Disponibilidade da busca semântica</summary>
      {open && (
        <div className="snapshot-index-content">
          {query.isPending && (
            <Loading>Conferindo o índice deste snapshot…</Loading>
          )}
          {query.isError && (
            <ErrorNotice
              error={query.error}
              retry={() => void query.refetch()}
            />
          )}
          {state && (
            <>
              <p>
                <strong>
                  {number(state.indexed_documents)} de{" "}
                  {number(state.total_documents)} trechos documentais preparados
                </strong>
              </p>
              <p>
                {state.total_documents === 0
                  ? "Este snapshot não contém trechos documentais para indexar."
                  : state.complete
                    ? "O índice cobre os trechos deste snapshot."
                    : "A busca semântica depende da preparação de todos os trechos. A leitura das fontes continua disponível."}
              </p>
              {!state.indexing_enabled && (
                <p>
                  {state.disabled_reason ??
                    "O perfil de modelos não está habilitado neste ambiente."}
                </p>
              )}
              {state.job && (
                <div className="index-job">
                  <Status value={state.job.state} />
                  <span>
                    {label(state.job.stage)} · tentativa{" "}
                    {number(state.job.attempt)}
                  </span>
                  {state.job.error && (
                    <p role="alert">{state.job.error.message}</p>
                  )}
                  {["failed", "cancelled"].includes(state.job.state) && (
                    <p>
                      A tentativa terminou sem concluir. O diagnóstico deve ser
                      conferido pela operação antes de reindexar.
                    </p>
                  )}
                </div>
              )}
              {state.indexing_enabled && !state.complete && !state.job && (
                <Button
                  size="small"
                  disabled={create.isPending}
                  onClick={() => create.mutate()}
                >
                  {create.isPending ? "Solicitando…" : "Preparar índice"}
                </Button>
              )}
            </>
          )}
          {create.isError && <ErrorNotice error={create.error} />}
        </div>
      )}
    </details>
  );
}
