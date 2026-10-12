"use client";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { dossierSchema, incidentSchema, type Revision } from "@/lib/contracts";
import { ApiError, request } from "@/lib/http";
import { scopeKey, useSession } from "@/lib/session";
import { Dialog } from "@/components/ui/dialog";
import { ErrorNotice, Loading } from "@/components/feedback";
import { DossierEditor } from "./dossier-editor";
import { ReviewDecision } from "./review-decision";

type Intent =
  | {
      kind: "edit";
      incidentId: string;
      snapshotId: string;
      dossierId?: string;
      base?: Revision;
    }
  | {
      kind: "review";
      incidentId: string;
      dossierId: string;
      revision: Revision;
      snapshotId: string;
    };
const DialogContext = createContext<{ open: (intent: Intent) => void } | null>(
  null,
);
export function useDossierDialogs() {
  const context = useContext(DialogContext);
  if (!context)
    throw new Error("Dossier dialogs require the workspace provider.");
  return context;
}

// The host stays outside the responsive panels and background-query loading branches.
// Its captured revision remains the If-Match base; refetching never replaces a draft.
export function DossierDialogs({
  children,
  onSaved,
}: {
  children: ReactNode;
  onSaved: (dossierId: string, revisionId?: string) => void;
}) {
  const [intent, setIntent] = useState<Intent | null>(null);
  const session = useSession();
  const scope = scopeKey(session).join("\u0000");
  const currentScope = useRef(scope);
  const hostMounted = useRef(false);
  const intentOpen = useRef(false);
  const intentSaved = useRef(false);
  const trigger = useRef<{ element: HTMLElement | null; scope: string } | null>(
    null,
  );
  useEffect(() => {
    currentScope.current = scope;
  }, [scope]);
  useEffect(() => {
    hostMounted.current = true;
    return () => {
      hostMounted.current = false;
    };
  }, []);
  const client = useQueryClient();
  function close() {
    intentOpen.current = false;
    setIntent(null);
  }
  function restoreFocus(event: Event) {
    event.preventDefault();
    // Authorization loading and session suspension replace/close a portal,
    // but they do not close the user's intent. Never focus hidden content.
    if (
      !hostMounted.current ||
      intentOpen.current ||
      trigger.current?.scope !== currentScope.current
    )
      return;
    const original = trigger.current?.element;
    const target =
      !intentSaved.current &&
      original?.isConnected &&
      original.getClientRects().length
        ? original
        : document.getElementById("main-content");
    if (target?.isConnected && target.getClientRects().length) target.focus();
  }
  return (
    <DialogContext.Provider
      value={{
        open: (next) => {
          trigger.current = {
            element:
              document.activeElement instanceof HTMLElement
                ? document.activeElement
                : null,
            scope,
          };
          intentOpen.current = true;
          intentSaved.current = false;
          setIntent(next);
        },
      }}
    >
      {children}
      {intent && (
        <AuthorizedDialog
          intent={intent}
          onClose={close}
          onCloseAutoFocus={restoreFocus}
          onSaved={(id, revisionId) => {
            intentSaved.current = true;
            void client.invalidateQueries({
              predicate: (query) =>
                query.queryKey.includes(intent.incidentId) ||
                query.queryKey.includes("dossier") ||
                query.queryKey.includes("revision"),
            });
            if (id) onSaved(id, revisionId);
          }}
        />
      )}
    </DialogContext.Provider>
  );
}
function AuthorizedDialog({
  intent,
  onClose,
  onSaved,
  onCloseAutoFocus,
}: {
  intent: Intent;
  onClose: () => void;
  onSaved: (dossierId?: string, revisionId?: string) => void;
  onCloseAutoFocus: (event: Event) => void;
}) {
  const session = useSession();
  const access = useQuery({
    queryKey: [
      ...scopeKey(session),
      "dossier-dialog-access",
      intent.incidentId,
      intent.dossierId ?? null,
    ],
    gcTime: 0,
    staleTime: 0,
    queryFn: async ({ signal }) => {
      const resource = intent.dossierId
        ? await request("/api/v1/dossiers/" + intent.dossierId, dossierSchema, {
            signal,
          })
        : await request(
            "/api/v1/incidents/" + intent.incidentId,
            incidentSchema,
            { signal },
          );
      const permission =
        intent.kind === "review"
          ? "review_revision"
          : intent.dossierId
            ? "edit_dossier"
            : "create_dossier";
      if (
        !resource.permissions.includes(permission) ||
        ("incident_id" in resource &&
          resource.incident_id !== intent.incidentId) ||
        (intent.kind === "review" &&
          "evidence_snapshot_id" in resource &&
          resource.evidence_snapshot_id !== intent.snapshotId)
      )
        throw new ApiError(
          403,
          "permission_changed",
          "A autorização para este formulário não está mais disponível. Reabra o incidente para conferir seu acesso.",
        );
      return true;
    },
  });
  const revoked =
    access.error instanceof ApiError &&
    [401, 403, 404].includes(access.error.status);
  if (access.isPending || (access.isError && (!access.data || revoked)))
    return (
      <Dialog
        open
        onCloseAutoFocus={onCloseAutoFocus}
        onOpenChange={(open) => {
          if (!open) onClose();
        }}
        title="Conferir autorização"
        description="O formulário exige acesso atual ao incidente e às fontes do dossiê."
      >
        {access.isError ? (
          <ErrorNotice
            error={access.error}
            retry={() => void access.refetch()}
          />
        ) : (
          <Loading>Conferindo acesso…</Loading>
        )}
      </Dialog>
    );
  return intent.kind === "edit" ? (
    <DossierEditor
      {...intent}
      checkingAccess={access.isFetching || access.isError}
      accessError={access.error ?? undefined}
      retryAccess={() => void access.refetch()}
      onClose={onClose}
      onCloseAutoFocus={onCloseAutoFocus}
      onSaved={onSaved}
    />
  ) : (
    <ReviewDecision
      {...intent}
      checkingAccess={access.isFetching || access.isError}
      accessError={access.error ?? undefined}
      retryAccess={() => void access.refetch()}
      onClose={onClose}
      onCloseAutoFocus={onCloseAutoFocus}
      onSaved={(revision) => onSaved(intent.dossierId, revision.id)}
    />
  );
}
