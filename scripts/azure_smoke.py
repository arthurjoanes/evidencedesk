"""One idempotent synthetic investigation through the real local API and Azure worker."""

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--incident-id", default="demo-aurora-01")
    parser.add_argument("--idempotency-key", default="azure-smoke-v1")
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/azure-smoke.json"))
    arguments = parser.parse_args()
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "profile": "real_azure_synthetic_single_run",
        "maximum_new_runs": 1,
        "reserved_token_ceiling": 12400,
        "semantic_quality_gate": "not_adjudicated",
    }
    with httpx.Client(
        base_url="http://127.0.0.1:8106",
        headers={"Origin": "http://localhost:3106"},
        timeout=20,
    ) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "ana@aurora.demo", "password": "EvidenceDesk-demo-2026!"},
        )
        login.raise_for_status()
        session = login.json()
        if not session["runtime"]["generation_enabled"]:
            raise RuntimeError("Azure runtime is disabled; no investigation was submitted.")
        client.headers["X-CSRF-Token"] = session["csrf_token"]
        incident = client.get(f"/api/v1/incidents/{arguments.incident_id}")
        incident.raise_for_status()
        snapshot = incident.json()["evidence_snapshot_id"]
        submitted = client.post(
            f"/api/v1/incidents/{arguments.incident_id}/runs",
            json={
                "evidence_snapshot_id": snapshot,
                "question": "O que a conciliação mostra sobre reentregas de pagamento? Distinga observação de hipótese e explicite lacunas. Use apenas as fontes disponíveis.",
            },
            headers={"Idempotency-Key": arguments.idempotency_key},
        )
        submitted.raise_for_status()
        run_id = submitted.json()["id"]
        report.update(
            {
                "run_id": run_id,
                "incident_id": arguments.incident_id,
                "evidence_snapshot_id": snapshot,
            }
        )
        print(
            json.dumps({"run_id": run_id, "state": submitted.json()["state"]}),
            flush=True,
        )
        deadline = time.monotonic() + 180
        state = submitted.json()
        while time.monotonic() < deadline and state["state"] not in {
            "succeeded",
            "failed",
            "cancelled",
        }:
            time.sleep(2)
            response = client.get(f"/api/v1/runs/{run_id}")
            response.raise_for_status()
            state = response.json()
        report.update(
            {
                "finished_at": datetime.now(UTC).isoformat(),
                "state": state["state"],
                "outcome": state["outcome"],
                "usage": state["usage"],
                "error": state["error"],
                "steps": state["steps"],
            }
        )
        if state["state"] == "succeeded":
            dossier = client.get(f"/api/v1/dossiers/{state['dossier_id']}")
            dossier.raise_for_status()
            revision = client.get(
                f"/api/v1/dossiers/{state['dossier_id']}/revisions/{state['revision_id']}"
            )
            revision.raise_for_status()
            content = revision.json()
            for claim in content["claims"]:
                for link in claim["evidence_links"]:
                    evidence = client.get(
                        f"/api/v1/evidence/{link['evidence_id']}",
                        params={"evidence_snapshot_id": snapshot},
                    )
                    evidence.raise_for_status()
            report.update(
                {
                    "dossier_id": state["dossier_id"],
                    "revision_id": state["revision_id"],
                    "review_status": content["review_status"],
                    "claim_count": len(content["claims"]),
                    "all_citations_accessible": True,
                    "revision_content_sha256": hashlib.sha256(
                        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
                    ).hexdigest(),
                }
            )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "state": report["state"],
                    "usage": report["usage"],
                    "error": report["error"],
                    "report": str(arguments.output),
                },
                ensure_ascii=True,
            )
        )
        client.post("/api/v1/auth/logout")
    return 0 if report["state"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
