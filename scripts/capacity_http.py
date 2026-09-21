"""Bounded open-loop reads against an explicitly isolated capacity Compose project."""

import argparse
import asyncio
import json
import math
import re
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx
from ops import COMPOSE, ROOT

CAPACITY = ROOT / "infra/compose/capacity.yaml"
DEMO_PASSWORD = "EvidenceDesk-demo-2026!"
USERS = {"aurora": "ana", "horizonte": "carla"}


def capacity_project(value):
    if not re.fullmatch(r"pf-evidencedesk-capacity-[a-z0-9][a-z0-9-]{0,25}", value):
        raise argparse.ArgumentTypeError("An isolated pf-evidencedesk-capacity-<run> is required.")
    return value


def compose(project):
    return [
        "docker",
        "compose",
        "--project-name",
        capacity_project(project),
        "--file",
        str(COMPOSE),
        "--file",
        str(CAPACITY),
    ]


def capture(command):
    return subprocess.check_output(command, cwd=ROOT, text=True, encoding="utf-8").strip()


def api_targets(project, replicas):
    targets = []
    for number in range(1, replicas + 1):
        address = capture(compose(project) + ["port", "--index", str(number), "api", "8106"])
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", address):
            raise ValueError("Capacity endpoints must be unambiguous loopback bindings.")
        targets.append("http://" + address)
    return targets


def provider_calls(project):
    return int(
        capture(
            compose(project)
            + [
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "postgres",
                "-d",
                "evidencedesk",
                "-At",
                "-c",
                "SELECT count(*) FROM provider_calls",
            ]
        )
    )


def percentiles(values):
    if not values:
        return None
    ordered = sorted(values)
    return {
        f"p{percent}": round(ordered[max(0, math.ceil(percent / 100 * len(ordered)) - 1)], 3)
        for percent in (50, 95, 99)
    }


def summarize(rows):
    attempted = [row for row in rows if row["status"] != "client_limit"]
    successful = [row for row in attempted if row["status"] == "200"]
    return {
        "offered": len(rows),
        "attempted": len(attempted),
        "successful": len(successful),
        "statuses": dict(Counter(row["status"] for row in rows)),
        "success_fraction_of_offered": len(successful) / len(rows) if rows else None,
        "latency_ms_all_attempts": percentiles([row["latency_ms"] for row in attempted]),
        "latency_ms_successes": percentiles([row["latency_ms"] for row in successful]),
        "scheduler_lag_ms": percentiles([row["scheduler_lag_ms"] for row in rows]),
    }


async def authenticate(client, user, tenant):
    response = await client.post(
        "/api/v1/auth/login", json={"email": f"{user}@{tenant}.demo", "password": DEMO_PASSWORD}
    )
    response.raise_for_status()
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


async def run_reads(args):
    targets = api_targets(args.project, args.replicas)
    if provider_calls(args.project) != 0:
        raise ValueError("The capacity database must have no provider calls.")
    clients = {}
    rows = []
    try:
        for replica, target in enumerate(targets):
            for tenant, user in USERS.items():
                client = httpx.AsyncClient(
                    base_url=target,
                    headers={"Origin": "http://localhost:3106"},
                    timeout=httpx.Timeout(12, connect=3, pool=1),
                    trust_env=False,
                    limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
                )
                clients[(replica, tenant)] = client
                await authenticate(client, user, tenant)
                response = await client.get("/api/v1/collections")
                response.raise_for_status()
        tasks = set()
        started_at = datetime.now(UTC).isoformat()
        started = time.perf_counter()

        async def request(index, scheduled):
            replica, tenant = (index // 2) % args.replicas, list(USERS)[index % 2]
            paths = [
                "/api/v1/collections",
                "/api/v1/incidents?limit=5",
                f"/api/v1/incidents/demo-{tenant}-01",
                "/api/v1/imports?limit=5",
            ]
            path = paths[(index // (2 * args.replicas)) % len(paths)]
            now = time.perf_counter()
            row = {
                "replica": replica + 1,
                "tenant": tenant,
                "route": path.replace(tenant, "{tenant}"),
                "scheduler_lag_ms": (now - scheduled) * 1000,
            }
            try:
                response = await clients[(replica, tenant)].get(path)
                row["status"] = str(response.status_code)
                row["response_bytes"] = len(response.content)
            except httpx.TimeoutException:
                row["status"] = "timeout"
            except httpx.HTTPError:
                row["status"] = "connection_error"
            row["latency_ms"] = (time.perf_counter() - now) * 1000
            rows.append(row)

        for index in range(round(args.rate * args.seconds)):
            scheduled = started + index / args.rate
            await asyncio.sleep(max(0, scheduled - time.perf_counter()))
            if len(tasks) >= args.max_inflight:
                rows.append(
                    {
                        "replica": (index // 2) % args.replicas + 1,
                        "tenant": list(USERS)[index % 2],
                        "route": "not_sent",
                        "status": "client_limit",
                        "scheduler_lag_ms": (time.perf_counter() - scheduled) * 1000,
                    }
                )
                continue
            task = asyncio.create_task(request(index, scheduled))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        if tasks:
            await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - started
        if provider_calls(args.project) != 0:
            raise ValueError("Unexpected provider call in a capacity run.")
        return {
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "project": args.project,
            "kind": "bounded-open-loop-http-reads",
            "replicas": args.replicas,
            "rate_offered_rps": args.rate,
            "offering_seconds": args.seconds,
            "elapsed_including_drain_seconds": round(elapsed, 3),
            "max_inflight": args.max_inflight,
            "warmup": "one authenticated collections read per replica/tenant; login excluded",
            "distribution": "explicit equal routing to each replica; no load balancer is under test",
            "provider_calls": 0,
            "summary": summarize(rows),
            "per_tenant": {
                tenant: summarize([row for row in rows if row["tenant"] == tenant])
                for tenant in USERS
            },
            "per_replica": {
                str(replica + 1): summarize([row for row in rows if row["replica"] == replica + 1])
                for replica in range(args.replicas)
            },
            "samples": rows,
        }
    finally:
        for client in clients.values():
            await client.aclose()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--project", type=capacity_project, required=True)
    cli.add_argument("--replicas", type=int, choices=(1, 2), required=True)
    cli.add_argument("--rate", type=int, choices=range(1, 31), default=10, metavar="1..30")
    cli.add_argument("--seconds", type=int, choices=range(5, 61), default=20, metavar="5..60")
    cli.add_argument("--max-inflight", type=int, choices=range(1, 33), default=32, metavar="1..32")
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    record = asyncio.run(run_reads(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({key: value for key, value in record.items() if key != "samples"}, indent=2))


if __name__ == "__main__":
    main()
