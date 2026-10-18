import type { CSSProperties } from "react";
import type { z } from "zod";
import type { divergencePageSchema } from "@/lib/contracts";
import { number } from "@/lib/format";

const statuses = [
  ["divergence", "Divergências"],
  ["not_evaluable", "Não avaliáveis"],
  ["observation", "Observações"],
] as const;

export function AssessmentChart({
  summary,
}: {
  summary: z.infer<typeof divergencePageSchema>["summary"];
}) {
  return (
    <section className="assessment-analysis" aria-label="Resumo das avaliações">
      <div className="assessment-heading">
        <h2>Avaliações do recorte</h2>
        <p>
          <strong>{number(summary.orders_with_divergence)}</strong>{" "}
          {summary.orders_with_divergence === 1
            ? "pedido com divergência"
            : "pedidos com divergência"}
        </p>
      </div>
      <ul className="assessment-bars">
        {statuses.map(([status, name]) => (
          <li key={status}>
            <span>{name}</span>
            <span className="assessment-track" aria-hidden="true">
              <span
                className={`assessment-bar ${status}`}
                style={
                  {
                    "--share": summary.assessments
                      ? summary.by_status[status] / summary.assessments
                      : 0,
                  } as CSSProperties
                }
              />
            </span>
            <strong>{number(summary.by_status[status])}</strong>
          </li>
        ))}
      </ul>
      {summary.uncorrelated_assessments > 0 && (
        <p className="muted">
          {number(summary.uncorrelated_assessments)}{" "}
          {summary.uncorrelated_assessments === 1 ? "avaliação" : "avaliações"}{" "}
          sem pedido identificado.
        </p>
      )}
    </section>
  );
}
