"""Synthetic document relevance pairs; operational facts still use deterministic rules."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

# Only development families. Final evaluation families are never imported here.
TOPICS = {
    "duplicate_webhook": (
        "reentrega do webhook",
        "mensagens com a mesma identidade de operação",
        "Reentregas não comprovam duplicidade de cobrança. Compare a identidade da operação.",
    ),
    "delayed_delivery": (
        "confirmação recebida com atraso",
        "diferença entre ocorrência e recebimento",
        "Uma observação tardia pode descrever ocorrência anterior; preserve ambos os horários.",
    ),
    "out_of_order": (
        "eventos fora de ordem",
        "ordem de chegada diferente da ordem de ocorrência",
        "Não deduza causalidade da ordenação. Considere incerteza dos relógios e empates.",
    ),
    "ambiguous_timeout": (
        "timeout na confirmação",
        "resposta ausente e aceite desconhecido",
        "Timeout não prova rejeição nem permite repetir um pagamento sem confirmação externa.",
    ),
    "expired_reservation": (
        "reserva expirada",
        "expiração próxima da confirmação do pagamento",
        "Expiração anterior à confirmação é uma sequência observada, não prova de causa raiz.",
    ),
    "stale_snapshot": (
        "snapshot desatualizado",
        "estado capturado antes da confirmação",
        "Um estado antigo não comprova divergência atual. Compare as_of e o horário da ocorrência.",
    ),
    "identity_mismatch": (
        "referências incompatíveis",
        "identificadores de pedido de sistemas distintos",
        "A semelhança textual não autoriza associação. Exija um mapeamento explícito entre sistemas.",
    ),
    "obsolete_procedure": (
        "procedimento substituído",
        "documentação com versões e períodos de validade diferentes",
        "Use a política vigente na janela do incidente. Revisão histórica serve apenas de contexto.",
    ),
}
QUERY_TEMPLATES = (
    "Para {order}, procure notas sobre {topic}. Quero verificar a hipótese e seus limites.",
    "Quais documentos ajudam a investigar {topic} no pedido {order}, incluindo evidência contrária?",
    "Investigo o pedido {order}: como interpretar {detail} sem afirmar uma causa não demonstrada?",
    "Encontre orientações e registros retrospectivos de {order} ligados a {topic}.",
    "Na análise de {order}, quais notas contestam conclusões precipitadas sobre {topic}?",
)
SHARED_REFERENCES = {
    "shared-procedure-v2": (
        "Procedimento de conciliação de pagamentos. Preserve identidades, estados e horários. "
        "O prazo fictício de confirmação no domínio de pedidos é de trezentos segundos. "
        "Não transforme correlação em causa; cite limitações e peça revisão humana."
    ),
    "shared-collection-guide-v1": (
        "Guia de coleta para investigação. Ausência no recorte não prova ausência na origem. "
        "Inspecione cobertura, intervalos faltantes, fuso, precisão dos relógios e marca de ingestão. "
        "Notas retrospectivas orientam consultas; os fatos operacionais exigem registros originais."
    ),
    "shared-unrelated-hr-v1": "Manual de benefícios internos: férias e atualização cadastral de funcionários.",
    "shared-unrelated-catalogue-v1": "Catálogo de decoração: medidas de vasos, cores e acabamentos disponíveis.",
}


def build_pairs() -> list[dict]:
    pairs = []
    for group_index in range(180):
        split = "train" if group_index < 150 else "dev"
        family = list(TOPICS)[group_index % len(TOPICS)]
        topic, detail, caution = TOPICS[family]
        group = f"training-docs-{group_index:03d}"
        focus = f"LAB-{group_index + 2000}-A"
        other = f"LAB-{group_index + 2000}-B"
        query = QUERY_TEMPLATES[group_index % len(QUERY_TEMPLATES)].format(
            order=focus, topic=topic, detail=detail
        )
        samples = [
            (
                (
                    f"Nota retrospectiva do pedido {focus}. Tema: {topic}. A investigação relatou {detail}. "
                    f"{caution} Esta nota organiza a revisão; valide o relato nas fontes originais."
                ),
                1.0,
                "case_note",
                group + "-note",
                "retrospective_context",
            ),
            (
                (
                    f"Revisão da hipótese no pedido {focus}: {topic}. {caution} "
                    "Uma explicação alternativa permanece aberta. A equipe deve confrontar os registros "
                    "dos sistemas e registrar informação faltante antes de concluir o dossiê."
                ),
                1.0,
                "counterevidence_or_limitation",
                group + "-review",
                "retrospective_context",
            ),
            (
                SHARED_REFERENCES["shared-procedure-v2"],
                0.5,
                "procedure_context",
                "shared-procedure-v2",
                "applicable_procedure",
            ),
            (
                SHARED_REFERENCES["shared-collection-guide-v1"],
                0.5,
                "coverage_context",
                "shared-collection-guide-v1",
                "applicable_procedure",
            ),
            (
                (
                    f"Nota retrospectiva do pedido {other}. Tema: {topic}. Foi relatada {detail}. "
                    f"{caution} Não há relação declarada entre este pedido e outros pedidos."
                ),
                0.0,
                "different_order_hard_negative",
                group + "-other-note",
                "retrospective_context",
            ),
            (
                (
                    f"Revisão da hipótese no pedido {other}: {topic}. {caution} "
                    "A análise é restrita a este pedido; não há identidade ou dependência compartilhada documentada."
                ),
                0.0,
                "different_order_hard_negative",
                group + "-other-review",
                "retrospective_context",
            ),
            (
                SHARED_REFERENCES["shared-unrelated-hr-v1"],
                0.0,
                "unrelated",
                "shared-unrelated-hr-v1",
                "historical_artifact",
            ),
            (
                SHARED_REFERENCES["shared-unrelated-catalogue-v1"],
                0.0,
                "unrelated",
                "shared-unrelated-catalogue-v1",
                "historical_artifact",
            ),
        ]
        for sample_index, (passage, label, rationale, lineage, role) in enumerate(
            samples
        ):
            pairs.append(
                {
                    "pair_id": f"{group}-{sample_index}",
                    "query_group": group,
                    "scenario_instance": group,
                    "document_lineage": lineage,
                    "shared_reference": lineage in SHARED_REFERENCES,
                    "scenario_family": family,
                    "split": split,
                    "query": query,
                    "passage": passage,
                    "label": label,
                    "label_rationale": rationale,
                    "temporal_role": role,
                    "annotation_method": "synthetic_declared_reference",
                    "human_adjudicated": False,
                    "focus_order": focus,
                }
            )
    return pairs


def write_pairs(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    pairs = build_pairs()
    files = []
    for split in ("train", "dev"):
        rows = [pair for pair in pairs if pair["split"] == split]
        content = (
            "\n".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows
            )
            + "\n"
        ).encode()
        path = output / f"{split}.jsonl"
        path.write_bytes(content)
        files.append(
            {
                "path": path.name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "pairs": len(rows),
                "query_groups": len({row["query_group"] for row in rows}),
            }
        )
    manifest = {
        "version": "reranker-synthetic-documents-v2",
        "files": files,
        "annotation": "synthetic_not_human_adjudicated",
        "promotion_eligible": False,
        "shared_reference_lineages": list(SHARED_REFERENCES),
        "serving_alignment": "document spans only; operational reconciliation is never learned by this reranker",
        "limitations": [
            "Compartilhamento declarado de quatro referências; dev avalia novos casos sobre documentos conhecidos.",
            "Cinco moldes de pergunta e oito famílias: não equivale à diversidade de produção.",
            "Nenhuma fonte, questão ou gold da avaliação final integra o treino.",
            "Rótulos e auditoria automáticos não substituem adjudicação semântica humana.",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("experiments/data"))
    args = parser.parse_args()
    print(json.dumps(write_pairs(args.output), ensure_ascii=False))
