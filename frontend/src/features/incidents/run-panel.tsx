"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Circle, Check, Square, ArrowRight } from "lucide-react";
import { runSchema, streamEventSchema, type Incident } from "@/lib/contracts";
import { request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { label, timestamp, number } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import {
  ErrorNotice,
  FieldError,
  Loading,
  Status,
} from "@/components/feedback";

const questionSchema = z.object({
  question: z
    .string()
    .trim()
    .min(10, "Descreva o que precisa conferir.")
    .max(2000, "Use até 2.000 caracteres."),
});
const terminalStates = new Set(["succeeded", "failed", "cancelled"]);
export function StartInvestigation({
  incident,
  snapshotId,
  open,
  onClose,
  onStarted,
}: {
  incident: Incident;
  snapshotId: string;
  open: boolean;
  onClose: () => void;
  onStarted: (id: string) => void;
}) {
  const session = useSession();
  const [error, setError] = useState<unknown>();
  const intent = useRef<{ fingerprint: string; key: string } | null>(null);
  const form = useForm<z.infer<typeof questionSchema>>({
    resolver: zodResolver(questionSchema),
    defaultValues: { question: "" },
  });
  async function submit({ question }: z.infer<typeof questionSchema>) {
    setError(undefined);
    const fingerprint = JSON.stringify([incident.id, snapshotId, question]);
    if (intent.current?.fingerprint !== fingerprint)
      intent.current = { fingerprint, key: crypto.randomUUID() };
    try {
      const run = await request(
        "/api/v1/incidents/" + incident.id + "/runs",
        runSchema,
        {
          method: "POST",
          csrf: session.csrf_token,
          headers: { "Idempotency-Key": intent.current.key },
          body: { evidence_snapshot_id: snapshotId, question },
        },
      );
      onStarted(run.id);
      onClose();
    } catch (failure) {
      setError(failure);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !form.formState.isSubmitting) onClose();
      }}
      title="Investigar com IA"
      description="A execução usa o snapshot selecionado e ferramentas de leitura limitadas. O resultado será um rascunho para conferência."
    >
      <form
        onSubmit={(event) => void form.handleSubmit(submit)(event)}
        className="form-stack"
      >
        <label className="field">
          O que precisa ser esclarecido?
          <textarea
            rows={5}
            {...form.register("question")}
            placeholder="Quais pedidos estão divergentes e quais fontes apoiam ou contradizem a hipótese de reserva expirada?"
          />
          <FieldError message={form.formState.errors.question?.message} />
        </label>
        <p className="muted">
          Gerador: {session.runtime.model_display_name}. A investigação não
          executa alterações em pedidos, pagamentos ou estoque.
        </p>
        {error !== undefined && <ErrorNotice error={error} />}
        <div className="form-actions">
          <Button disabled={form.formState.isSubmitting} onClick={onClose}>
            Voltar
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={
              form.formState.isSubmitting || !session.runtime.generation_enabled
            }
          >
            {form.formState.isSubmitting ? "Enviando…" : "Iniciar investigação"}
            <ArrowRight size={15} />
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function RunPanel({
  runId,
  incidentId,
  onResult,
}: {
  runId: string;
  incidentId: string;
  onResult: (dossierId: string, revisionId: string | null) => void;
}) {
  const session = useSession();
  const client = useQueryClient();
  const scope = useMemo(() => scopeKey(session), [session]);
  const key = [...scope, "run", runId];
  const [connection, setConnection] = useState("connecting");
  const [actionError, setActionError] = useState<unknown>();
  const [cancelling, setCancelling] = useState(false);
  const lastSequence = useRef(0);
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      request("/api/v1/runs/" + runId, runSchema, { signal }),
    refetchInterval: (current) =>
      current.state.data && terminalStates.has(current.state.data.state)
        ? false
        : 4000,
  });
  const terminal = !!query.data && terminalStates.has(query.data.state);
  useEffect(() => {
    if (terminal) return;
    const stream = new EventSource(
      "/api/v1/runs/" + encodeURIComponent(runId) + "/events",
    );
    stream.onopen = () => setConnection("live");
    stream.onerror = () => setConnection("polling");
    const receive = (event: MessageEvent<string>) => {
      try {
        const parsed = streamEventSchema.parse(JSON.parse(event.data));
        if (parsed.type === "resync_required") {
          stream.close();
          setConnection("polling");
          void client.invalidateQueries({
            queryKey: [...scope, "run", runId],
          });
          return;
        }
        if (parsed.seq <= lastSequence.current) return;
        lastSequence.current = parsed.seq;
        void client.invalidateQueries({
          queryKey: [...scope, "run", runId],
        });
      } catch {
        stream.close();
        setConnection("polling");
      }
    };
    for (const eventName of [
      "progress",
      "snapshot",
      "terminal",
      "resync_required",
    ])
      stream.addEventListener(eventName, receive as EventListener);
    return () => stream.close();
  }, [client, runId, scope, terminal]);
  useEffect(() => {
    if (terminal) {
      void client.invalidateQueries({
        predicate: (entry) =>
          entry.queryKey.includes(incidentId) ||
          entry.queryKey.includes("dossier"),
      });
    }
  }, [client, incidentId, terminal]);
  if (query.isPending) return <Loading>Consultando a investigação…</Loading>;
  if (query.isError)
    return (
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
    );
  const run = query.data;
  return (
    <section className="run-panel" aria-label="Execução da investigação">
      <div className="run-heading">
        <div>
          <span className="section-kicker">INVESTIGAÇÃO SELECIONADA</span>
          <h3 style={{ marginTop: 6 }}>
            <Status value={run.state} />
            {run.outcome && (
              <span style={{ marginLeft: 12, fontSize: 12 }}>
                {label(run.outcome)}
              </span>
            )}
          </h3>
        </div>
        <div className="button-row">
          {run.state === "succeeded" && run.dossier_id && (
            <Button
              size="small"
              onClick={() => onResult(run.dossier_id!, run.revision_id)}
            >
              Conferir rascunho
              <ArrowRight size={14} />
            </Button>
          )}
          {!terminal && (
            <Button
              size="small"
              disabled={cancelling || run.cancel_requested}
              onClick={async () => {
                setCancelling(true);
                setActionError(undefined);
                try {
                  const next = await request(
                    "/api/v1/runs/" + run.id + "/cancel",
                    runSchema,
                    { method: "POST", csrf: session.csrf_token },
                  );
                  client.setQueryData(key, next);
                } catch (error) {
                  setActionError(error);
                } finally {
                  setCancelling(false);
                }
              }}
            >
              <Square size={12} />
              {run.cancel_requested
                ? "Cancelamento solicitado"
                : "Cancelar execução"}
            </Button>
          )}
        </div>
      </div>
      <div className="run-details" role="status">
        {run.cancel_requested && !terminal
          ? "O cancelamento foi solicitado. A conclusão ainda precisa ser confirmada pelo servidor."
          : label(run.stage)}
        {!terminal && (
          <span>
            {" "}
            ·{" "}
            {connection === "live"
              ? "Conexão de eventos ativa"
              : "Atualização por consulta periódica"}
          </span>
        )}
      </div>
      {run.steps.length > 0 && (
        <ol className="run-steps">
          {run.steps.map((step) => (
            <li key={step.key} data-state={step.status}>
              {["succeeded", "completed"].includes(step.status) ? (
                <Check size={12} />
              ) : (
                <Circle size={9} />
              )}
              {label(step.key)}
            </li>
          ))}
        </ol>
      )}
      {run.error && (
        <div className="notice notice-danger">
          <p>
            {run.error.message} A revisão aprovada anterior, se houver, não
            representa sucesso desta tentativa.
          </p>
        </div>
      )}
      {actionError !== undefined && <ErrorNotice error={actionError} />}
      <details className="rule-detail">
        <summary>Identidade, horários e uso</summary>
        <p>
          <code>{run.id}</code>
        </p>
        <p>
          Início: {timestamp(run.started_at)} · fim:{" "}
          {timestamp(run.completed_at)}
        </p>
        <p>
          Uso {label(run.usage.status).toLowerCase()}: entrada{" "}
          {run.usage.input_tokens === null
            ? "não informada"
            : number(run.usage.input_tokens)}{" "}
          · saída{" "}
          {run.usage.output_tokens === null
            ? "não informada"
            : number(run.usage.output_tokens)}{" "}
          tokens.
        </p>
      </details>
    </section>
  );
}
