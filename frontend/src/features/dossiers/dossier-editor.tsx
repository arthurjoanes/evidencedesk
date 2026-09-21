"use client";
import { useEffect, useState } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { editorSchema, type Draft } from "./dossier-draft";
import { Plus, Trash2 } from "lucide-react";
import {
  dossierSchema,
  evidenceSummarySchema,
  outcomeSchema,
  pageSchema,
  revisionSchema,
  type Revision,
  type ClaimInput,
} from "@/lib/contracts";
import { ApiError, queryString, request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { validationMessages } from "@/lib/form-errors";
import { label } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import {
  ErrorNotice,
  FieldError,
  Loading,
  Pagination,
} from "@/components/feedback";

export function DossierEditor({
  accessError,
  retryAccess,
  checkingAccess,
  incidentId,
  snapshotId,
  dossierId,
  base,
  onClose,
  onSaved,
}: {
  accessError?: unknown;
  retryAccess: () => void;
  checkingAccess: boolean;
  incidentId: string;
  snapshotId: string;
  dossierId?: string;
  base?: Revision;
  onClose: () => void;
  onSaved: (dossierId?: string, revisionId?: string) => void;
}) {
  const session = useSession();
  const [error, setError] = useState<unknown>();
  const [comparison, setComparison] = useState(false);
  const [sourceSearch, setSourceSearch] = useState("");
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const form = useForm<Draft>({
    resolver: zodResolver(editorSchema),
    defaultValues: {
      summary: base?.summary ?? "",
      outcome: base?.outcome ?? "insufficient_evidence",
      missing_information: base?.missing_information ?? [],
      suggested_checks: base?.suggested_checks ?? [],
      claims:
        base?.claims.map((claim) => ({
          ...claim,
          support_status: "pending_review" as const,
        })) ?? [],
    },
  });
  useEffect(() => {
    if (!form.formState.isDirty) return;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [form.formState.isDirty]);
  const fields = useFieldArray({ control: form.control, name: "claims" });
  const claims = useWatch({ control: form.control, name: "claims" });
  const summary = useWatch({ control: form.control, name: "summary" });
  const missing = useWatch({
    control: form.control,
    name: "missing_information",
  });
  const checks = useWatch({ control: form.control, name: "suggested_checks" });
  function requestClose() {
    if (
      !form.formState.isDirty ||
      window.confirm("Descartar este rascunho não salvo?")
    )
      onClose();
  }
  const sources = useQuery({
    enabled: fields.fields.length > 0,
    gcTime: 0,
    staleTime: 0,
    queryKey: [
      ...scopeKey(session),
      "editor-sources",
      incidentId,
      snapshotId,
      sourceSearch,
      cursors.at(-1),
    ],
    queryFn: ({ signal }) =>
      request(
        "/api/v1/incidents/" +
          incidentId +
          "/evidence" +
          queryString({
            evidence_snapshot_id: snapshotId,
            q: sourceSearch,
            cursor: cursors.at(-1),
            limit: 15,
          }),
        pageSchema(evidenceSummarySchema),
        { signal },
      ),
  });
  const save = form.handleSubmit(async (draft) => {
    const clean = (items: string[]) =>
      items.map((item) => item.trim()).filter(Boolean);
    const values = {
      ...draft,
      missing_information: clean(draft.missing_information),
      suggested_checks: clean(draft.suggested_checks),
      claims: draft.claims.map((claim) => ({
        ...claim,
        order_references: clean(claim.order_references),
        missing_information: clean(claim.missing_information),
        suggested_checks: clean(claim.suggested_checks),
      })),
    };
    setError(undefined);
    try {
      if (dossierId && base) {
        const revision = await request(
          "/api/v1/dossiers/" + dossierId + "/revisions",
          revisionSchema,
          {
            method: "POST",
            csrf: session.csrf_token,
            headers: { "If-Match": base.etag },
            body: { ...values, base_revision_id: base.id },
          },
        );
        onSaved(dossierId, revision.id);
      } else {
        const dossier = await request(
          "/api/v1/incidents/" + incidentId + "/dossiers",
          dossierSchema,
          {
            method: "POST",
            csrf: session.csrf_token,
            body: { ...values, evidence_snapshot_id: snapshotId },
          },
        );
        onSaved(dossier.id, dossier.current_revision_id);
      }
      onClose();
    } catch (failure) {
      setError(failure);
    }
  });
  function toggleEvidence(index: number, evidenceId: string, checked: boolean) {
    const current = form.getValues(`claims.${index}.evidence_links` as const);
    form.setValue(
      `claims.${index}.evidence_links` as const,
      checked
        ? [...current, { evidence_id: evidenceId, relation: "supports" }]
        : current.filter((link) => link.evidence_id !== evidenceId),
      { shouldDirty: true, shouldValidate: true },
    );
  }
  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next && !form.formState.isSubmitting) requestClose();
      }}
      title={base ? "Preparar uma nova revisão" : "Registrar dossiê manual"}
      description={
        base
          ? "O texto original permanece preservado. Salvar cria uma revisão nova, sem aprovação automática."
          : "Registre o que foi observado, suas fontes e o que continua sem resposta."
      }
      wide
    >
      {accessError !== undefined && (
        <ErrorNotice error={accessError} retry={retryAccess} />
      )}
      {checkingAccess && accessError === undefined && (
        <Loading>
          Conferindo acesso… Seu rascunho permanece nesta janela.
        </Loading>
      )}
      <form
        hidden={checkingAccess}
        onSubmit={save}
        className="form-stack"
        noValidate
      >
        <fieldset
          className="form-stack form-fields"
          disabled={form.formState.isSubmitting}
        >
          <label className="field">
            Resumo da investigação
            <textarea
              rows={4}
              {...form.register("summary")}
              aria-label="Resumo da investigação"
              aria-invalid={!!form.formState.errors.summary}
              aria-describedby={
                form.formState.errors.summary
                  ? "dossier-summary-error"
                  : undefined
              }
            />
            <FieldError
              id="dossier-summary-error"
              message={form.formState.errors.summary?.message}
            />
          </label>
          <label className="field">
            Resultado do recorte
            <select
              {...form.register("outcome")}
              aria-label="Resultado do recorte"
              aria-invalid={!!form.formState.errors.outcome}
              aria-describedby={
                form.formState.errors.outcome
                  ? "dossier-outcome-error"
                  : undefined
              }
            >
              {outcomeSchema.options.map((option) => (
                <option value={option} key={option}>
                  {label(option)}
                </option>
              ))}
            </select>
            <FieldError
              id="dossier-outcome-error"
              message={form.formState.errors.outcome?.message}
            />
          </label>
          <label className="field">
            Lacunas do recorte (uma por linha)
            <textarea
              rows={2}
              value={missing.join("\n")}
              onChange={(event) =>
                form.setValue(
                  "missing_information",
                  event.target.value.split("\n"),
                  { shouldDirty: true },
                )
              }
            />
          </label>
          <label className="field">
            Próximas verificações do recorte (uma por linha)
            <textarea
              rows={2}
              value={checks.join("\n")}
              onChange={(event) =>
                form.setValue(
                  "suggested_checks",
                  event.target.value.split("\n"),
                  { shouldDirty: true },
                )
              }
            />
          </label>
          <div className="subheading">
            <h3>Alegações e fontes</h3>
            <Button
              size="small"
              disabled={fields.fields.length >= 30}
              onClick={() =>
                fields.append({
                  kind: "observed_fact",
                  text: "",
                  order_references: [],
                  evidence_links: [],
                  support_status: "pending_review",
                  missing_information: [],
                  suggested_checks: [],
                })
              }
            >
              <Plus size={14} />
              Adicionar alegação
            </Button>
          </div>
          <p className="muted">
            Sem evidência suficiente, mantenha zero alegações e descreva as
            lacunas no resumo. Suporte permanece pendente de revisão.
          </p>
          {fields.fields.length > 0 && (
            <label className="field">
              Localizar fontes para vincular
              <input
                value={sourceSearch}
                onChange={(event) => {
                  setSourceSearch(event.target.value);
                  setCursors([null]);
                }}
                placeholder="Filtrar título ou trecho"
              />
            </label>
          )}
          {fields.fields.length > 0 && sources.isPending && (
            <Loading>Carregando fontes…</Loading>
          )}
          {sources.isError && <ErrorNotice error={sources.error} />}
          <FieldError message={form.formState.errors.claims?.message} />
          {fields.fields.map((field, index) => (
            <fieldset key={field.id} className="editor-claim">
              <legend className="sr-only">Alegação {index + 1}</legend>
              <div className="editor-claim-header">
                <strong>Alegação {index + 1}</strong>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => fields.remove(index)}
                  aria-label={"Remover alegação " + (index + 1)}
                >
                  <Trash2 size={15} />
                </Button>
              </div>
              <div className="form-stack">
                <label className="field">
                  Tipo
                  <select {...form.register(`claims.${index}.kind` as const)}>
                    <option value="observed_fact">Fato observado</option>
                    <option value="hypothesis">Hipótese</option>
                  </select>
                </label>
                <label className="field">
                  Texto
                  <textarea
                    {...form.register(`claims.${index}.text` as const)}
                    aria-label="Texto"
                    aria-invalid={!!form.formState.errors.claims?.[index]?.text}
                    aria-describedby={
                      form.formState.errors.claims?.[index]?.text
                        ? field.id + "-text-error"
                        : undefined
                    }
                  />
                  <FieldError
                    id={field.id + "-text-error"}
                    message={
                      form.formState.errors.claims?.[index]?.text?.message
                    }
                  />
                </label>
                <label className="field">
                  Pedidos relacionados (separados por vírgula)
                  <input
                    value={claims[index]?.order_references.join(",") ?? ""}
                    onChange={(event) =>
                      form.setValue(
                        `claims.${index}.order_references` as const,
                        event.target.value.split(","),
                        { shouldDirty: true },
                      )
                    }
                  />
                </label>
                <div>
                  <strong style={{ fontSize: 12 }}>
                    Fontes vinculadas:{" "}
                    {claims[index]?.evidence_links.length ?? 0}
                  </strong>
                  <div className="evidence-picker">
                    {(!sources.isError && !sources.isFetching
                      ? sources.data?.items
                      : []
                    )?.map((source) => {
                      const selected = claims[index]?.evidence_links.find(
                        (link) => link.evidence_id === source.id,
                      );
                      return (
                        <div key={source.id} className="evidence-choice">
                          <input
                            type="checkbox"
                            id={field.id + source.id}
                            checked={!!selected}
                            onChange={(event) =>
                              toggleEvidence(
                                index,
                                source.id,
                                event.target.checked,
                              )
                            }
                          />
                          <label
                            htmlFor={field.id + source.id}
                            style={{ flex: 1 }}
                          >
                            {source.title}
                            <small
                              className="muted"
                              style={{ display: "block" }}
                            >
                              {label(source.kind)} · {source.source_system}
                            </small>
                          </label>
                          {selected && (
                            <select
                              aria-label={"Relação da fonte " + source.title}
                              value={selected.relation}
                              onChange={(event) => {
                                const relation = event.target
                                  .value as ClaimInput["evidence_links"][number]["relation"];
                                form.setValue(
                                  `claims.${index}.evidence_links` as const,
                                  claims[index].evidence_links.map((link) =>
                                    link.evidence_id === source.id
                                      ? { ...link, relation }
                                      : link,
                                  ),
                                  { shouldDirty: true },
                                );
                              }}
                            >
                              <option value="supports">Apoia</option>
                              <option value="contradicts">Contradiz</option>
                              <option value="context">Contextualiza</option>
                            </select>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  <div className="source-links">
                    {claims[index]?.evidence_links
                      .filter(
                        (link) =>
                          !sources.data?.items.some(
                            (source) => source.id === link.evidence_id,
                          ),
                      )
                      .map((link) => (
                        <div className="linked-source" key={link.evidence_id}>
                          <span>
                            Fonte de outra página ·{" "}
                            <code>{link.evidence_id}</code>
                          </span>
                          <select
                            aria-label={"Relação da fonte " + link.evidence_id}
                            value={link.relation}
                            onChange={(event) =>
                              form.setValue(
                                `claims.${index}.evidence_links`,
                                claims[index].evidence_links.map((item) =>
                                  item.evidence_id === link.evidence_id
                                    ? {
                                        ...item,
                                        relation: event.target
                                          .value as ClaimInput["evidence_links"][number]["relation"],
                                      }
                                    : item,
                                ),
                                { shouldDirty: true },
                              )
                            }
                          >
                            <option value="supports">Apoia</option>
                            <option value="contradicts">Contradiz</option>
                            <option value="context">Contextualiza</option>
                          </select>
                          <Button
                            size="small"
                            onClick={() =>
                              toggleEvidence(index, link.evidence_id, false)
                            }
                          >
                            Remover vínculo
                          </Button>
                        </div>
                      ))}
                  </div>
                  <FieldError
                    message={
                      form.formState.errors.claims?.[index]?.evidence_links
                        ?.message
                    }
                  />
                </div>
                <label className="field">
                  Informação que falta (uma por linha)
                  <textarea
                    rows={2}
                    value={claims[index]?.missing_information.join("\n") ?? ""}
                    onChange={(event) =>
                      form.setValue(
                        `claims.${index}.missing_information` as const,
                        event.target.value.split("\n"),
                        { shouldDirty: true },
                      )
                    }
                  />
                </label>
                <label className="field">
                  Próximas verificações (uma por linha)
                  <textarea
                    rows={2}
                    value={claims[index]?.suggested_checks.join("\n") ?? ""}
                    onChange={(event) =>
                      form.setValue(
                        `claims.${index}.suggested_checks` as const,
                        event.target.value.split("\n"),
                        { shouldDirty: true },
                      )
                    }
                  />
                </label>
              </div>
            </fieldset>
          ))}
          {fields.fields.length > 0 &&
            sources.data &&
            !sources.isError &&
            !sources.isFetching && (
              <Pagination
                total={sources.data.total}
                count={sources.data.items.length}
                page={cursors.length - 1}
                canNext={!!sources.data.next_cursor}
                onPrevious={() =>
                  setCursors((previous) => previous.slice(0, -1))
                }
                onNext={() =>
                  setCursors((previous) => [
                    ...previous,
                    sources.data.next_cursor,
                  ])
                }
              />
            )}
          {base && (
            <>
              <Button onClick={() => setComparison((value) => !value)}>
                {comparison
                  ? "Recolher comparação"
                  : "Comparar com a revisão " + base.number}
              </Button>
              {comparison && (
                <div className="review-diff">
                  <section>
                    <h4>Revisão {base.number}</h4>
                    <p>{base.summary}</p>
                    {base.claims.map((claim) => (
                      <p key={claim.claim_id} style={{ marginTop: 12 }}>
                        {claim.text}
                      </p>
                    ))}
                  </section>
                  <section>
                    <h4>Seu rascunho</h4>
                    <p>{summary}</p>
                    {claims.map((claim, index) => (
                      <p
                        key={fields.fields[index]?.id}
                        style={{ marginTop: 12 }}
                      >
                        {claim.text}
                      </p>
                    ))}
                  </section>
                </div>
              )}
            </>
          )}
          {error !== undefined && (
            <>
              <ErrorNotice error={error} />
              {error instanceof ApiError && error.status === 409 && (
                <p className="notice notice-warning">
                  A revisão-base mudou. Seu texto foi preservado. Copie ou
                  compare seu rascunho antes de fechar e recarregar a revisão
                  mais recente.
                </p>
              )}
            </>
          )}
          {validationMessages(form.formState.errors).length > 0 && (
            <div className="notice notice-danger" role="alert">
              <div>
                <strong>Confira os campos antes de salvar</strong>
                <ul>
                  {validationMessages(form.formState.errors).map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          <div className="form-actions">
            <Button
              disabled={form.formState.isSubmitting}
              onClick={requestClose}
            >
              Voltar
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={form.formState.isSubmitting}
            >
              {form.formState.isSubmitting
                ? "Salvando…"
                : base
                  ? "Salvar nova revisão"
                  : "Salvar dossiê manual"}
            </Button>
          </div>
        </fieldset>
      </form>
    </Dialog>
  );
}
