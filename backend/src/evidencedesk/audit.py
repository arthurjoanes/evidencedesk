import json
from uuid import uuid4

from sqlalchemy import Connection, text

from evidencedesk.identity.service import Actor


def record_action(
    connection: Connection,
    actor: Actor,
    action: str,
    resource_id: str,
    revision: int,
    metadata: dict | None = None,
) -> None:
    connection.execute(
        text("""
        INSERT INTO audit_events(tenant_id,id,actor_id,action,resource_id,policy_revision,metadata)
        VALUES(:tenant,:id,:actor,:action,:resource,:revision,CAST(:metadata AS jsonb))
    """),
        {
            "tenant": actor.tenant_id,
            "id": uuid4().hex,
            "actor": actor.id,
            "action": action,
            "resource": resource_id,
            "revision": revision,
            "metadata": json.dumps(metadata or {}),
        },
    )
