"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { importSchema } from "@/lib/contracts";
import { request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { bytes, label, timestamp, number } from "@/lib/format";
import { ErrorNotice, Loading, Status } from "@/components/feedback";
import { summarizeEntries } from "./import-summary";
export function ImportDetail({ id }: { id: string }) {
  const session = useSession();
  const query = useQuery({
    queryKey: [...scopeKey(session), "import", id],
    queryFn: ({ signal }) =>
      request("/api/v1/imports/" + encodeURIComponent(id), importSchema, {
        signal,
      }),
    refetchInterval: (query) =>
      ["sealed", "processing"].includes(query.state.data?.state ?? "")
        ? 2500
        : false,
  });
  if (query.isPending) return <Loading>Consultando o pacote…</Loading>;
  if (query.isError)
    return (
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
    );
  const batch = query.data;
  const summary = summarizeEntries(batch.entries);
  return (
    <>
      <Link className="back-link" href="/imports">
        <ArrowLeft size={14} />
        Importações
      </Link>
      <div className="page-heading">
        <div>
          <h1>{batch.title}</h1>
          <div className="page-title-meta">
            <Status value={batch.state} />
            <span>{timestamp(batch.created_at)}</span>
          </div>
        </div>
      </div>
      <p className="import-collection">
        Coleção de destino: <code>{batch.collection_id}</code>
      </p>
      <dl className="import-summary" aria-label="Resumo dos arquivos">
        <div>
          <dt>Total</dt>
          <dd>{number(summary.total)}</dd>
        </div>
        <div>
          <dt>Válidos</dt>
          <dd>{number(summary.valid)}</dd>
        </div>
        <div>
          <dt>Aguardando validação</dt>
          <dd>{number(summary.pending)}</dd>
        </div>
        <div>
          <dt>Com erro</dt>
          <dd>{number(summary.failed)}</dd>
        </div>
        {summary.unknown > 0 && (
          <div>
            <dt>Estado não reconhecido</dt>
            <dd>{number(summary.unknown)}</dd>
          </div>
        )}
      </dl>
      {batch.state === "ready" ? (
        <div className="notice notice-info" style={{ marginBottom: 24 }}>
          <div>
            <strong>Pacote publicado por inteiro</strong>
            <p>
              As fontes estão disponíveis na coleção. Abra um incidente no
              período relevante para consultá-las.
            </p>
            <Link href="/" className="button button-secondary button-small">
              Ir para incidentes
            </Link>
          </div>
        </div>
      ) : (
        <p className="notice notice-warning" style={{ marginBottom: 24 }}>
          Este pacote ainda não está publicado. Nenhum arquivo desta importação
          substitui o snapshot anterior.
        </p>
      )}
      {batch.error && (
        <p
          className="notice notice-danger"
          role="alert"
          style={{ marginBottom: 24 }}
        >
          {batch.error.message}
        </p>
      )}
      <div className="table-panel">
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Validação dos arquivos"
        >
          <table className="import-files-table" style={{ minWidth: 670 }}>
            <thead>
              <tr>
                <th scope="col">Arquivo</th>
                <th scope="col">Tipo</th>
                <th scope="col">Tamanho</th>
                <th scope="col">Validação</th>
              </tr>
            </thead>
            <tbody>
              {batch.entries.map((entry) => (
                <tr key={entry.entry_id}>
                  <td>
                    <strong>{entry.filename}</strong>
                  </td>
                  <td>{label(entry.kind)}</td>
                  <td className="table-nowrap">{bytes(entry.byte_size)}</td>
                  <td>
                    <Status value={entry.state} />
                    {entry.error && (
                      <p className="field-error">{entry.error.message}</p>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <details className="evidence-technical" style={{ marginTop: 20 }}>
        <summary>Integridade declarada · SHA-256 de cada arquivo</summary>
        <p>
          Valores recebidos no manifesto. O estado de validação acima informa o
          resultado do processamento.
        </p>
        <dl>
          {batch.entries.map((entry) => (
            <div key={entry.entry_id}>
              <dt>{entry.filename}</dt>
              <dd>
                <code className="break-anywhere">{entry.sha256}</code>
              </dd>
            </div>
          ))}
        </dl>
      </details>
      <details className="evidence-technical" style={{ marginTop: 12 }}>
        <summary>Identificadores do pacote</summary>
        <dl>
          <dt>Importação</dt>
          <dd>{batch.id}</dd>
          <dt>Coleção</dt>
          <dd>{batch.collection_id}</dd>
          <dt>Snapshot</dt>
          <dd>{batch.evidence_snapshot_id ?? "Ainda não publicado"}</dd>
        </dl>
      </details>
    </>
  );
}
