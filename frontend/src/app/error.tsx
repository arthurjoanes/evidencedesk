"use client";
import { Button } from "@/components/ui/button";
export default function ErrorBoundary({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="empty-state">
      <h1>Esta tela não pôde ser exibida</h1>
      <p>
        Seus dados salvos permanecem no servidor. Tente abrir a tela novamente.
      </p>
      <Button onClick={reset}>Reabrir tela</Button>
    </div>
  );
}
