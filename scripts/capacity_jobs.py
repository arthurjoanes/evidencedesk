"""Real ingestion/export bursts; isolated Compose namespace, no model generation."""

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from capacity_http import (
    DEMO_PASSWORD,
    api_targets,
    capacity_project,
    capture,
    compose,
    provider_calls,
)


def sql(project, statement):
    return capture(
        compose(project)
        + [
            "exec",
            "-T",
            "db",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "evidencedesk",
            "-At",
            "-c",
            statement,
        ]
    )


def request(client, method, path, status=200, **kwargs):
    response = client.request(method, "/api/v1" + path, **kwargs)
    if response.status_code != status:
        raise RuntimeError(f"{method} {path.split('/')[1]}: HTTP {response.status_code}")
    return response.json()


def login(target, user, tenant):
    client = httpx.Client(base_url=target, headers={"Origin": "http://localhost:3106"}, timeout=60)
    payload = request(
        client,
        "POST",
        "/auth/login",
        json={"email": f"{user}@{tenant}.demo", "password": DEMO_PASSWORD},
    )
    client.headers["X-CSRF-Token"] = payload["csrf_token"]
    return client


def prepare_dossier(author, reviewer, tenant):
    incident = request(author, "GET", f"/incidents/demo-{tenant}-01")
    dossier = request(
        author,
        "POST",
        f"/incidents/{incident['id']}/dossiers",
        status=201,
        json={
            "evidence_snapshot_id": incident["evidence_snapshot_id"],
            "summary": "<script>synthetic</script> Capacidade local.",
            "outcome": "insufficient_evidence",
            "claims": [],
            "missing_information": ["Conferência adicional"],
        },
    )
    path = f"/dossiers/{dossier['id']}"
    revision = request(author, "GET", f"{path}/revisions/{dossier['current_revision_id']}")
    headers = {"If-Match": revision["etag"]}
    request(
        author,
        "POST",
        path + "/submit",
        json={"target_revision_id": revision["id"]},
        headers=headers,
    )
    request(
        reviewer,
        "POST",
        path + "/reviews",
        json={
            "target_revision_id": revision["id"],
            "claim_ids": [],
            "decision": "approved",
            "reason": "Ensaio sintético com revisão independente.",
        },
        headers=headers,
    )
    return path, revision["id"]


def prepare_jobs(author, tenant, count, dossier, tag):
    resources = []
    path, revision = dossier
    for index in range(count):
        export = request(
            author,
            "POST",
            path + "/exports",
            status=202,
            json={"revision_id": revision},
            headers={"Idempotency-Key": f"{tag}-{tenant}-{index}"},
        )
        resources.append({"tenant": tenant, "kind": "export", "resource_id": export["id"]})
        content = (
            f"# Ensaio {tag} {tenant} {index}\n" + "Documento sintético de operação.\n" * 1000
        ).encode()
        imported = request(
            author,
            "POST",
            "/imports",
            status=201,
            json={
                "collection_id": "capacity-jobs",
                "manifest": {
                    "schema_version": "1",
                    "title": f"Capacity {tag} {index}",
                    "source_tenant": tenant,
                    "coverage": [],
                    "entries": [
                        {
                            "entry_id": "doc",
                            "filename": "capacity.md",
                            "kind": "document",
                            "media_type": "text/markdown",
                            "byte_size": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "metadata": {
                                "title": "Documento sintético",
                                "version": "1",
                                "temporal_role": "historical_artifact",
                            },
                        }
                    ],
                },
            },
        )
        request(
            author,
            "PUT",
            f"/imports/{imported['id']}/files/doc",
            content=content,
            headers={"Content-Type": "text/markdown"},
        )
        request(author, "POST", f"/imports/{imported['id']}/finalize", status=202)
        resources.append({"tenant": tenant, "kind": "ingestion", "resource_id": imported["id"]})
    return resources


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--project", required=True, type=capacity_project)
    cli.add_argument("--workers", required=True, type=int, choices=(1, 2))
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists():
        raise ValueError("Refusing to overwrite evidence.")
    record = {
        "started_at": datetime.now(UTC).isoformat(),
        "project": args.project,
        "workers": args.workers,
        "kind": "real-ingestion-export-burst",
        "status": "running",
        "resources": [],
    }
    clients = []
    try:
        if provider_calls(args.project) != 0:
            raise ValueError("Expected an isolated database without provider calls.")
        subprocess.run(compose(args.project) + ["stop", "worker"], check=True, capture_output=True)
        target = api_targets(args.project, 1)[0]
        sql(
            args.project,
            "INSERT INTO collections(tenant_id,id,name) SELECT id,'capacity-jobs','Capacity jobs' FROM tenants WHERE id IN('aurora','horizonte') ON CONFLICT DO NOTHING; INSERT INTO collection_grants(tenant_id,collection_id,user_id) SELECT tenant_id,'capacity-jobs',id FROM users WHERE tenant_id IN('aurora','horizonte') ON CONFLICT DO NOTHING;",
        )
        authors = {}
        tag = uuid4().hex
        # Larger tenant is deliberately admitted first; progress of the small tenant is measured.
        for tenant, author_name, reviewer_name, count in [
            ("aurora", "ana", "bruno", 6),
            ("horizonte", "carla", "diego", 2),
        ]:
            author, reviewer = (
                login(target, author_name, tenant),
                login(target, reviewer_name, tenant),
            )
            clients.extend([author, reviewer])
            authors[tenant] = author
            record["resources"].extend(
                prepare_jobs(author, tenant, count, prepare_dossier(author, reviewer, tenant), tag)
            )
        record["released_at"] = sql(args.project, "SELECT now()")
        started = time.monotonic()
        subprocess.run(
            compose(args.project)
            + ["up", "-d", "--no-deps", "--scale", f"worker={args.workers}", "worker"],
            check=True,
            capture_output=True,
        )
        ids = ",".join("'" + item["resource_id"] + "'" for item in record["resources"])
        query = (
            "SELECT coalesce(json_agg(r),'[]'::json) FROM (SELECT id,tenant_id,kind,resource_id,state,attempt,worker_id,fencing_token,created_at,started_at,completed_at,error->>'code' AS error_code,extract(epoch FROM(started_at-created_at)) AS queue_seconds,extract(epoch FROM(completed_at-started_at)) AS execution_seconds FROM jobs WHERE resource_id IN("
            + ids
            + ") ORDER BY created_at,id) r"
        )
        while time.monotonic() - started < 180:
            record["jobs"] = json.loads(sql(args.project, query))
            if len(record["jobs"]) == len(record["resources"]) and all(
                row["state"] in {"succeeded", "failed", "cancelled"} for row in record["jobs"]
            ):
                break
            time.sleep(1)
        record["elapsed_from_release_seconds"] = round(time.monotonic() - started, 3)
        if any(row["state"] != "succeeded" for row in record["jobs"]):
            raise RuntimeError(
                "At least one admitted job did not succeed within the observation window."
            )
        verified = []
        for resource in record["resources"]:
            client = authors[resource["tenant"]]
            if resource["kind"] == "ingestion":
                result = request(client, "GET", f"/imports/{resource['resource_id']}")
                if result["state"] != "ready":
                    raise RuntimeError("Completed ingestion is not published.")
                verified.append(
                    {
                        "resource_id": resource["resource_id"],
                        "snapshot_id": result["evidence_snapshot_id"],
                    }
                )
            else:
                response = client.get(f"/api/v1/exports/{resource['resource_id']}/download")
                digest = hashlib.sha256(response.content).hexdigest()
                stored = sql(
                    args.project,
                    "SELECT sha256 FROM exports WHERE tenant_id='"
                    + resource["tenant"]
                    + "' AND id='"
                    + resource["resource_id"]
                    + "'",
                )
                if (
                    response.status_code != 200
                    or digest != stored
                    or "<script>" in response.text
                    or "&lt;script&gt;" not in response.text
                ):
                    raise RuntimeError("Export verification failed.")
                verified.append(
                    {"resource_id": resource["resource_id"], "sha256": digest, "html_escaped": True}
                )
        record["verified"] = verified
        record["provider_calls"] = provider_calls(args.project)
        if record["provider_calls"]:
            raise RuntimeError("Provider calls must remain zero.")
        record["status"] = "passed"
    except Exception as error:
        record["status"] = "failed"
        record["error_type"] = type(error).__name__
        raise
    finally:
        subprocess.run(compose(args.project) + ["stop", "worker"], check=False, capture_output=True)
        for client in clients:
            client.close()
        record["completed_at"] = datetime.now(UTC).isoformat()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
        print(
            json.dumps(
                {
                    key: value
                    for key, value in record.items()
                    if key not in {"jobs", "resources", "verified"}
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
