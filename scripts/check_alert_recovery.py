"""Finite local fault exercises, with scoped synthetic queue and unconditional recovery."""

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from ops import ROOT

BASE = [
    "docker",
    "compose",
    "--file",
    str(ROOT / "infra/compose/compose.yaml"),
    "--file",
    str(ROOT / "infra/compose/observability.yaml"),
]


def docker(*args):
    # Compose start follows depends_on and can rerun an old migration container.
    # Resume only the exact existing runtime containers, retaining their environment.
    if args[0] == "start":
        if not set(args[1:]) <= {"worker", "collector", "models"}:
            raise ValueError("Unexpected service in recovery.")
        command = ["docker", "start", *["pf-evidencedesk-" + name + "-1" for name in args[1:]]]
    else:
        command = [*BASE, *args]
    return subprocess.check_output(
        command, cwd=ROOT, text=True, encoding="utf-8", stderr=subprocess.STDOUT
    ).strip()


def sql(statement):
    return docker(
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
    )


def deliveries(since):
    with httpx.Client(timeout=5) as client:
        response = client.get("http://127.0.0.1:9187/events")
        response.raise_for_status()
        return [row for row in response.json()["events"] if row["received_at"] >= since]


def wait_for_alerts(names, state, since, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = deliveries(since)
        seen = {
            alert["labels"]["alertname"]
            for row in rows
            for alert in row["alerts"]
            if alert["status"] == state
        }
        if names <= seen:
            return rows
        time.sleep(5)
    raise RuntimeError("Timed out waiting for " + state + ": " + ",".join(sorted(names - seen)))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--scenario", choices=["worker-queue-collector", "model"], required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists():
        raise ValueError("Refusing to overwrite evidence.")
    services = ["worker", "collector"] if args.scenario == "worker-queue-collector" else ["models"]
    names = (
        {"EvidenceDeskWorkerMissing", "EvidenceDeskQueueAging", "EvidenceDeskCollectorUnavailable"}
        if len(services) == 2
        else {"EvidenceDeskModelUnavailable"}
    )
    # Refuse to "recover" a service which was already stopped before this exercise.
    for service in services:
        state = json.loads(
            subprocess.check_output(
                ["docker", "inspect", "pf-evidencedesk-" + service + "-1"], text=True
            )
        )[0]
        if not state["State"]["Running"]:
            raise ValueError(service + " must be running before the exercise.")
    start = datetime.now(UTC).isoformat()
    record = {
        "started_at": start,
        "scenario": args.scenario,
        "project": "pf-evidencedesk",
        "status": "running",
        "services": services,
        "thresholds_modified": False,
        "new_generation_requests": 0,
    }
    tenant = "ops-probe-" + uuid4().hex
    fixture = False
    initial_calls = int(sql("SELECT count(*) FROM provider_calls"))
    try:
        docker("stop", *services)
        if args.scenario == "worker-queue-collector":
            # New, declared fixture only. Real rows/timestamps are never aged or repurposed.
            sql(
                f"BEGIN; INSERT INTO tenants(id,name) VALUES('{tenant}','Synthetic operational fault probe'); INSERT INTO tenant_policy(tenant_id) VALUES('{tenant}'); INSERT INTO users(id,tenant_id,email,name,password_hash,role,enabled) VALUES('{tenant}','{tenant}','{tenant}@invalid.local','Synthetic non-login actor','not-a-password','analyst',false); INSERT INTO jobs(tenant_id,id,kind,resource_id,actor_id,deadline,available_at,policy_revision) VALUES('{tenant}','queue-probe','export','non-executable-probe','{tenant}',now()+interval '15 minutes',now()+interval '1 hour',1); COMMIT;"
            )
            fixture = True
            record["synthetic_tenant_id"] = tenant
        record["firing_deliveries"] = wait_for_alerts(names, "firing", start, 210)
        record["firing_observed_at"] = datetime.now(UTC).isoformat()
        print("All requested alerts delivered firing.", flush=True)
    except Exception as error:
        record["status"] = "failed"
        record["error_type"] = type(error).__name__
        record["error_code"] = "fault_exercise_failed"
        raise
    finally:
        try:
            try:
                if fixture:
                    sql(
                        f"BEGIN; DELETE FROM jobs WHERE tenant_id='{tenant}' AND id='queue-probe'; DELETE FROM users WHERE tenant_id='{tenant}'; DELETE FROM tenant_policy WHERE tenant_id='{tenant}'; DELETE FROM tenants WHERE id='{tenant}'; COMMIT;"
                    )
            finally:
                # Reuse the existing env, including Azure context, even if fixture cleanup fails.
                docker("start", *services)
            record["recovery_started_at"] = datetime.now(UTC).isoformat()
            if record.get("firing_deliveries"):
                record["resolved_deliveries"] = wait_for_alerts(
                    names, "resolved", record["recovery_started_at"], 120
                )
            record["provider_calls_before"] = initial_calls
            record["provider_calls_after"] = int(sql("SELECT count(*) FROM provider_calls"))
            if record["provider_calls_after"] != initial_calls:
                raise RuntimeError("Unexpected provider call count change.")
            record["api_readiness_http"] = httpx.get(
                "http://127.0.0.1:8106/api/v1/health/ready", timeout=5
            ).status_code
            record["synthetic_fixture_removed"] = (
                not fixture or sql(f"SELECT count(*) FROM tenants WHERE id='{tenant}'") == "0"
            )
            if record["api_readiness_http"] != 200 or not record["synthetic_fixture_removed"]:
                raise RuntimeError("Recovery verification failed.")
            if record["status"] != "failed":
                record["status"] = "passed"
        except Exception as error:
            record["status"] = "failed"
            record["error_type"] = type(error).__name__
            record["error_code"] = "recovery_verification_failed"
            raise
        finally:
            record["completed_at"] = datetime.now(UTC).isoformat()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {k: v for k, v in record.items() if not k.endswith("_deliveries")},
                    ensure_ascii=False,
                    indent=2,
                )
            )


if __name__ == "__main__":
    main()
