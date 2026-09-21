"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { z } from "zod";
import { ApiError, request } from "./http";
import { sessionSchema, type Session } from "./contracts";
import { Login } from "@/features/identity/login";
import { ErrorNotice, Loading } from "@/components/feedback";
import { scopeKey } from "./session-scope";
export { scopeKey } from "./session-scope";
import { SessionSuspensionContext } from "./session-suspension";
import { AppShell } from "@/components/app-shell";

const SessionContext = createContext<Session | null>(null);
export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("Sessão autenticada necessária.");
  return session;
}
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            staleTime: 15_000,
            refetchOnWindowFocus: true,
          },
          mutations: { retry: false },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <SessionGate>{children}</SessionGate>
    </QueryClientProvider>
  );
}
function SessionGate({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: async ({ signal }) => {
      try {
        return await request("/api/v1/auth/session", sessionSchema, { signal });
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 30_000,
  });
  useEffect(() => {
    const expire = () => {
      void client.cancelQueries().then(() => {
        client.removeQueries({
          predicate: (query) => query.queryKey[0] !== "session",
        });
        client.setQueryData(["session"], null);
      });
    };
    window.addEventListener("ed:session-expired", expire);
    return () => window.removeEventListener("ed:session-expired", expire);
  }, [client]);
  useEffect(() => {
    if (session.data !== null) return;
    const protectedQueries = {
      predicate: (query: { queryKey: readonly unknown[] }) =>
        query.queryKey[0] !== "session",
    };
    void client
      .cancelQueries(protectedQueries)
      .then(() => client.removeQueries(protectedQueries));
  }, [client, session.data]);
  if (session.isPending)
    return (
      <div className="boot-screen">
        <Loading>Conferindo sua sessão…</Loading>
      </div>
    );
  if (session.isError && !session.data)
    return (
      <div className="boot-screen">
        <ErrorNotice
          error={session.error}
          retry={() => void session.refetch()}
        />
      </div>
    );
  if (!session.data)
    return (
      <Login
        onAuthenticated={async (next) => {
          await client.cancelQueries();
          client.removeQueries({
            predicate: (query) => query.queryKey[0] !== "session",
          });
          client.setQueryData(["session"], next);
        }}
      />
    );
  const authenticated = session.data;
  const suspended = session.isError || session.isFetching;
  const logout = async () => {
    await request("/api/v1/auth/logout", z.null(), {
      method: "POST",
      csrf: authenticated.csrf_token,
    });
    await client.cancelQueries();
    client.removeQueries({
      predicate: (query) => query.queryKey[0] !== "session",
    });
    client.setQueryData(["session"], null);
  };
  return (
    <>
      {suspended && (
        <div
          className="boot-screen"
          role="region"
          aria-label="Verificação da sessão"
        >
          {session.isError ? (
            <ErrorNotice
              error={session.error}
              retry={() => void session.refetch()}
            />
          ) : (
            <Loading>
              Conferindo sua sessão… O trabalho permanece nesta janela.
            </Loading>
          )}
        </div>
      )}
      <SessionContext.Provider
        key={JSON.stringify(scopeKey(authenticated))}
        value={authenticated}
      >
        <SessionSuspensionContext.Provider value={suspended}>
          <div
            className="authenticated-content"
            hidden={suspended}
            inert={suspended}
          >
            <AppShell session={authenticated} onLogout={logout}>
              {children}
            </AppShell>
          </div>
        </SessionSuspensionContext.Provider>
      </SessionContext.Provider>
    </>
  );
}
