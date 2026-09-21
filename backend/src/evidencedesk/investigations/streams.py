from uuid import uuid4

from sqlalchemy import text

from evidencedesk.database import transaction
from evidencedesk.errors import Problem

MAX_STREAMS = 32
MAX_USER_STREAMS = 2
ADMISSION_LOCK = 9146206


def reserve_stream(user_id: str) -> str:
    token = uuid4().hex
    with transaction() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMISSION_LOCK})
        connection.execute(text("DELETE FROM stream_leases WHERE expires_at<=now()"))
        counts = (
            connection.execute(
                text(
                    "SELECT count(*) AS total,count(*) FILTER(WHERE user_id=:user) AS owned FROM stream_leases"
                ),
                {"user": user_id},
            )
            .mappings()
            .one()
        )
        if counts["total"] >= MAX_STREAMS or counts["owned"] >= MAX_USER_STREAMS:
            raise Problem(
                429,
                "stream_limit",
                "Há conexões de acompanhamento demais. Consulte o estado da execução enquanto aguarda.",
                retryable=True,
            )
        connection.execute(
            text(
                "INSERT INTO stream_leases(token,user_id,expires_at) VALUES(:token,:user,now()+interval '6 minutes')"
            ),
            {"token": token, "user": user_id},
        )
    return token


def release_stream(token: str) -> None:
    with transaction() as connection:
        connection.execute(text("DELETE FROM stream_leases WHERE token=:token"), {"token": token})
