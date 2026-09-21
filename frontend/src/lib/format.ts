const numberFormat = new Intl.NumberFormat("pt-BR");
const timeFormat = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeStyle: "short",
  timeZone: "America/Sao_Paulo",
});
export function number(value: number) {
  return numberFormat.format(value);
}
export function timestamp(value: string | null | undefined) {
  if (!value) return "Não informado";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Horário inválido"
    : timeFormat.format(date);
}
const preciseTimeFormat = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeStyle: "medium",
  timeZone: "America/Sao_Paulo",
});
export function eventTimestamp(value: string | null | undefined) {
  if (!value) return "Não informado";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Horário inválido";
  // Keep only precision supplied by the source; never invent fractional digits.
  const fraction = value.match(/T\d{2}:\d{2}:\d{2}(\.\d+)/)?.[1] ?? "";
  return preciseTimeFormat.format(date) + fraction;
}
export function bytes(value: number) {
  return value < 1024
    ? value + " B"
    : value < 1024 * 1024
      ? number(Math.round(value / 1024)) + " KiB"
      : numberFormat.format(value / 1024 / 1024) + " MiB";
}
export const labels: Record<string, string> = {
  open: "Em investigação",
  in_review: "Aguardando revisão",
  resolved: "Resolvido",
  queued: "Na fila",
  running: "Em execução",
  retry_wait: "Aguardando nova tentativa",
  succeeded: "Concluído",
  failed: "Falhou",
  cancelled: "Cancelado",
  draft: "Rascunho",
  submitted: "Enviado para revisão",
  approved: "Aprovado",
  changes_requested: "Ajustes solicitados",
  evidence_found: "Evidências encontradas",
  conflicting_evidence: "Evidências conflitantes",
  insufficient_evidence: "Evidência insuficiente",
  unsupported_scope: "Fora do escopo",
  receiving: "Recebendo arquivos",
  sealed: "Arquivos conferidos",
  processing: "Processando",
  ready: "Publicado",
  rejected: "Rejeitado",
  uploaded: "Enviado",
  pending: "Pendente",
  valid: "Válido",
  uploading: "Enviando",
  document: "Documento",
  events: "Eventos",
  snapshots: "Snapshots de pedidos",
  mappings: "Mapeamentos",
  complete: "Completa",
  partial: "Parcial",
  missing: "Ausente",
  unknown: "Desconhecido",
  divergence: "Divergência",
  observation: "Observação",
  not_evaluable: "Não avaliável",
  document_span: "Documento",
  source_event: "Evento",
  delivery_attempt: "Entrega",
  order_snapshot: "Snapshot do pedido",
  reconciliation_result: "Conciliação",
  applicable_procedure: "Procedimento aplicável",
  historical_artifact: "Artefato histórico",
  retrospective_context: "Contexto retrospectivo",
  observed_fact: "Fato observado",
  hypothesis: "Hipótese",
  supports: "Apoia",
  contradicts: "Contradiz",
  context: "Contextualiza",
  pending_review: "Suporte não revisado",
  contested: "Suporte contestado",
  reviewed: "Suporte revisado",
  analyst: "Analista",
  reviewer: "Revisor",
  tenant_admin: "Administrador",
  ai: "Gerado por IA",
  manual: "Elaboração manual",
  reported: "Reportado",
  estimated: "Estimado",
  reserved: "Reservado",
  reconciliation: "Conciliação dos registros",
  planning: "Planejamento da investigação",
  retrieval: "Busca de evidências",
  generation: "Elaboração do rascunho",
  validation: "Validação do resultado",
  indexing: "Preparação do índice",
  publication: "Publicação do resultado",
};
export function label(value: string | null | undefined) {
  return value
    ? (labels[value] ?? value.replaceAll("_", " "))
    : "Não informado";
}
export function tone(value: string) {
  return ["failed", "rejected", "changes_requested", "contested"].includes(
    value,
  )
    ? "danger"
    : ["approved", "resolved", "ready", "succeeded", "valid"].includes(value)
      ? "success"
      : [
            "divergence",
            "partial",
            "conflicting_evidence",
            "insufficient_evidence",
            "retry_wait",
          ].includes(value)
        ? "warning"
        : "neutral";
}
