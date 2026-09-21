"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { collectionSchema, incidentSchema, pageSchema } from "@/lib/contracts";
import { request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ErrorNotice, FieldError, Loading } from "@/components/feedback";

const schema = z
  .object({
    title: z
      .string()
      .trim()
      .min(5, "Descreva o incidente em pelo menos 5 caracteres.")
      .max(160, "Use no máximo 160 caracteres no título."),
    collection_id: z.string().min(1, "Escolha uma coleção."),
    from: z.string().min(1, "Informe o início."),
    to: z.string().min(1, "Informe o fim."),
    description: z
      .string()
      .max(3000, "Use no máximo 3.000 caracteres no contexto."),
  })
  .refine((values) => values.from < values.to, {
    path: ["to"],
    message: "O fim deve ser posterior ao início.",
  });
export function CreateIncident({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const session = useSession();
  const router = useRouter();
  const [error, setError] = useState<unknown>();
  const collections = useQuery({
    queryKey: [...scopeKey(session), "collections"],
    queryFn: ({ signal }) =>
      request("/api/v1/collections?limit=100", pageSchema(collectionSchema), {
        signal,
      }),
    enabled: open,
  });
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: "",
      collection_id: "",
      from: "",
      to: "",
      description: "",
    },
  });
  const submit = form.handleSubmit(async ({ from, to, ...values }) => {
    setError(undefined);
    try {
      const incident = await request("/api/v1/incidents", incidentSchema, {
        method: "POST",
        csrf: session.csrf_token,
        body: {
          ...values,
          window: {
            from: new Date(from + "Z").toISOString(),
            to: new Date(to + "Z").toISOString(),
            time_zone: "UTC",
          },
        },
      });
      onClose();
      router.push("/incidents/" + incident.id);
    } catch (failure) {
      setError(failure);
    }
  });
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !form.formState.isSubmitting) onClose();
      }}
      title="Abrir incidente"
      description="Defina a coleção e a janela a investigar. O snapshot disponível será fixado pelo servidor."
    >
      <form onSubmit={submit} className="form-stack" noValidate>
        <label className="field">
          Título
          <input
            {...form.register("title")}
            placeholder="Ex.: pagamentos confirmados com pedidos pendentes"
          />
          <FieldError message={form.formState.errors.title?.message} />
        </label>
        <label className="field">
          Coleção
          <select {...form.register("collection_id")}>
            <option value="">Selecione uma coleção publicada</option>
            {collections.data?.items.map((collection) => (
              <option
                key={collection.id}
                value={collection.id}
                disabled={!collection.active_snapshot_id}
              >
                {collection.name}
                {!collection.active_snapshot_id ? " — sem publicação" : ""}
              </option>
            ))}
          </select>
          <FieldError message={form.formState.errors.collection_id?.message} />
        </label>
        {collections.isPending && <Loading>Carregando coleções…</Loading>}
        {collections.isError && <ErrorNotice error={collections.error} />}
        <div className="form-grid">
          <label className="field">
            Início (UTC)
            <input type="datetime-local" {...form.register("from")} />
            <FieldError message={form.formState.errors.from?.message} />
          </label>
          <label className="field">
            Fim (UTC)
            <input type="datetime-local" {...form.register("to")} />
            <FieldError message={form.formState.errors.to?.message} />
          </label>
        </div>
        <label className="field">
          Contexto para a equipe
          <textarea
            {...form.register("description")}
            placeholder="O que foi observado e o que precisa ser conferido?"
          />
        </label>
        <FieldError message={form.formState.errors.description?.message} />
        {error !== undefined && <ErrorNotice error={error} />}
        <div className="form-actions">
          <Button disabled={form.formState.isSubmitting} onClick={onClose}>
            Voltar
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={form.formState.isSubmitting}
          >
            {form.formState.isSubmitting ? "Abrindo…" : "Abrir incidente"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
