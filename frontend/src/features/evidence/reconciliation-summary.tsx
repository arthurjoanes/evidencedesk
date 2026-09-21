import { Status } from "@/components/feedback";
import { number, timestamp } from "@/lib/format";
import type { ReconciliationContent } from "./reconciliation-content";

const measures = [
  ["orders", "Pedidos"],
  ["observations", "Observações recebidas"],
  ["logical_events", "Eventos lógicos"],
  ["divergences", "Divergências"],
  ["not_evaluable", "Não avaliáveis"],
] as const;

export function ReconciliationSummary({
  content,
}: {
  content: ReconciliationContent;
}) {
  return (
    <section
      className="reconciliation-source"
      aria-label="Conciliação estruturada"
    >
      <h3>Resultado determinístico</h3>
      <p className="muted">
        Valores registrados nesta evidência. A leitura não recalcula o recorte
        nem confirma uma causa.
      </p>
      <dl className="reconciliation-measures">
        {measures.map(([key, name]) => (
          <div key={key}>
            <dt>{name}</dt>
            <dd>
              {content.counts?.[key] === undefined
                ? "Não informado"
                : number(content.counts[key])}
            </dd>
          </div>
        ))}
      </dl>
      <h3>Regra e período</h3>
      <p className="mono">{content.rule_revision ?? "Regra não informada"}</p>
      <p>
        {content.window ? (
          <>
            {timestamp(content.window.from)} → {timestamp(content.window.to)}
            <small>
              Horários em America/Sao_Paulo. O original preserva o fuso
              recebido.
            </small>
          </>
        ) : (
          "Período não informado."
        )}
      </p>
      <h3>Cobertura declarada</h3>
      {content.coverage === undefined ? (
        <p>Cobertura não informada.</p>
      ) : content.coverage.length === 0 ? (
        <p>Nenhuma janela de cobertura registrada.</p>
      ) : (
        <ul className="reconciliation-records">
          {content.coverage.map((coverage, index) => (
            <li key={index}>
              <div className="reconciliation-record-heading">
                <strong>{coverage.source_system}</strong>
                <Status value={coverage.status} />
              </div>
              <p>
                {timestamp(coverage.from)} → {timestamp(coverage.to)}
              </p>
              <p>
                Tipos de evento:{" "}
                {coverage.event_types?.length
                  ? coverage.event_types.join(", ")
                  : coverage.event_types
                    ? "Sem restrição declarada"
                    : "Não informados"}
              </p>
              <p>
                Incerteza do relógio:{" "}
                {coverage.clock_uncertainty_ms == null
                  ? "Não informada"
                  : number(coverage.clock_uncertainty_ms) + " ms"}
              </p>
              {coverage.gaps === undefined ? (
                <p>Lacunas não informadas.</p>
              ) : coverage.gaps.length ? (
                <ul>
                  {coverage.gaps.map((gap, index) => (
                    <li key={index}>{gap}</li>
                  ))}
                </ul>
              ) : (
                <p>Sem lacunas declaradas nesta janela.</p>
              )}
            </li>
          ))}
        </ul>
      )}
      <h3>Avaliações incluídas</h3>
      <p>
        {content.divergences_included === undefined
          ? "Quantidade incluída não informada"
          : number(content.divergences_included) + " incluídas"}{" "}
        ·{" "}
        {content.divergences_total === undefined
          ? "Total não informado"
          : number(content.divergences_total) + " no recorte"}
        . A lista pode ser um subconjunto das avaliações.
      </p>
      {content.divergences === undefined ? (
        <p>A lista não está disponível nesta evidência.</p>
      ) : content.divergences.length === 0 ? (
        <p>
          Nenhuma avaliação incluída. Isso, isoladamente, não comprova ausência
          de problemas.
        </p>
      ) : (
        <ul className="reconciliation-records">
          {content.divergences.map((item, index) => (
            <li key={item.id + index}>
              <div className="reconciliation-record-heading">
                <strong>
                  {item.order_reference ?? "Sem correlação de pedido"}
                </strong>
                <Status value={item.status} />
              </div>
              <p>{item.summary}</p>
              <details>
                <summary>Regra desta avaliação</summary>
                <p className="mono">
                  {item.rule_code} · {item.rule_revision}
                </p>
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
