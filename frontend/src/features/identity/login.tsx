"use client";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ArrowRight, Files, LockKeyhole } from "lucide-react";
import { request } from "@/lib/http";
import { sessionSchema, type Session } from "@/lib/contracts";
import { Button } from "@/components/ui/button";
import { ErrorNotice, FieldError } from "@/components/feedback";

const schema = z.object({
  email: z.email("Informe um e-mail válido."),
  password: z.string().min(1, "Informe sua senha."),
});
export function Login({
  onAuthenticated,
}: {
  onAuthenticated: (session: Session) => Promise<void>;
}) {
  const [error, setError] = useState<unknown>();
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });
  const submit = form.handleSubmit(async (values) => {
    setError(undefined);
    try {
      await onAuthenticated(
        await request("/api/v1/auth/login", sessionSchema, {
          method: "POST",
          body: values,
        }),
      );
    } catch (failure) {
      setError(failure);
    }
  });
  return (
    <main className="login-screen">
      <section className="login-context">
        <Link className="brand" href="/">
          <Files size={24} />
          <span>EvidenceDesk</span>
        </Link>
        <div className="login-intro">
          <h1>Investigação de incidentes em pedidos</h1>
          <p>
            Compare eventos e snapshots, monte um dossiê com as fontes e submeta
            a conclusão à revisão de outra conta. Dados fictícios.
          </p>
        </div>
      </section>
      <section className="login-form-wrap">
        <div className="login-form">
          <LockKeyhole size={23} />
          <h2>Acessar a bancada</h2>
          <p>Entre com a conta da sua organização.</p>
          <form onSubmit={submit} noValidate>
            <label className="field">
              <span id="login-email-label">E-mail</span>
              <input
                autoComplete="username"
                inputMode="email"
                type="email"
                {...form.register("email")}
                aria-labelledby="login-email-label"
                aria-describedby={
                  form.formState.errors.email ? "login-email-error" : undefined
                }
                aria-invalid={!!form.formState.errors.email}
              />
              <FieldError
                id="login-email-error"
                message={form.formState.errors.email?.message}
              />
            </label>
            <label className="field">
              <span id="login-password-label">Senha</span>
              <input
                type="password"
                autoComplete="current-password"
                {...form.register("password")}
                aria-labelledby="login-password-label"
                aria-describedby={
                  form.formState.errors.password
                    ? "login-password-error"
                    : undefined
                }
                aria-invalid={!!form.formState.errors.password}
              />
              <FieldError
                id="login-password-error"
                message={form.formState.errors.password?.message}
              />
            </label>
            {error !== undefined && <ErrorNotice error={error} />}
            <Button
              type="submit"
              variant="primary"
              disabled={form.formState.isSubmitting}
            >
              {form.formState.isSubmitting ? "Entrando…" : "Entrar"}
              <ArrowRight size={17} />
            </Button>
          </form>
          <p className="muted login-security">
            A sessão determina quais incidentes e fontes você pode consultar.
          </p>
        </div>
      </section>
    </main>
  );
}
