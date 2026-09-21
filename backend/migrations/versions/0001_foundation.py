"""Identidade, evidências, snapshots, trabalhos e revisões; todas as FKs de conteúdo incluem tenant."""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    sql = Path(__file__).with_suffix(".sql").read_text(encoding="utf-8")
    # Static migration SQL contains both PostgreSQL format('%I') and JSON colons.
    # No bind interpolation is appropriate for this checked-in script.
    op.get_bind().execution_options(no_parameters=True).exec_driver_sql(sql)


def downgrade() -> None:
    raise RuntimeError("Downgrade destrutivo não é automático; restaurar backup verificado.")
