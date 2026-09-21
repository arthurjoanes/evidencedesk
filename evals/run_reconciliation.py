"""Run deterministic dev cases only. Does not claim semantic or provider quality."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from evidencedesk.reconciliation import (
    EventObservation,
    IdentityMapping,
    OrderSnapshot,
    ReconciliationInput,
    SourceCoverage,
    TimeWindow,
    reconcile,
)


def evaluate(data_dir: Path, output: Path) -> dict:
    cases = [
        json.loads(line)
        for line in (data_dir / "dev.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    details = []
    for case in cases:
        source_path = (data_dir / case["source_path"]).resolve()
        if not source_path.is_relative_to(data_dir.resolve()):
            raise ValueError("Fonte fora do diretório de avaliação.")
        source_bytes = source_path.read_bytes()
        if hashlib.sha256(source_bytes).hexdigest() != case["source_sha256"]:
            raise ValueError("Checksum da fonte de avaliação divergente.")
        source = json.loads(source_bytes)
        window = TimeWindow.model_validate(
            {
                key: value
                for key, value in source["window"].items()
                if key in {"from", "to"}
            }
        )
        observations, snapshots = [], []
        for line_number, item in enumerate(source["corpus"], 1):
            provenance = {
                "evidence_id": item["evidence_id"],
                "source_file_sha256": case["source_sha256"],
                "line_number": line_number,
            }
            if item["kind"] == "source_event":
                observations.append(
                    EventObservation.model_validate(
                        {
                            **item["source_record"],
                            **provenance,
                            "ingested_at": window.end,
                        }
                    )
                )
            elif item["kind"] == "order_snapshot":
                snapshots.append(
                    OrderSnapshot.model_validate(
                        {**item["source_record"], **provenance}
                    )
                )
        result = reconcile(
            ReconciliationInput(
                tenant_id="evaluation",
                evidence_snapshot_id=case["case_id"],
                window=window,
                watermark=window.end,
                events=tuple(observations),
                snapshots=tuple(snapshots),
                mappings=tuple(
                    IdentityMapping.model_validate(row) for row in source["mappings"]
                ),
                coverage=tuple(
                    SourceCoverage.model_validate(row) for row in source["coverage"]
                ),
            )
        )
        observed = {(fact.rule_code, fact.status) for fact in result.divergences}
        expectation = case["reconciliation_expectation"]
        missing = [
            code
            for code, status in expectation["required"].items()
            if (code, status) not in observed
        ]
        forbidden = [
            code
            for code in expectation["forbidden"]
            if any(rule == code for rule, _ in observed)
        ]
        details.append(
            {
                "case_id": case["case_id"],
                "scenario_family": case["scenario_family"],
                "passed": not missing and not forbidden,
                "missing_rules": missing,
                "forbidden_rules": forbidden,
                "observations": result.counts.observations,
                "orders": result.counts.orders,
            }
        )
    report = {
        "evaluation": "deterministic_reconciliation_dev",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "planned": len(cases),
        "executed": len(details),
        "passed": sum(row["passed"] for row in details),
        "failed": sum(not row["passed"] for row in details),
        "categories": dict(Counter(case["scenario_family"] for case in cases)),
        "reserved_used": False,
        "azure_calls": 0,
        "human_semantic_gate": "inconclusive",
        "retrieval_and_model_gates": "not_executed",
        "cases": details,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("evals/data"))
    parser.add_argument(
        "--output", type=Path, default=Path("evals/reports/reconciliation-dev.json")
    )
    args = parser.parse_args()
    report = evaluate(args.data, args.output)
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("planned", "executed", "passed", "failed", "reserved_used")
            }
        )
    )
    raise SystemExit(0 if report["failed"] == 0 else 1)
