"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import {
  Files,
  FolderSearch,
  Upload,
  LogOut,
  PanelLeftClose,
} from "lucide-react";
import type { Session } from "@/lib/contracts";
import { label } from "@/lib/format";
import { Button } from "./ui/button";
import { ErrorNotice } from "./feedback";

export function AppShell({
  session,
  onLogout,
  children,
}: {
  session: Session;
  onLogout: () => Promise<void>;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const [logoutError, setLogoutError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Pular para o conteúdo
      </a>
      <aside className="app-sidebar">
        <Link className="brand" href="/">
          <Files size={23} />
          <span>EvidenceDesk</span>
        </Link>
        <div className="organization">
          <span className="organization-mark">
            {session.tenant.name.slice(0, 1)}
          </span>
          <div>
            <strong>{session.tenant.name}</strong>
            <small>Organização atual</small>
          </div>
        </div>
        <nav aria-label="Navegação principal">
          <Link
            className={
              pathname === "/" || pathname.startsWith("/incidents")
                ? "active"
                : ""
            }
            href="/"
          >
            <FolderSearch size={18} />
            Incidentes
          </Link>
          <Link
            className={pathname.startsWith("/imports") ? "active" : ""}
            href="/imports"
          >
            <Upload size={18} />
            Importações
          </Link>
        </nav>
        <div className="sidebar-note">
          <PanelLeftClose size={18} />
          <p>
            Investigue os registros.
            <br />
            Preserve as incertezas.
          </p>
        </div>
      </aside>
      <div className="app-body">
        <header className="app-topbar">
          <span className="workspace-label">Bancada de investigação</span>
          <div className="user-menu">
            <span>
              <strong>{session.user.name}</strong>
              <small>{label(session.user.role)}</small>
            </span>
            <Button
              size="icon"
              variant="ghost"
              aria-label="Sair da sessão"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await onLogout();
                } catch (error) {
                  setLogoutError(error);
                  setBusy(false);
                }
              }}
            >
              <LogOut size={17} />
            </Button>
          </div>
        </header>
        {logoutError !== undefined && <ErrorNotice error={logoutError} />}
        <main id="main-content" className="main-content" tabIndex={-1}>
          {children}
        </main>
        <footer className="app-footer">
          <span>Horários em Brasília (UTC−3), salvo indicação explícita.</span>
          <span>Fontes versionadas · revisão humana</span>
        </footer>
      </div>
    </div>
  );
}
