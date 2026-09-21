"""Construct isolated synthetic evaluation cases with explicit reference provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# This script also runs directly; keep generation separate from the installed API.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "datasets"))
from generate import documents, incident_records

FAMILIES = (
    "duplicate_webhook",
    "delayed_delivery",
    "out_of_order",
    "ambiguous_timeout",
    "expired_reservation",
    "stale_snapshot",
    "identity_mismatch",
    "obsolete_procedure",
    "partial_failure",
    "missing_coverage",
)
QUESTIONS = {
    "duplicate_webhook": "Essas duas mensagens provam pagamento duplicado?",
    "delayed_delivery": "A confirmação de pagamento chegou a tempo ao serviço de pedidos?",
    "out_of_order": "Qual a diferença entre a sequência de ocorrência e de recepção?",
    "ambiguous_timeout": "O timeout significa que o pagamento foi recusado?",
    "expired_reservation": "A reserva expirou antes da confirmação no domínio?",
    "stale_snapshot": "O snapshot pode provar uma divergência posterior ao pagamento?",
    "identity_mismatch": "Podemos relacionar o pagamento a esse pedido sem o mapa de IDs?",
    "obsolete_procedure": "Qual procedimento estava vigente e qual foi consultado?",
    "partial_failure": "Por que a fonte de pagamento e o snapshot discordam?",
    "missing_coverage": "Sem logs completos, podemos concluir que a transição não ocorreu?",
}
RECONCILIATION_EXPECTATIONS = {
    "duplicate_webhook": {
        "required": {"event_redelivery": "observation"},
        "forbidden": [],
    },
    "delayed_delivery": {
        "required": {"transition_not_observed": "divergence"},
        "forbidden": [],
    },
    "out_of_order": {"required": {}, "forbidden": ["payment_snapshot_mismatch"]},
    "ambiguous_timeout": {"required": {}, "forbidden": ["payment_snapshot_mismatch"]},
    "expired_reservation": {
        "required": {"reservation_expired_before_confirmation": "divergence"},
        "forbidden": [],
    },
    "stale_snapshot": {"required": {}, "forbidden": ["payment_snapshot_mismatch"]},
    "identity_mismatch": {
        "required": {"insufficient_correlation": "not_evaluable"},
        "forbidden": ["payment_snapshot_mismatch"],
    },
    "obsolete_procedure": {"required": {}, "forbidden": ["payment_snapshot_mismatch"]},
    "partial_failure": {
        "required": {
            "payment_snapshot_mismatch": "divergence",
            "transition_not_observed": "divergence",
        },
        "forbidden": [],
    },
    "missing_coverage": {
        "required": {"transition_not_observed": "not_evaluable"},
        "forbidden": [],
    },
}


def build_cases() -> list[dict]:
    cases = []
    for split in ("dev", "reserved"):
        for index in range(60):
            # Reserved contains separate known-family instances AND genuinely held-out families.
            family = (
                FAMILIES[index % 8]
                if split == "dev" or index < 30
                else FAMILIES[8 + index % 2]
            )
            group = f"evaluation-{split}-{index:03d}"
            relevant_id = group + "-source"
            counter_id = group + "-counterevidence"
            unknown = family in {
                "ambiguous_timeout",
                "identity_mismatch",
                "partial_failure",
                "missing_coverage",
            }
            case, events, snapshots, mappings, coverage = incident_records(
                "evaluation",
                index + (1000 if split == "reserved" else 500),
                1,
                family_override=family,
                namespace=group,
            )
            corpus = []
            for event_index, event in enumerate(events):
                corpus.append(
                    {
                        "evidence_id": f"{group}-event-{event_index}",
                        "lineage": group + "-records",
                        "kind": "source_event",
                        "text": json.dumps(event, ensure_ascii=False),
                        "source_record": event,
                    }
                )
            for snapshot_index, snapshot in enumerate(snapshots):
                corpus.append(
                    {
                        "evidence_id": f"{group}-snapshot-{snapshot_index}",
                        "lineage": group + "-records",
                        "kind": "order_snapshot",
                        "text": json.dumps(snapshot, ensure_ascii=False),
                        "source_record": snapshot,
                    }
                )
            for document_index, (_, text, metadata) in enumerate(documents(case)):
                corpus.append(
                    {
                        "evidence_id": f"{group}-document-{document_index}",
                        "lineage": group + "-procedure",
                        "kind": "document_span",
                        "text": text,
                        "metadata": metadata,
                    }
                )
            focus_ids = [
                item["evidence_id"]
                for item in corpus
                if case["focus_order"] in item["text"]
            ]
            relevant_id = focus_ids[0]
            counter_id = f"{group}-document-0"
            cases.append(
                {
                    "case_id": group,
                    "split": split,
                    "scenario_family": family,
                    "scenario_instance": group,
                    "document_lineage": [group + "-procedure", group + "-records"],
                    "query_group": group + "-question",
                    "generalization": "unseen_family"
                    if split == "reserved" and index >= 30
                    else "known_family_new_instance",
                    "question": f"No pedido {case['focus_order']}: "
                    + QUESTIONS[family],
                    "answerable": not unknown,
                    "expected_outcome": "insufficient_evidence"
                    if unknown
                    else "evidence_found",
                    "expected_evidence_grades": {relevant_id: 2, counter_id: 2},
                    "required_facts": [
                        "Identificar o limite da evidência sem inferir causalidade."
                    ],
                    "prohibited_facts": [
                        "Afirmar causa raiz comprovada ou recomendar movimentação financeira."
                    ],
                    "annotation_method": "original_synthetic_reference",
                    "human_adjudicated": False,
                    "corpus": corpus,
                    "coverage": coverage,
                    "mappings": mappings,
                    "window": case["window"],
                    "focus_order": case["focus_order"],
                    "state": "synthetic_reference_requires_human_review",
                    "reconciliation_expectation": RECONCILIATION_EXPECTATIONS[family],
                }
            )
    return cases


def write_dataset(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    cases = build_cases()
    entries = []
    for split in ("dev", "reserved"):
        source_dir = output / "sources" / split
        source_dir.mkdir(parents=True, exist_ok=True)
        golds = []
        for case in cases:
            if case["split"] != split:
                continue
            source_fields = {"corpus", "coverage", "mappings", "window", "focus_order"}
            source_data = {
                key: value for key, value in case.items() if key in source_fields
            }
            source_bytes = (
                json.dumps(source_data, ensure_ascii=False, sort_keys=True) + "\n"
            ).encode("utf-8")
            source_path = source_dir / (case["case_id"] + ".json")
            source_path.write_bytes(source_bytes)
            gold = {
                key: value for key, value in case.items() if key not in source_fields
            }
            gold["source_path"] = source_path.relative_to(output).as_posix()
            gold["source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
            golds.append(gold)
        content = (
            "\n".join(
                json.dumps(case, ensure_ascii=False, sort_keys=True) for case in golds
            )
            + "\n"
        )
        data = content.encode("utf-8")
        filename = split + ".jsonl"
        (output / filename).write_bytes(data)
        entries.append(
            {"path": filename, "cases": 60, "sha256": hashlib.sha256(data).hexdigest()}
        )
    manifest = {
        "version": "evaluation-synthetic-v1",
        "origin": "original_synthetic",
        "semantic_status": "not_adjudicated",
        "entries": entries,
        "reserved_state": "uninspected",
        "common_runbooks": [],
        "limitation": "Fontes e referências sintéticas não adjudicadas. Não equivalem a validação humana.",
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evals/data"))
    args = parser.parse_args()
    result = write_dataset(args.output)
    print(
        json.dumps(
            {
                "version": result["version"],
                "cases": 120,
                "status": result["semantic_status"],
            }
        )
    )
