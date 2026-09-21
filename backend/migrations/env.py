from alembic import context
from sqlalchemy import create_engine

from evidencedesk.config import get_settings

settings = get_settings()
if settings.migration_database_url is None:
    raise RuntimeError("ED_MIGRATION_DATABASE_URL é obrigatória; não migrar com a credencial da API.")
engine = create_engine(settings.migration_database_url.get_secret_value())
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
