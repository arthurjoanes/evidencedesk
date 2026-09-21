import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from fastapi.testclient import TestClient
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

from evidencedesk.telemetry.signals import PersistedProviderFailures, safe_event


def test_unknown_http_methods_have_bounded_metric_labels(monkeypatch):
    from evidencedesk import app

    registry = CollectorRegistry()
    requests = Counter(
        "review_http_requests", "Requests", ["route", "method", "status_class"], registry=registry
    )
    duration = Histogram("review_http_duration", "Duration", ["route", "method"], registry=registry)
    monkeypatch.setattr(app, "HTTP_REQUESTS", requests)
    monkeypatch.setattr(app, "HTTP_DURATION", duration)
    client = TestClient(app.create_app())
    try:
        assert client.get("/api/v1/health/live").status_code == 200
        for method in ("BREW", "ATTACKER-CONTROLLED-UNIQUE-METHOD"):
            assert client.request(method, "/api/v1/health/live").status_code == 405
    finally:
        client.close()
    metrics = generate_latest(registry).decode()
    assert 'method="GET"' in metrics
    assert 'method="_OTHER"' in metrics
    assert "BREW" not in metrics and "ATTACKER" not in metrics


def test_logs_only_keep_bounded_operational_fields():
    assert safe_event(
        "http.completed",
        {
            "request_id": "req-123",
            "route": "/api/v1/evidence/{evidence_id}",
            "status": 200,
            "duration_ms": 12.5,
            "question": "private question",
            "exception": "credential in exception",
            "headers": {"Authorization": "private token"},
            "outcome": "line\ninjection",
            "token": True,
        },
    ) == {
        "event": "http.completed",
        "request_id": "req-123",
        "route": "/api/v1/evidence/{evidence_id}",
        "status": 200,
        "duration_ms": 12.5,
    }
    assert safe_event("unsafe event", {"route": "/search?q=private", "status": float("nan")}) == {
        "event": "invalid_event"
    }


def test_persisted_counter_does_not_add_the_same_rows_on_each_scrape():
    registry = CollectorRegistry()
    failures = PersistedProviderFailures()
    registry.register(failures)
    failures.timeouts = 3
    first = generate_latest(registry)
    assert b'ed_provider_failures_total{outcome="timeout"} 3.0' in first
    assert generate_latest(registry) == first
    failures.timeouts = 4
    assert b'ed_provider_failures_total{outcome="timeout"} 4.0' in generate_latest(registry)


def test_real_otlp_http_export_preserves_correlation_without_raw_content():
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received[self.path] = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    environment = dict(
        os.environ, OTEL_EXPORTER_OTLP_ENDPOINT=f"http://127.0.0.1:{server.server_port}"
    )
    code = """
import json
from evidencedesk.telemetry.signals import TRACER, setup_telemetry, log_event, flush_telemetry
setup_telemetry('telemetry-test')
setup_telemetry('must-not-add-another-exporter')
with TRACER.start_as_current_span('operational.probe', record_exception=False) as span:
    span.set_attribute('ed.operation', 'exporter_test')
    log_event('probe.completed', request_id='probe-123', outcome='ok',
              question='DO-NOT-EXPORT-QUESTION', exception='DO-NOT-EXPORT-SECRET')
    print(json.dumps({'trace_id': f'{span.get_span_context().trace_id:032x}'}))
flush_telemetry()
"""
    try:
        process = subprocess.run(
            [sys.executable, "-c", code],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert set(received) == {"/v1/traces", "/v1/logs"}
    for output in [*received.values(), process.stderr.encode()]:
        assert b"DO-NOT-EXPORT" not in output
    traces = ExportTraceServiceRequest.FromString(received["/v1/traces"])
    logs = ExportLogsServiceRequest.FromString(received["/v1/logs"])
    span = traces.resource_spans[0].scope_spans[0].spans[0]
    record = logs.resource_logs[0].scope_logs[0].log_records[0]
    assert span.trace_id == record.trace_id
    assert span.span_id == record.span_id
    assert span.trace_id.hex() == json.loads(process.stdout)["trace_id"]
    assert record.body.string_value == "probe.completed"
    assert {attribute.key for attribute in record.attributes} == {
        "ed.event",
        "ed.request_id",
        "ed.outcome",
    }
    assert {attribute.key for attribute in logs.resource_logs[0].resource.attributes} == {
        "service.name",
        "service.version",
        "deployment.environment.name",
    }
