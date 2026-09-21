"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, FileCheck2 } from "lucide-react";
import { importSchema, type ImportBatch } from "@/lib/contracts";
import { request } from "@/lib/http";
import { useSession } from "@/lib/session";
import { Button } from "@/components/ui/button";
import { ErrorNotice } from "@/components/feedback";
import { CollectionSelect } from "@/features/collections/collection-select";
import {
  PackageValidationError,
  parseManifest,
  verifyFiles,
} from "./import-files";

export function NewImport() {
  const session = useSession();
  const router = useRouter();
  const [manifestFile, setManifestFile] = useState<File>();
  const [files, setFiles] = useState<File[]>([]);
  const [collection, setCollection] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [created, setCreated] = useState<{
    batch: ImportBatch;
    fingerprint: string;
  } | null>(null);
  async function upload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(undefined);
    setBusy(true);
    try {
      if (!manifestFile || !collection)
        throw new PackageValidationError(
          "Selecione a coleção e o manifesto do pacote.",
        );
      if (manifestFile.size > 256 * 1024)
        throw new PackageValidationError("O manifesto ultrapassa 256 KiB.");
      const manifest = parseManifest(await manifestFile.text());
      const matched = await verifyFiles(manifest, files, setProgress);
      const fingerprint = JSON.stringify([collection, manifest]);
      let batch: ImportBatch;
      if (created) {
        if (created.fingerprint !== fingerprint)
          throw new PackageValidationError(
            "O pacote já foi criado. Mantenha seu manifesto e coleção para retomar, ou abra uma nova importação.",
          );
        batch = await request(
          "/api/v1/imports/" + created.batch.id,
          importSchema,
        );
      } else {
        setProgress("Criando a importação…");
        batch = await request("/api/v1/imports", importSchema, {
          method: "POST",
          csrf: session.csrf_token,
          body: { collection_id: collection, manifest },
        });
        setCreated({ batch, fingerprint });
      }
      if (batch.state !== "receiving") {
        router.push("/imports/" + batch.id);
        return;
      }
      for (const entry of manifest.entries) {
        if (
          batch.entries.find((item) => item.entry_id === entry.entry_id)
            ?.state === "uploaded"
        )
          continue;
        setProgress("Enviando " + entry.filename);
        batch = await request(
          "/api/v1/imports/" + batch.id + "/files/" + entry.entry_id,
          importSchema,
          {
            method: "PUT",
            csrf: session.csrf_token,
            headers: { "Content-Type": entry.media_type },
            rawBody: matched.get(entry.entry_id),
          },
        );
        setCreated({ batch, fingerprint });
      }
      setProgress("Solicitando validação do pacote completo…");
      await request("/api/v1/imports/" + batch.id + "/finalize", importSchema, {
        method: "POST",
        csrf: session.csrf_token,
      });
      router.push("/imports/" + batch.id);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
      setProgress("");
    }
  }
  if (!session.permissions.includes("create_import"))
    return (
      <div className="notice notice-warning">
        Seu perfil não permite criar importações.
      </div>
    );
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Importar fontes</h1>
          <p>
            Um pacote define o conjunto e a cobertura. A publicação só acontece
            quando todos os arquivos passam pela validação.
          </p>
        </div>
      </div>
      <div className="import-intro">
        <form className="form-stack" onSubmit={(event) => void upload(event)}>
          <CollectionSelect
            label="Coleção de destino"
            value={collection}
            onChange={(event) => setCollection(event.target.value)}
            required
            disabled={busy || !!created}
          />
          <label className="field file-input">
            1. Manifesto do pacote
            <input
              type="file"
              accept=".json,application/json"
              disabled={busy || !!created}
              required
              onChange={(event) => setManifestFile(event.target.files?.[0])}
            />
            <small className="muted">
              JSON com versões, cobertura, tamanhos e hashes.
            </small>
          </label>
          <label className="field file-input">
            2. Arquivos descritos no manifesto
            <input
              type="file"
              multiple
              disabled={busy}
              required
              onChange={(event) =>
                setFiles(Array.from(event.target.files ?? []))
              }
            />
            <small className="muted">
              Até 40 arquivos, 10 MiB por arquivo e 40 MiB no total.
            </small>
          </label>
          {files.length > 0 && (
            <p className="muted">
              {files.length} arquivos selecionados. O conteúdo ainda não foi
              publicado.
            </p>
          )}
          {busy && (
            <p className="import-progress" role="status">
              {progress}
            </p>
          )}
          {error instanceof PackageValidationError ? (
            <p role="alert" className="notice notice-danger">
              {error.message}
            </p>
          ) : (
            error !== undefined && <ErrorNotice error={error} />
          )}
          {created && (
            <p className="notice notice-info">
              Importação {created.batch.id} preservada. Tentar novamente retoma
              os arquivos pendentes do mesmo pacote.
            </p>
          )}
          <div className="form-actions">
            <Button
              type="submit"
              variant="primary"
              disabled={busy || !collection || !manifestFile || !files.length}
            >
              {busy
                ? "Conferindo e enviando…"
                : created
                  ? "Retomar envio"
                  : "Conferir e enviar"}
              <ArrowRight size={15} />
            </Button>
          </div>
        </form>
        <aside className="import-help">
          <details className="import-example">
            <summary>Como preparar o primeiro pacote</summary>
            <p>
              O manifesto descreve exatamente os arquivos enviados. Baixe os
              dois exemplos abaixo e selecione cada um no campo correspondente.
            </p>
            <p>
              <a href="/examples/manifesto-exemplo.json" download>
                Baixar manifesto JSON
              </a>
            </p>
            <p>
              <a href="/examples/documento-exemplo.md" download>
                Baixar documento de exemplo
              </a>
            </p>
            <p>
              Exemplo sintético, sem eventos ou cobertura operacional. Use uma
              coleção de testes: publicar um pacote define um novo snapshot da
              coleção.
            </p>
            <p>
              Se alterar o documento, atualize seu tamanho em bytes e SHA-256 no
              manifesto. Documentos devem informar origem, versão e papel
              temporal; cobertura só deve descrever intervalos realmente
              conhecidos.
            </p>
          </details>
          <FileCheck2 size={24} />
          <h3 style={{ marginTop: 14 }}>O que será conferido</h3>
          <ol>
            <li>
              Os nomes, tamanhos e hashes precisam coincidir com o manifesto.
            </li>
            <li>Eventos, snapshots e documentos são validados no servidor.</li>
            <li>
              A publicação cria um snapshot imutável e mantém o anterior
              acessível.
            </li>
          </ol>
          <p className="muted">
            Uma falha em qualquer arquivo impede a publicação do pacote. Upload
            concluído ainda não significa fonte pronta para investigar.
          </p>
        </aside>
      </div>
    </>
  );
}
