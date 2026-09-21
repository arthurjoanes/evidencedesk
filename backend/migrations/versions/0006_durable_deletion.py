"""Physical deletion survives worker restarts after the tombstone commits."""

from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE deletion_requests ADD object_keys jsonb NOT NULL DEFAULT '[]', ADD reserved_bytes bigint NOT NULL DEFAULT 0 CHECK(reserved_bytes>=0), ADD completed_at timestamptz"
    )


def downgrade() -> None:
    raise RuntimeError("Reversão destrutiva exige restore verificado.")
