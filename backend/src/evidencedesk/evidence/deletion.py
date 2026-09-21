from sqlalchemy import text

from evidencedesk.database import transaction
from evidencedesk.errors import Problem
from evidencedesk.jobs.service import Lease, assert_publishable, complete
from evidencedesk.retention.cleanup import complete_cleanup


def process_deletion(lease: Lease) -> None:
    with transaction(lease.tenant_id) as connection:
        assert_publishable(connection, lease)
        deletion = dict(
            connection.execute(
                text("SELECT * FROM deletion_requests WHERE tenant_id=:tenant AND id=:id"),
                {"tenant": lease.tenant_id, "id": lease.resource_id},
            )
            .mappings()
            .one()
        )
    with transaction(lease.tenant_id) as connection:
        assert_publishable(connection, lease)
        outcome = complete_cleanup(connection, lease.tenant_id, deletion["cleanup_id"])
        if outcome["state"] != "completed":
            failure = True
        else:
            failure = False
            connection.execute(
                text(
                    "UPDATE deletion_requests SET state='completed',completed_at=now(),object_keys='[]',reserved_bytes=0 WHERE tenant_id=:tenant AND id=:id AND completed_at IS NULL"
                ),
                {"tenant": lease.tenant_id, "id": lease.resource_id},
            )
            complete(connection, lease)
    if failure:
        raise Problem(
            503,
            "storage_unavailable",
            "A remoção dos arquivos será tentada novamente.",
            retryable=True,
        )
