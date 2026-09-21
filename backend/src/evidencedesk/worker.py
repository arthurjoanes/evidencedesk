import signal
import threading
from uuid import uuid4

from opentelemetry.propagate import extract
from opentelemetry.trace import SpanKind, Status, StatusCode
from sqlalchemy import text

from evidencedesk.config import get_settings
from evidencedesk.database import transaction
from evidencedesk.errors import Problem
from evidencedesk.ingestion.processing import process_import
from evidencedesk.jobs.service import Lease, acquire, fail, renew, retry_transient
from evidencedesk.reviews.exporting import process_export
from evidencedesk.telemetry.signals import TRACER, log_event, setup_telemetry


def execute_lease(lease: Lease) -> None:
    stop_renewal = threading.Event()

    def heartbeat() -> None:
        while not stop_renewal.wait(get_settings().job_lease_seconds / 3):
            try:
                if not renew(lease):
                    return
            except Exception as error:
                log_event(
                    "job.renewal_failed", job_id=lease.job_id, error_type=type(error).__name__
                )
                return

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        with TRACER.start_as_current_span(
            f"job.{lease.kind}",
            context=extract(lease.trace_context),
            kind=SpanKind.CONSUMER,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("ed.operation", lease.kind)
            span.set_attribute("ed.job_id", lease.job_id)
            span.set_attribute("ed.fencing_token", lease.token)
            try:
                dispatch(lease)
            except Problem as error:
                span.set_status(Status(StatusCode.ERROR))
                span.set_attribute("error.type", error.code)
                if retry_transient(lease, error.code):
                    log_event(
                        "job.retry_scheduled",
                        job_id=lease.job_id,
                        kind=lease.kind,
                        error_code=error.code,
                    )
                    return
                fail(lease, error.code, error.message)
                log_event("job.failed", job_id=lease.job_id, kind=lease.kind, error_code=error.code)
            except Exception as error:
                span.set_status(Status(StatusCode.ERROR))
                span.set_attribute("error.type", type(error).__name__)
                log_event(
                    "job.failed",
                    job_id=lease.job_id,
                    kind=lease.kind,
                    error_type=type(error).__name__,
                )
                fail(lease, "job_failed", "A etapa falhou. Consulte o diagnóstico operacional.")
                raise
            else:
                log_event("job.completed", job_id=lease.job_id, kind=lease.kind, token=lease.token)
    finally:
        stop_renewal.set()
        thread.join(timeout=2)


def dispatch(lease: Lease) -> None:
    if lease.kind == "ingestion":
        process_import(lease)
    elif lease.kind == "export":
        process_export(lease)
    elif lease.kind == "investigation":
        from evidencedesk.investigations.processing import process_investigation

        process_investigation(lease)
    elif lease.kind == "purge":
        from evidencedesk.evidence.deletion import process_deletion

        process_deletion(lease)
    elif lease.kind == "index_snapshot":
        from evidencedesk.retrieval.jobs import process_index

        process_index(lease)
    else:
        raise Problem(422, "unknown_job", "Tipo de trabalho não suportado.")


def main() -> None:
    setup_telemetry("evidencedesk-worker")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    worker_id = uuid4().hex
    while not stop.is_set():
        with transaction() as connection:
            connection.execute(
                text(
                    "INSERT INTO worker_heartbeats(worker_id) VALUES(:id) ON CONFLICT(worker_id) DO UPDATE SET observed_at=now()"
                ),
                {"id": worker_id},
            )
            tenants = (
                connection.execute(text("SELECT id FROM tenants WHERE enabled ORDER BY id"))
                .scalars()
                .all()
            )
        worked = False
        for tenant in tenants:
            if stop.is_set():
                break
            lease = acquire(tenant, worker_id)
            if lease:
                worked = True
                try:
                    execute_lease(lease)
                except Exception:
                    # Each failure is persisted/logged; one malformed job must not kill polling.
                    continue
        if not worked:
            stop.wait(get_settings().worker_poll_seconds)


if __name__ == "__main__":
    main()
