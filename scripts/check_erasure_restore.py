"""Prove post-backup erasure on an existing, isolated capacity dataset; never main."""

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from backup import RESTORE_OVERRIDE, create_backup, verify_restore
from capacity_http import api_targets, capacity_project, compose, provider_calls
from capacity_jobs import login, request, sql
from ops import ROOT, compose_command

PROBE = """
import json, sys
from fastapi.testclient import TestClient
from sqlalchemy import text
from evidencedesk.app import create_app
from evidencedesk.database import transaction
from evidencedesk.evidence.storage import PrivateStorage
from evidencedesk.maintenance import status
p=json.load(sys.stdin)
with TestClient(create_app(),base_url='http://localhost:3106') as client:
    client.cookies.set('ed_session',p['session'])
    codes={name:client.get(path).status_code for name,path in {
        'source':f"/api/v1/evidence/{p['evidence']}?evidence_snapshot_id={p['snapshot']}",
        'original':f"/api/v1/evidence/{p['evidence']}/content?evidence_snapshot_id={p['snapshot']}",
        'dossier':f"/api/v1/dossiers/{p['dossier']}"
    }.items()}
with transaction('aurora') as c:
    row=c.execute(text('SELECT tombstoned_at IS NOT NULL AS tombstoned, canonical_text FROM evidence WHERE id=:id'),{'id':p['evidence']}).mappings().one()
    claims=c.execute(text('SELECT claims FROM dossier_revisions WHERE dossier_id=:id'),{'id':p['dossier']}).scalar_one()
    refs=c.execute(text('SELECT count(*) FROM import_entries WHERE object_key=:key'),{'key':p['object_key']}).scalar_one()
    sequence=c.execute(text('SELECT sequence FROM operational_ledger WHERE id=1')).scalar_one()
result={'http_statuses':codes,'source_tombstoned':row['tombstoned'],
        'source_text_empty':row['canonical_text']=='','derived_claims_empty':claims==[],
        'original_file_absent':not PrivateStorage().path(p['object_key']).exists(),
        'matching_object_references':refs,'ledger_sequence':sequence,'maintenance':status()}
assert all(code==404 for code in codes.values()), result
assert all(result[k] for k in ['source_tombstoned','source_text_empty','derived_claims_empty','original_file_absent']), result
assert refs==0 and sequence==p['sequence'], result
assert result['maintenance']['maintenance'] and result['maintenance']['ledger_ready'], result
print(json.dumps(result))
"""


def execute(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=True, **kwargs)


def wait_resource(client, path, state, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = request(client, "GET", path)
        if result["state"] == state:
            return result
        if result["state"] in {"failed", "cancelled"}:
            raise RuntimeError("Synthetic job did not succeed.")
        time.sleep(0.5)
    raise TimeoutError("Synthetic job exceeded its observation window.")


def close_attempt(record, output, source, target):
    """Try both isolated projects and preserve evidence even when a stop fails."""
    failures = []
    for name, base in (("target", target), ("source", source)):
        if base:
            try:
                execute(base + ["stop"])
            except (OSError, subprocess.CalledProcessError) as error:
                failures.append({"project_role": name, "error_type": type(error).__name__})
    record["containers_stopped"] = not failures
    record["volumes_preserved"] = True
    record["completed_at"] = datetime.now(UTC).isoformat()
    if failures:
        record["status"] = "failed"
        record["cleanup_failures"] = failures
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    print(json.dumps({key: value for key, value in record.items() if key != "steps"}, indent=2))
    if failures:
        raise RuntimeError("Isolated cleanup was incomplete; inspect the saved evidence.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=capacity_project, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Refusing to overwrite evidence.")
    # Explicitly select current code; an older capacity image is not a restore proof.
    os.environ["ED_CAPACITY_IMAGE"] = "pf-evidencedesk-backend:local"
    base = compose(args.project)
    record = {
        "started_at": datetime.now(UTC).isoformat(),
        "source_project": args.project,
        "target_project": args.target,
        "status": "running",
        "steps": {},
    }
    target = None
    client = None
    try:
        execute(base + ["up", "-d", "--wait", "db"])
        if provider_calls(args.project) != 0:
            raise ValueError("Only an isolated source without provider calls is allowed.")
        execute(base + ["run", "--rm", "--no-deps", "migrate"])
        execute(
            base
            + [
                "up",
                "-d",
                "--no-deps",
                "--scale",
                "api=1",
                "--scale",
                "worker=1",
                "--wait",
                "api",
                "worker",
            ]
        )
        tag = uuid4().hex[:12]
        collection = "erasure-" + tag
        sql(
            args.project,
            f"INSERT INTO collections(tenant_id,id,name) VALUES('aurora','{collection}','Synthetic erasure restore'); INSERT INTO collection_grants(tenant_id,collection_id,user_id) VALUES('aurora','{collection}','aurora-admin')",
        )
        client = login(api_targets(args.project, 1)[0], "admin", "aurora")
        content = f"# Synthetic recovery check {tag}\nConfirm payment before releasing an order.\n".encode()
        imported = request(
            client,
            "POST",
            "/imports",
            status=201,
            json={
                "collection_id": collection,
                "manifest": {
                    "schema_version": "1",
                    "title": "Erasure restore fixture",
                    "source_tenant": "aurora",
                    "coverage": [],
                    "entries": [
                        {
                            "entry_id": "doc",
                            "filename": "restore.md",
                            "kind": "document",
                            "media_type": "text/markdown",
                            "byte_size": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "metadata": {
                                "title": "Synthetic procedure",
                                "version": "1",
                                "temporal_role": "historical_artifact",
                            },
                        }
                    ],
                },
            },
        )
        request(
            client,
            "PUT",
            f"/imports/{imported['id']}/files/doc",
            content=content,
            headers={"Content-Type": "text/markdown"},
        )
        request(client, "POST", f"/imports/{imported['id']}/finalize", status=202)
        imported = wait_resource(client, f"/imports/{imported['id']}", "ready")
        snapshot = imported["evidence_snapshot_id"]
        source = json.loads(
            sql(
                args.project,
                f"SELECT row_to_json(e) FROM (SELECT id,original_key FROM evidence WHERE tenant_id='aurora' AND collection_id='{collection}' AND kind='document_span') e",
            )
        )
        incident = request(
            client,
            "POST",
            "/incidents",
            status=201,
            json={
                "title": "Synthetic restore check",
                "collection_id": collection,
                "window": {
                    "from": "2026-08-01T10:00:00Z",
                    "to": "2026-08-01T12:00:00Z",
                    "time_zone": "UTC",
                },
            },
        )
        dossier = request(
            client,
            "POST",
            f"/incidents/{incident['id']}/dossiers",
            status=201,
            json={
                "evidence_snapshot_id": snapshot,
                "summary": "Synthetic evidence to erase",
                "outcome": "evidence_found",
                "claims": [
                    {
                        "kind": "observed_fact",
                        "text": "The procedure mentions payment.",
                        "evidence_links": [{"evidence_id": source["id"], "relation": "supports"}],
                    }
                ],
            },
        )
        read_path = f"/evidence/{source['id']}?evidence_snapshot_id={snapshot}"
        request(client, "GET", read_path)
        record["steps"]["before_backup"] = {
            "source_http_status": 200,
            "ledger_sequence": int(
                sql(args.project, "SELECT sequence FROM operational_ledger WHERE id=1")
            ),
            "source_sha256": hashlib.sha256(content).hexdigest(),
        }
        backup_args = argparse.Namespace(
            project=args.project,
            env_file=None,
            observability=False,
            backup=args.backup,
            target=args.target,
        )
        source_base = compose_command(backup_args)
        record["steps"]["backup"] = create_backup(source_base, args.backup, args.project)
        deletion = request(
            client,
            "DELETE",
            f"/admin/evidence/{source['id']}",
            status=202,
            json={"reason": "user_request"},
            headers={"Idempotency-Key": "erasure-" + tag},
        )
        denied = client.get("/api/v1" + read_path).status_code
        if denied != 404:
            raise AssertionError("Deletion did not deny source access immediately.")
        wait_resource(client, f"/admin/deletions/{deletion['id']}", "succeeded")
        sequence = int(sql(args.project, "SELECT sequence FROM operational_ledger WHERE id=1"))
        if sequence <= record["steps"]["before_backup"]["ledger_sequence"]:
            raise AssertionError("The external deletion ledger did not advance.")
        record["steps"]["after_deletion"] = {
            "source_http_status": denied,
            "purge_state": "succeeded",
            "ledger_sequence": sequence,
        }
        record["steps"]["restore"] = verify_restore(source_base, backup_args)
        target = compose_command(
            argparse.Namespace(project=args.target, env_file=None, observability=False)
        ) + ["--file", str(RESTORE_OVERRIDE)]
        execute(["docker", "start", args.target + "-db-1"])
        probe_input = {
            "evidence": source["id"],
            "snapshot": snapshot,
            "dossier": dossier["id"],
            "object_key": source["original_key"],
            "sequence": sequence,
            "session": client.cookies.get("ed_session"),
        }
        checked = execute(
            target + ["run", "--rm", "--no-deps", "-T", "api", "python", "-c", PROBE],
            input=json.dumps(probe_input),
            text=True,
            encoding="utf-8",
        )
        record["steps"]["restored_read_and_bytes"] = json.loads(checked.stdout)
        record["provider_calls"] = provider_calls(args.project)
        if record["provider_calls"] != 0:
            raise AssertionError("Provider calls must remain zero.")
        record["status"] = "passed"
    except Exception as error:
        record["status"] = "failed"
        record["error_type"] = type(error).__name__
        if isinstance(error, subprocess.CalledProcessError):
            print(
                (error.stderr or b"").decode() if isinstance(error.stderr, bytes) else error.stderr
            )
        raise
    finally:
        if client:
            client.close()
        close_attempt(record, args.output, base, target)


if __name__ == "__main__":
    main()
