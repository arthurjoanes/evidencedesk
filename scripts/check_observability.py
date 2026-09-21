"""Finite, read-only runtime checks inside the project's Docker network.

Run with compose run --rm --no-deps -v <repo>/scripts:/ops:ro api
python /ops/check_observability.py. Standard output is a content-free JSON record.
"""

import json
import os
import time
from datetime import UTC, datetime

import httpx


def wait_for_trace(client, trace_id, *, attempts=15, pause=time.sleep):
    # Logs and spans use independent exporters. A visible log does not mean Tempo has its span yet.
    for attempt in range(attempts):
        response = client.get(
            f"http://tempo:3200/api/traces/{trace_id}", headers={"Accept": "application/json"}
        )
        if response.status_code != 404 or attempt == attempts - 1:
            response.raise_for_status()
            return response
        pause(2)
    raise AssertionError("Trace wait must have at least one attempt.")


def collect():
    started = datetime.now(UTC).isoformat()
    with httpx.Client(timeout=8, trust_env=False) as client:
        response = client.get(
            "http://api:8106/api/v1/health/live", params={"probe": "PRIVATE_QUERY_MUST_NOT_LEAK"}
        )
        response.raise_for_status()
        request_id = response.headers["x-request-id"]
        unauthenticated = client.get("http://api:8106/metrics")
        assert unauthenticated.status_code == 403
        metrics = client.get(
            "http://api:8106/metrics",
            headers={"Authorization": "Bearer " + os.environ["ED_METRICS_TOKEN"]},
        )
        metrics.raise_for_status()
        assert "ed_provider_failures_total" in metrics.text
        targets = client.get("http://prometheus:9090/api/v1/targets").json()["data"][
            "activeTargets"
        ]
        target_states = {target["labels"]["job"]: target["health"] for target in targets}
        assert (
            target_states["api"]
            == target_states["readiness"]
            == target_states["collector-health"]
            == "up"
        )
        assert client.get("http://api:8106/api/v1/health/ready").status_code == 200
        probe = client.get(
            "http://prometheus:9090/api/v1/query",
            params={"query": 'probe_success{job=~"readiness|collector-health"}'},
        ).json()
        assert {item["metric"]["job"] for item in probe["data"]["result"]} == {
            "readiness",
            "collector-health",
        }
        assert all(float(item["value"][1]) == 1 for item in probe["data"]["result"])
        assert client.get("http://loki:3100/ready").status_code == 200
        assert client.get("http://tempo:3200/ready").status_code == 200
        assert client.get("http://grafana:3000/api/health").json()["database"] == "ok"
        trace_id = None
        # SDK + collector batches are asynchronous; polling is bounded to 30 seconds.
        for _ in range(15):
            logs = client.get(
                "http://loki:3100/loki/api/v1/query_range",
                params={"query": '{service_name="evidencedesk-api"}', "limit": 200},
            )
            logs.raise_for_status()
            encoded = json.dumps(logs.json())
            assert "PRIVATE_QUERY_MUST_NOT_LEAK" not in encoded
            for stream in logs.json()["data"]["result"]:
                for entry in stream["values"]:
                    # Loki versions may return structured metadata flattened into the stream.
                    metadata = stream["stream"] | (entry[2] if len(entry) > 2 else {})
                    if metadata.get("ed_request_id") == request_id:
                        assert entry[1] == "structured application event"
                        trace_id = metadata.get("trace_id")
            if trace_id:
                break
            time.sleep(2)
        assert trace_id, "Application request was not found in Loki with its trace correlation."
        trace = wait_for_trace(client, trace_id)
        assert "PRIVATE_QUERY_MUST_NOT_LEAK" not in trace.text
        assert "/api/v1/health/live" in trace.text
        deliveries = client.get("http://receiver:9187/events").json()["events"]
        quality_unknown = any(
            alert["labels"].get("alertname") == "EvidenceDeskQualityUnknown"
            and alert["status"] == "firing"
            for delivery in deliveries
            for alert in delivery["alerts"]
        )
        assert quality_unknown, "Unknown quality must produce a real alert delivery."
        return {
            "started_at": started,
            "completed_at": datetime.now(UTC).isoformat(),
            "status": "passed",
            "project": "pf-evidencedesk",
            "scope": "application HTTP -> SDK -> collector -> Loki/Tempo; Prometheus -> Alertmanager -> receiver",
            "request_id": request_id,
            "trace_id": trace_id,
            "checks": {
                "metrics_require_bearer": True,
                "prometheus_targets": target_states,
                "loki_log_and_tempo_trace_correlated": True,
                "query_marker_absent_from_telemetry": True,
                "grafana_database_healthy": True,
                "quality_unknown_delivered": quality_unknown,
            },
            "limits": "This check does not adjudicate model quality or establish availability SLOs.",
        }


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
