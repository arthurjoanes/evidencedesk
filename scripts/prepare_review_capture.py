"""Create two real, synthetic review cases on an isolated capacity source before backup.

This exercises application roles with demo accounts; it is not a human evaluation.
It neither starts services nor invokes a model. Browser capture is a separate step.
"""

import argparse
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from backup import command_budget, command_timeout, run
from capacity_http import api_targets, capacity_project, provider_calls
from capacity_jobs import login, request
from restore_read_probe import new_private_directory, runtime_proof, write_private


def prepare(author, reviewer, run_id):
    def call(client, method, path, **kwargs):
        result = request(client, method, path, timeout=command_timeout(15), **kwargs)
        command_timeout()
        return result

    for client in (author, reviewer):
        session = call(client, "GET", "/auth/session")
        if session["runtime"]["generation_enabled"] or session["runtime"]["provider"] != "disabled":
            raise ValueError("Only a source with generation disabled may prepare capture cases.")
    incident = call(author, "GET", "/incidents/demo-aurora-01")
    sources = call(author, "GET", "/incidents/demo-aurora-01/evidence?limit=30")["items"]
    if not sources:
        raise ValueError("The seeded incident has no authorized source to cite.")
    source = call(
        author,
        "GET",
        f"/evidence/{sources[0]['id']}?evidence_snapshot_id={incident['evidence_snapshot_id']}",
    )
    quote = source["canonical_text"].strip()[:250]
    if not quote:
        raise ValueError("A real canonical text is required for the citation case.")
    payload = {
        "evidence_snapshot_id": incident["evidence_snapshot_id"],
        "summary": "Ensaio sintético de revisão e rastreabilidade " + run_id,
        "outcome": "evidence_found",
        "claims": [
            {
                "kind": "observed_fact",
                "text": "Trecho literal da fonte sintética: " + quote,
                "evidence_links": [{"evidence_id": source["id"], "relation": "supports"}],
            }
        ],
    }
    cases = {}
    for name in ("approved", "conflict"):
        dossier = call(
            author, "POST", f"/incidents/{incident['id']}/dossiers", status=201, json=payload
        )
        path = "/dossiers/" + dossier["id"]
        revision = call(author, "GET", path + "/revisions/" + dossier["current_revision_id"])
        cases[name] = {
            "incident_id": incident["id"],
            "dossier_id": dossier["id"],
            "revision_id": revision["id"],
        }
        if name == "approved":
            headers = {"If-Match": revision["etag"]}
            call(
                author,
                "POST",
                path + "/submit",
                headers=headers,
                json={"target_revision_id": revision["id"]},
            )
            call(
                reviewer,
                "POST",
                path + "/reviews",
                headers=headers,
                json={
                    "target_revision_id": revision["id"],
                    "claim_ids": [claim["claim_id"] for claim in revision["claims"]],
                    "decision": "approved",
                    "reason": "Ensaio automatizado com contas de papéis distintos; não avaliação humana.",
                },
            )
            checked = call(author, "GET", path + "/revisions/" + revision["id"])
            if checked["review_status"] != "approved":
                raise ValueError("The application did not approve the expected revision.")
            cases[name]["expected_source_ids"] = [source["id"]]
    return {"run_id": run_id, **cases}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--project", required=True, type=capacity_project)
    cli.add_argument("--runtime-proof", required=True, type=Path)
    cli.add_argument("--artifacts", required=True, type=Path)
    args = cli.parse_args()
    frozen = runtime_proof(args.runtime_proof)
    directory = new_private_directory(args.artifacts)
    clients = []
    result = {"status": "running", "project": args.project, "human_evaluation": False}
    try:
        with command_budget(120):
            image = run(
                ["docker", "inspect", "--format", "{{.Image}}", args.project + "-api-1"],
                capture=True,
            ).strip()
            if image != frozen["images"]["api"] or provider_calls(args.project) != 0:
                raise ValueError("Expected the frozen isolated API without provider calls.")
            target = api_targets(args.project, 1)[0]
            clients.append(login(target, "admin", "aurora"))
            clients.append(login(target, "bruno", "aurora"))
            case = prepare(*clients, uuid4().hex[:12])
            if provider_calls(args.project) != 0:
                raise ValueError("Preparing review cases admitted a provider call.")
            write_private(directory / "review-case.json", case)
            result.update(status="passed", provider_calls=0, case=case)
    except BaseException as error:
        result.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        for client in clients:
            client.close()
        result["recorded_at"] = datetime.now(UTC).isoformat()
        write_private(directory / "preparation.json", result)


if __name__ == "__main__":
    main()
