import secrets
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from opentelemetry.propagate import extract
from opentelemetry.trace import SpanKind, Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from evidencedesk.administration.routes import router as administration_router
from evidencedesk.body_limit import JsonBodyLimit
from evidencedesk.config import get_settings
from evidencedesk.database import get_engine, transaction
from evidencedesk.errors import Problem
from evidencedesk.evidence.routes import router as evidence_router
from evidencedesk.identity.routes import router as identity_router
from evidencedesk.incidents.routes import router as incidents_router
from evidencedesk.ingestion.routes import router as ingestion_router
from evidencedesk.investigations.routes import router as investigations_router
from evidencedesk.retrieval.jobs import router as indexing_router
from evidencedesk.reviews.routes import router as reviews_router
from evidencedesk.telemetry.signals import (
    HTTP_DURATION,
    HTTP_REQUESTS,
    TRACER,
    log_event,
    refresh_database_metrics,
    setup_telemetry,
)

KNOWN_HTTP_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"}
)


def problem_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    retryable: bool = False,
    fields: dict | None = None,
) -> JSONResponse:
    error = {
        "code": code,
        "message": message,
        "request_id": getattr(request.state, "request_id", "unknown"),
        "retryable": retryable,
    }
    if fields:
        error["field_errors"] = fields
    return JSONResponse({"error": error}, status_code=status, headers={"Cache-Control": "no-store"})


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_telemetry("evidencedesk-api")
        yield
        get_engine().dispose()

    app = FastAPI(title="EvidenceDesk", version="0.1.0", lifespan=lifespan)
    app.add_middleware(JsonBodyLimit)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = uuid4().hex
        started = time.perf_counter()
        # Unknown methods remain valid HTTP inputs but must not create arbitrary
        # Prometheus series or span names controlled by an unauthenticated client.
        method = request.method if request.method in KNOWN_HTTP_METHODS else "_OTHER"
        with TRACER.start_as_current_span(
            f"HTTP {method}",
            context=extract(
                {
                    key: value
                    for key, value in request.headers.items()
                    if key in {"traceparent", "tracestate"}
                }
            ),
            kind=SpanKind.SERVER,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("http.request.method", method)
            try:
                response = await call_next(request)
            except Exception as error:
                span.set_attribute("error.type", type(error).__name__)
                response = await unexpected_error(request, error)
            if response.status_code >= 500:
                span.set_status(Status(StatusCode.ERROR))
            route = getattr(request.scope.get("route"), "path", "unmatched")
            duration = time.perf_counter() - started
            HTTP_REQUESTS.labels(
                route=route, method=method, status_class=f"{response.status_code // 100}xx"
            ).inc()
            HTTP_DURATION.labels(route=route, method=method).observe(duration)
            span.set_attribute("http.route", route)
            span.set_attribute("http.response.status_code", response.status_code)
            response.headers["X-Request-ID"] = request.state.request_id
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            log_event(
                "http.completed",
                request_id=request.state.request_id,
                route=route,
                status=response.status_code,
                duration_ms=round(duration * 1000, 2),
            )
            return response

    @app.exception_handler(Problem)
    async def known_problem(request: Request, error: Problem):
        return problem_response(request, error.status, error.code, error.message, error.retryable)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        fields: dict[str, list[str]] = {}
        for detail in error.errors():
            field = ".".join(map(str, detail["loc"][1:]))
            fields.setdefault(field, []).append("Valor inválido ou fora do limite permitido.")
        return problem_response(
            request, 422, "validation_error", "Confira os campos informados.", fields=fields
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        log_event(
            "http.failed",
            request_id=getattr(request.state, "request_id", "unknown"),
            error_type=type(error).__name__,
        )
        return problem_response(
            request,
            500,
            "internal_error",
            "Não foi possível concluir a operação. Use o identificador da requisição para diagnóstico.",
        )

    for router in (
        identity_router,
        incidents_router,
        ingestion_router,
        evidence_router,
        reviews_router,
        investigations_router,
        administration_router,
    ):
        app.include_router(router, prefix="/api/v1")
    app.include_router(indexing_router, prefix="/api/v1")

    @app.get("/api/v1/health/live", tags=["Saúde"])
    def live():
        return {"status": "alive"}

    @app.get("/api/v1/health/ready", tags=["Saúde"])
    def ready():
        with transaction() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT r.rolsuper,r.rolbypassrls,c.maintenance,pg_has_role(current_user,'ed_owner','MEMBER') AS member_owner,EXISTS(SELECT 1 FROM pg_class t WHERE t.relname='evidence' AND t.relowner=r.oid) AS owns_data FROM pg_roles r CROSS JOIN operational_control c WHERE r.rolname=current_user AND c.id=1"
                    )
                )
                .mappings()
                .one()
            )
            if row["rolsuper"] or row["rolbypassrls"] or row["member_owner"] or row["owns_data"]:
                raise Problem(
                    503,
                    "unsafe_database_role",
                    "A credencial de aplicação não está configurada com privilégios mínimos.",
                )
            if row["maintenance"]:
                raise Problem(503, "maintenance", "Manutenção em andamento.", retryable=True)
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request):
        supplied = request.headers.get("authorization", "")
        expected = f"Bearer {get_settings().metrics_token.get_secret_value()}"
        if not secrets.compare_digest(supplied, expected):
            raise Problem(403, "metrics_access_denied", "Acesso administrativo necessário.")
        refresh_database_metrics()
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
