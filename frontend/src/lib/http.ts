import { z } from "zod";
import { apiErrorSchema } from "./contracts";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId?: string,
    public fields?: Record<string, string[]>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  csrf?: string;
  rawBody?: BodyInit;
};

export function apiUrl(path: string) {
  let parsed: URL;
  try {
    parsed = new URL(path, "https://evidencedesk.invalid");
  } catch {
    throw new Error("Caminho da API inválido.");
  }
  const decoded = decodeURIComponent(path.split("?")[0]);
  if (
    !path.startsWith("/api/v1/") ||
    parsed.origin !== "https://evidencedesk.invalid" ||
    !parsed.pathname.startsWith("/api/v1/") ||
    decoded.includes("\\") ||
    decoded.split("/").some((segment) => segment === "." || segment === "..")
  )
    throw new Error("Caminho da API inválido.");
  return path;
}

export async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  options: RequestOptions = {},
): Promise<T> {
  const { body, csrf, rawBody, ...init } = options;
  const headers = new Headers(init.headers);
  if (body !== undefined) headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const response = await fetch(apiUrl(path), {
    ...init,
    headers,
    body: rawBody ?? (body === undefined ? undefined : JSON.stringify(body)),
    credentials: "same-origin",
    cache: "no-store",
  });
  const payload: unknown =
    response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const parsed = apiErrorSchema.safeParse(payload);
    const detail = parsed.success ? parsed.data.error : null;
    if (
      response.status === 401 &&
      typeof window !== "undefined" &&
      !path.startsWith("/api/v1/auth/")
    )
      window.dispatchEvent(new Event("ed:session-expired"));
    throw new ApiError(
      response.status,
      detail?.code ?? "http_error",
      detail?.message ?? "Não foi possível completar esta operação.",
      detail?.request_id,
      detail?.field_errors,
    );
  }
  const parsed = schema.safeParse(payload);
  if (!parsed.success)
    throw new ApiError(
      502,
      "invalid_response",
      "A resposta recebida não corresponde ao contrato. Atualize a página; se persistir, informe a operação ao suporte.",
    );
  return parsed.data;
}

export function queryString(
  values: Record<string, string | number | null | undefined>,
) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value !== undefined && value !== null && value !== "")
      params.set(key, String(value));
  return params.size ? "?" + params.toString() : "";
}

export function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  if (error instanceof TypeError)
    return "A conexão foi interrompida. Confira a rede e tente novamente.";
  return "Não foi possível concluir. Tente novamente.";
}
