"""Bound unauthenticated password work before allocating an e-mail bucket."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from threading import BoundedSemaphore

from sqlalchemy import text

from evidencedesk.config import get_settings
from evidencedesk.database import transaction
from evidencedesk.errors import Problem

# E-mail keys are SHA256 hex; this namespace cannot collide with user input.
GLOBAL_LOGIN_KEY = "global:login:v1"
EMAIL_KEY_SQL = "key_hash ~ '^[0-9a-f]{64}$'"


def reserve_password_attempt(email_key: str) -> None:
    settings = get_settings()
    denied: Problem | None = None
    with transaction() as connection:
        connection.execute(
            text("""
            INSERT INTO login_limits(key_hash,failures,window_start) VALUES(:key,0,now())
            ON CONFLICT(key_hash) DO NOTHING
            """),
            {"key": GLOBAL_LOGIN_KEY},
        )
        global_state = (
            connection.execute(
                text("""
            SELECT failures,window_start<=now()-interval '1 minute' AS expired
            FROM login_limits WHERE key_hash=:key FOR UPDATE
            """),
                {"key": GLOBAL_LOGIN_KEY},
            )
            .mappings()
            .one()
        )
        if global_state["expired"]:
            connection.execute(
                text("UPDATE login_limits SET failures=0,window_start=now() WHERE key_hash=:key"),
                {"key": GLOBAL_LOGIN_KEY},
            )
        used = 0 if global_state["expired"] else global_state["failures"]
        if used >= settings.login_global_per_minute:
            denied = Problem(
                429,
                "login_global_limited",
                "Muitas tentativas de acesso. Aguarde um minuto.",
                retryable=True,
            )
        else:
            email_state = (
                connection.execute(
                    text("""
                SELECT failures,window_start<=now()-interval '15 minutes' AS expired
                FROM login_limits WHERE key_hash=:key
                """),
                    {"key": email_key},
                )
                .mappings()
                .first()
            )
            if email_state and not email_state["expired"] and email_state["failures"] >= 10:
                denied = Problem(
                    429,
                    "login_limited",
                    "Muitas tentativas. Aguarde alguns minutos.",
                    retryable=True,
                )
            else:
                # Already blocked e-mails do not trigger cleanup or consume quota.
                # The global row lock serializes both the cap check and reservations.
                # Each cleanup/count scan remains bounded by the cardinality cap.
                connection.execute(
                    text("UPDATE login_limits SET failures=failures+1 WHERE key_hash=:key"),
                    {"key": GLOBAL_LOGIN_KEY},
                )
                connection.execute(
                    text(f"""
                    DELETE FROM login_limits WHERE key_hash IN (
                      SELECT key_hash FROM login_limits WHERE {EMAIL_KEY_SQL}
                        AND window_start<=now()-interval '15 minutes'
                      ORDER BY window_start,key_hash LIMIT :batch
                    )
                    """),
                    {"batch": settings.login_cleanup_batch},
                )
                if (
                    email_state is None
                    and connection.execute(
                        text(
                            f"SELECT count(*) FROM (SELECT 1 FROM login_limits WHERE {EMAIL_KEY_SQL} LIMIT :maximum) limited"
                        ),
                        {"maximum": settings.login_max_email_keys},
                    ).scalar_one()
                    >= settings.login_max_email_keys
                ):
                    denied = Problem(
                        503,
                        "login_capacity",
                        "O acesso está ocupado. Tente novamente em instantes.",
                        retryable=True,
                    )
                else:
                    connection.execute(
                        text("""
                    INSERT INTO login_limits(key_hash,failures,window_start) VALUES(:key,1,now())
                    ON CONFLICT(key_hash) DO UPDATE SET
                      failures=CASE WHEN login_limits.window_start<=now()-interval '15 minutes' THEN 1 ELSE login_limits.failures+1 END,
                      window_start=CASE WHEN login_limits.window_start<=now()-interval '15 minutes' THEN now() ELSE login_limits.window_start END
                    """),
                        {"key": email_key},
                    )
    # Reservations commit before password verification. An already blocked e-mail
    # never consumes shared quota; new-key cleanup/capacity work still does.
    if denied is not None:
        raise denied


@lru_cache(maxsize=1)
def password_slots(capacity: int) -> BoundedSemaphore:
    return BoundedSemaphore(capacity)


@contextmanager
def password_capacity() -> Iterator[None]:
    slots = password_slots(get_settings().login_password_concurrency)
    if not slots.acquire(blocking=False):
        raise Problem(
            503,
            "login_capacity",
            "O acesso está ocupado. Tente novamente em instantes.",
            retryable=True,
        )
    try:
        yield
    finally:
        slots.release()
