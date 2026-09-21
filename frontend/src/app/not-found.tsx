import Link from "next/link";
export default function NotFound() {
  return (
    <div className="empty-state">
      <h1>Página não encontrada</h1>
      <p>O endereço pode ter mudado ou não estar disponível.</p>
      <Link href="/">Voltar aos incidentes</Link>
    </div>
  );
}
