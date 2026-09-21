"use client";
import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTable, tableFeatures, type ColumnDef } from "@tanstack/react-table";
import { ArrowUpRight, Plus, Search } from "lucide-react";
import { incidentSchema, pageSchema, type Incident } from "@/lib/contracts";
import { request, queryString } from "@/lib/http";
import { useSession, scopeKey } from "@/lib/session";
import { number, timestamp } from "@/lib/format";
import { Button } from "@/components/ui/button";
import {
  EmptyState,
  ErrorNotice,
  Loading,
  Pagination,
  Status,
} from "@/components/feedback";
import { incidentDestination } from "./navigation";
import { CreateIncident } from "./create-incident";

const features = tableFeatures({});
const columns: ColumnDef<typeof features, Incident>[] = [
  {
    id: "incident",
    header: "Incidente",
    cell: ({ row }) => (
      <>
        <IncidentLink className="cell-title" incident={row.original}>
          {row.original.title}
        </IncidentLink>
        <span className="cell-description">{row.original.description}</span>
      </>
    ),
  },
  {
    id: "status",
    header: "Situação",
    cell: ({ row }) => <Status value={row.original.status} />,
  },
  {
    id: "orders",
    header: "Pedidos",
    cell: ({ row }) => (
      <span className="mono">{number(row.original.counts.orders)}</span>
    ),
  },
  {
    id: "divergences",
    header: "Divergências",
    cell: ({ row }) => (
      <span className="mono">{number(row.original.counts.divergences)}</span>
    ),
  },
  {
    id: "updated",
    header: "Atualizado",
    cell: ({ row }) => (
      <span className="table-nowrap">{timestamp(row.original.updated_at)}</span>
    ),
  },
  {
    id: "open",
    header: "",
    cell: ({ row }) => (
      <IncidentLink
        className="button button-ghost button-icon"
        incident={row.original}
        aria-label={"Abrir " + row.original.title}
      >
        <ArrowUpRight size={17} />
      </IncidentLink>
    ),
  },
];

function IncidentLink({
  incident,
  children,
  ...props
}: {
  incident: Incident;
  children: React.ReactNode;
  className: string;
  "aria-label"?: string;
}) {
  const params = useSearchParams();
  return (
    <Link href={incidentDestination(incident.id, params)} {...props}>
      {children}
    </Link>
  );
}
export function IncidentQueue() {
  const params = useSearchParams();
  const router = useRouter();
  const session = useSession();
  const [creating, setCreating] = useState(false);
  const q = params.get("q") ?? "";
  const status = params.get("status") ?? "";
  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    router.replace(
      "/" +
        queryString({
          q: String(data.get("q") ?? ""),
          status: String(data.get("status") ?? ""),
        }),
    );
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Incidentes</h1>
          <p>
            Compare os registros, encontre divergências e acompanhe o que ainda
            precisa de revisão.
          </p>
        </div>
        {session.permissions.includes("create_incident") && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus size={17} />
            Abrir incidente
          </Button>
        )}
      </div>
      <div className="toolbar">
        <form className="filter-form" onSubmit={filter} key={q + status}>
          <label className="search-field">
            <Search size={16} />
            <span className="sr-only">Buscar incidentes</span>
            <input
              className="search-input"
              name="q"
              placeholder="Buscar pelo título do incidente"
              defaultValue={q}
            />
          </label>
          <label>
            <span className="sr-only">Situação do incidente</span>
            <select
              className="filter-select"
              name="status"
              defaultValue={status}
            >
              <option value="">Todas as situações</option>
              <option value="open">Em investigação</option>
              <option value="in_review">Aguardando revisão</option>
              <option value="resolved">Resolvidos</option>
            </select>
          </label>
          <Button type="submit">Aplicar</Button>
          {(q || status) && (
            <Button variant="ghost" onClick={() => router.replace("/")}>
              Limpar
            </Button>
          )}
        </form>
      </div>
      <QueueTable key={q + status} q={q} status={status} />
      <CreateIncident open={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function QueueTable({ q, status }: { q: string; status: string }) {
  const session = useSession();
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const cursor = cursors.at(-1);
  const query = useQuery({
    queryKey: [...scopeKey(session), "incidents", q, status, cursor],
    queryFn: ({ signal }) =>
      request(
        "/api/v1/incidents" + queryString({ q, status, cursor, limit: 30 }),
        pageSchema(incidentSchema),
        { signal },
      ),
  });
  const table = useTable({
    features,
    data: query.data?.items ?? [],
    columns,
    getRowId: (row) => row.id,
  });
  if (query.isPending) return <Loading>Carregando incidentes…</Loading>;
  if (query.isError)
    return (
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
    );
  if (!query.data.items.length)
    return (
      <EmptyState
        title={
          q || status
            ? "Nenhum incidente neste filtro"
            : "A bancada está pronta para o primeiro caso"
        }
        description={
          q || status
            ? "Ajuste os filtros para explorar outro recorte."
            : "Importe uma coleção de evidências e abra um incidente com uma janela definida."
        }
      />
    );
  return (
    <div className="table-panel">
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Tabela de incidentes"
      >
        <table style={{ minWidth: 760 }}>
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => (
                  <th key={header.id} scope="col">
                    <table.FlexRender header={header} />
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getAllCells().map((cell) => (
                  <td key={cell.id}>
                    <table.FlexRender cell={cell} />
                  </td>
                ))}
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
        busy={query.isFetching}
        onPrevious={() => setCursors((previous) => previous.slice(0, -1))}
        onNext={() =>
          setCursors((previous) => [...previous, query.data.next_cursor])
        }
      />
    </div>
  );
}
