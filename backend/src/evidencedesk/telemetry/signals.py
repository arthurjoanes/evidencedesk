import json
import logging
import os
import re
import shutil
import time
from datetime import UTC, datetime
from threading import Lock

from opentelemetry import trace
from prometheus_client import REGISTRY, Counter, Gauge, Histogram
from prometheus_client.core import CounterMetricFamily
from sqlalchemy import text

from evidencedesk.config import get_settings
from evidencedesk.database import transaction

HTTP_REQUESTS = Counter(
    "ed_http_requests_total",
    "HTTP por rota, método e classe de status",
    ["route", "method", "status_class"],
)
HTTP_DURATION = Histogram("ed_http_request_duration_seconds", "Duração HTTP", ["route", "method"])
QUEUE_AGE = Gauge("ed_job_oldest_queued_seconds", "Idade do job aguardando execução mais antigo")
WORKER_HEARTBEAT = Gauge("ed_worker_heartbeat_timestamp_seconds", "Último heartbeat de worker")
BUDGET = Gauge("ed_budget_utilization_ratio", "Fração máxima de orçamento comprometido por tenant")
STORAGE_FREE = Gauge("ed_storage_free_bytes", "Bytes livres no armazenamento local")
INGESTION_PUBLISHED = Gauge(
    "ed_ingestion_last_published_timestamp_seconds", "Última publicação de corpus"
)
INGESTION_PENDING = Gauge("ed_ingestion_pending_batches", "Importações seladas ou em processamento")
QUALITY_GATE = Gauge(
    "ed_quality_gate",
    "Estado do gate; ausência de adjudicação não equivale a aprovação",
    ["status"],
)
QUALITY_EVALUATED = Gauge(
    "ed_quality_evaluated_timestamp_seconds", "Data da última avaliação válida"
)
PROVIDER_CALLS = Gauge(
    "ed_provider_call_records", "Estoque de chamadas persistidas por estado de consumo", ["state"]
)
LOGGER = logging.getLogger("evidencedesk")
TRACER = trace.get_tracer("evidencedesk", "0.1.0")
_setup_lock = Lock()
_log_provider = None
_otel_logger = None
_trace_provider = None


class PersistedProviderFailures:
    """Repeated scrapes expose the DB total instead of incrementing a process counter."""

    def __init__(self):
        self.timeouts = 0

    def collect(self):
        metric = CounterMetricFamily(
            "ed_provider_failures", "Falhas de tentativas persistidas", labels=["outcome"]
        )
        metric.add_metric(["timeout"], self.timeouts)
        yield metric


PROVIDER_FAILURES = PersistedProviderFailures()
REGISTRY.register(PROVIDER_FAILURES)


def setup_telemetry(service_name: str) -> None:
    global _log_provider, _otel_logger, _trace_provider
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    with _setup_lock:
        if _trace_provider is not None:
            return
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource(
            {
                "service.name": service_name,
                "service.version": "0.1.0",
                "deployment.environment.name": "local-lab",
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces", timeout=3),
                max_queue_size=512,
                max_export_batch_size=64,
            )
        )
        trace.set_tracer_provider(provider)
        _trace_provider = provider
        _log_provider = LoggerProvider(resource=resource)
        _log_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(endpoint=f"{endpoint.rstrip('/')}/v1/logs", timeout=3),
                max_queue_size=512,
                max_export_batch_size=64,
            )
        )
        _otel_logger = _log_provider.get_logger("evidencedesk", "0.1.0")


def safe_event(event: str, fields: dict) -> dict:
    payload = {"event": event if re.fullmatch(r"[a-z][a-z0-9_.]{0,63}", event) else "invalid_event"}
    identifiers = {
        "request_id",
        "job_id",
        "run_id",
        "error_code",
        "error_type",
        "kind",
        "operation",
        "outcome",
    }
    for key, value in fields.items():
        if (
            key in identifiers
            and isinstance(value, str)
            and re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", value)
        ):
            payload[key] = value
        elif (
            key == "route"
            and isinstance(value, str)
            and re.fullmatch(r"[/a-zA-Z0-9_{}.-]{1,160}", value)
        ):
            payload[key] = value
        elif (
            key in {"status", "duration_ms", "token"}
            and type(value) in (int, float)
            and 0 <= value < 10**12
        ):
            payload[key] = value
    return payload


def log_event(event: str, **fields: str | int | float | None) -> None:
    # Both stdout and OTLP use this allowlist; redaction is not deferred to the collector.
    payload = safe_event(event, fields)
    context = trace.get_current_span().get_span_context()
    correlation = (
        {"trace_id": f"{context.trace_id:032x}", "span_id": f"{context.span_id:016x}"}
        if context.is_valid
        else {}
    )
    LOGGER.info(
        json.dumps(
            {"timestamp": datetime.now(UTC).isoformat(), **payload, **correlation},
            ensure_ascii=True,
        )
    )
    if _otel_logger is not None:
        from opentelemetry._logs import LogRecord, SeverityNumber

        names = {
            "event": "ed.event",
            "request_id": "ed.request_id",
            "job_id": "ed.job_id",
            "run_id": "ed.run_id",
            "error_code": "ed.code",
            "error_type": "error.type",
            "kind": "ed.operation",
            "operation": "ed.operation",
            "outcome": "ed.outcome",
            "route": "http.route",
            "status": "http.response.status_code",
            "duration_ms": "ed.duration_ms",
            "token": "ed.fencing_token",
        }
        _otel_logger.emit(
            LogRecord(
                timestamp=time.time_ns(),
                severity_number=SeverityNumber.INFO,
                severity_text="INFO",
                body=payload["event"],
                attributes={names[key]: value for key, value in payload.items()},
            )
        )


def flush_telemetry(timeout_millis: int = 3000) -> None:
    """Used by a finite operational probe before its process exits."""
    if _trace_provider is not None:
        _trace_provider.force_flush(timeout_millis=timeout_millis)
    if _log_provider is not None:
        _log_provider.force_flush(timeout_millis=timeout_millis)


def refresh_database_metrics() -> None:
    from evidencedesk.investigations.budget import budget_position

    with transaction() as connection:
        tenants = connection.execute(text("SELECT id FROM tenants WHERE enabled")).scalars().all()
        heartbeat = connection.execute(
            text("SELECT extract(epoch FROM max(observed_at)) FROM worker_heartbeats")
        ).scalar()
    age, published, utilization = 0.0, 0.0, 0.0
    pending = timeouts = 0
    calls: dict[str, int] = {}
    for tenant in tenants:
        with transaction(tenant) as connection:
            value = connection.execute(
                text(
                    "SELECT coalesce(extract(epoch FROM (now()-min(created_at))),0) FROM jobs WHERE state IN ('queued','retry_wait')"
                )
            ).scalar_one()
            age = max(age, float(value))
            value = connection.execute(
                text(
                    "SELECT coalesce(extract(epoch FROM max(published_at)),0) FROM evidence_snapshots"
                )
            ).scalar_one()
            published = max(published, float(value))
            pending += connection.execute(
                text("SELECT count(*) FROM import_batches WHERE state IN('sealed','processing')")
            ).scalar_one()
            timeouts += connection.execute(
                text("SELECT count(*) FROM provider_calls WHERE error_code='provider_timeout'")
            ).scalar_one()
            value = budget_position(connection, tenant).committed_tokens
            utilization = max(utilization, value / get_settings().ai_period_token_budget)
            for status, count in connection.execute(
                text("SELECT status,count(*) FROM provider_calls GROUP BY status")
            ):
                calls[status] = calls.get(status, 0) + count
    QUEUE_AGE.set(age)
    WORKER_HEARTBEAT.set(float(heartbeat or 0))
    BUDGET.set(utilization)
    INGESTION_PUBLISHED.set(published)
    INGESTION_PENDING.set(pending)
    PROVIDER_FAILURES.timeouts = timeouts
    get_settings().storage_root.mkdir(parents=True, exist_ok=True)
    STORAGE_FREE.set(shutil.disk_usage(get_settings().storage_root).free)
    QUALITY_GATE.labels(status="unknown").set(1)
    QUALITY_EVALUATED.set(0)
    for status in ("reserved", "dispatched", "reported", "estimated", "unknown", "released"):
        PROVIDER_CALLS.labels(state=status).set(calls.get(status, 0))
