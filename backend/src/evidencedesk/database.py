from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import TimeoutError as PoolTimeout

from evidencedesk.config import get_settings
from evidencedesk.errors import Problem


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.pool_size,
        max_overflow=0,
        pool_timeout=5,
        pool_pre_ping=True,
        connect_args={"options": "-c statement_timeout=10000 -c lock_timeout=3000"},
    )


@contextmanager
def transaction(tenant_id: str | None = None) -> Iterator[Connection]:
    try:
        with get_engine().begin() as connection:
            if tenant_id is not None:
                connection.execute(
                    text("SELECT set_config('ed.tenant_id', :tenant, true)"), {"tenant": tenant_id}
                )
            yield connection
    except PoolTimeout:
        raise Problem(
            503, "database_busy", "Serviço ocupado. Tente novamente depois.", retryable=True
        ) from None


def lock_policy(connection: Connection, tenant_id: str, *, mutation: bool = False) -> int:
    # Lock order: maintenance -> tenant policy -> entity/job. Revocation follows it too.
    mode = connection.execute(
        text("SELECT maintenance FROM operational_control WHERE id=1 FOR SHARE")
    ).scalar_one()
    if mode and mutation:
        raise Problem(
            503, "maintenance", "Manutenção em andamento. Tente novamente depois.", retryable=True
        )
    revision = connection.execute(
        text("SELECT revision FROM tenant_policy WHERE tenant_id=:tenant FOR UPDATE"),
        {"tenant": tenant_id},
    ).scalar_one()
    return revision
