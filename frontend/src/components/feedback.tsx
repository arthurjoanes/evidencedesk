import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  SearchX,
} from "lucide-react";
import { ApiError, errorMessage } from "@/lib/http";
import { label, number, tone } from "@/lib/format";
import { Button } from "./ui/button";
import type { ReactNode } from "react";

export function Status({ value }: { value: string }) {
  return (
    <span className={"status status-" + tone(value)}>
      <span className="status-dot" />
      {label(value)}
    </span>
  );
}
export function Loading({
  children = "Carregando…",
}: {
  children?: ReactNode;
}) {
  return (
    <div className="loading" role="status">
      <LoaderCircle size={18} className="spinner" />
      {children}
    </div>
  );
}
export function ErrorNotice({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  return (
    <div className="notice notice-danger" role="alert">
      <AlertCircle size={19} />
      <div>
        <strong>
          {error instanceof ApiError && error.status === 403
            ? "Acesso indisponível"
            : "A operação não foi concluída"}
        </strong>
        <p>{errorMessage(error)}</p>
        {error instanceof ApiError && error.requestId && (
          <small>
            Referência: <code>{error.requestId}</code>
          </small>
        )}
        {retry && (
          <Button size="small" onClick={retry}>
            Tentar novamente
          </Button>
        )}
      </div>
    </div>
  );
}
export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <SearchX size={30} strokeWidth={1.4} />
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
export function Pagination({
  total,
  count,
  page,
  canNext,
  busy,
  onPrevious,
  onNext,
}: {
  total: number | null;
  count: number;
  page: number;
  canNext: boolean;
  busy?: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  return (
    <div className="pagination">
      <p>
        <strong>{number(count)}</strong> nesta página
        {total !== null && (
          <>
            {" "}
            · <strong>{number(total)}</strong> no recorte
          </>
        )}
      </p>
      <div className="button-row">
        <Button size="small" onClick={onPrevious} disabled={page === 0 || busy}>
          <ChevronLeft size={15} />
          Anterior
        </Button>
        <span>Página {page + 1}</span>
        <Button size="small" onClick={onNext} disabled={!canNext || busy}>
          Próxima
          <ChevronRight size={15} />
        </Button>
      </div>
    </div>
  );
}
export function FieldError({ message, id }: { message?: string; id?: string }) {
  return message ? (
    <span id={id} className="field-error" role="alert">
      {message}
    </span>
  ) : null;
}
