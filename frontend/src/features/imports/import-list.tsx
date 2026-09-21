"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, ArrowUpRight } from "lucide-react";
import { importSchema, pageSchema } from "@/lib/contracts";
import { request, queryString } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { timestamp } from "@/lib/format";
import { Button } from "@/components/ui/button";
import {
  EmptyState,
  ErrorNotice,
  Loading,
  Pagination,
  Status,
} from "@/components/feedback";
export function ImportList() {
  const session = useSession();
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const query = useQuery({
    queryKey: [...scopeKey(session), "imports", cursors.at(-1)],
    queryFn: ({ signal }) =>
      request(
        "/api/v1/imports" + queryString({ cursor: cursors.at(-1) }),
        pageSchema(importSchema),
        { signal },
      ),
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Importações</h1>
          <p>
            Acompanhe a validação de cada pacote e a publicação dos snapshots.
          </p>
        </div>
        {session.permissions.includes("create_import") && (
          <Button asChild variant="primary">
            <Link href="/imports/new">
              <Plus size={16} />
              Importar fontes
            </Link>
          </Button>
        )}
      </div>
      {query.isPending && <Loading>Consultando importações…</Loading>}
      {query.isError && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {query.data &&
        !query.isError &&
        (!query.data.items.length ? (
          <EmptyState
            title="Nenhum pacote importado"
            description="Os pacotes publicados ficam disponíveis nas coleções para abrir um incidente."
          />
        ) : (
          <div className="table-panel">
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Pacotes importados"
            >
              <table style={{ minWidth: 650 }}>
                <thead>
                  <tr>
                    <th scope="col">Pacote</th>
                    <th scope="col">Publicação</th>
                    <th scope="col">Arquivos</th>
                    <th scope="col">Criado em</th>
                    <th scope="col">
                      <span className="sr-only">Detalhes</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.items.map((batch) => (
                    <tr key={batch.id}>
                      <td>
                        <Link
                          className="cell-title"
                          href={"/imports/" + batch.id}
                        >
                          {batch.title}
                        </Link>
                      </td>
                      <td>
                        <Status value={batch.state} />
                      </td>
                      <td>{batch.entries.length}</td>
                      <td className="table-nowrap">
                        {timestamp(batch.created_at)}
                      </td>
                      <td>
                        <Link
                          href={"/imports/" + batch.id}
                          aria-label={"Abrir importação " + batch.title}
                        >
                          <ArrowUpRight size={17} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
          </div>
        ))}
    </>
  );
}
