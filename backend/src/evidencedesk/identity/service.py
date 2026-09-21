import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Request
from sqlalchemy import Connection, text

from evidencedesk.config import get_settings
from evidencedesk.database import transaction
from evidencedesk.errors import Problem, not_found
from evidencedesk.identity.admission import password_capacity, reserve_password_attempt

PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = PASSWORDS.hash("not-a-user-password")
BASE_PERMISSIONS = [
    "create_incident",
    "create_import",
    "create_dossier",
    "create_run",
    "edit_dossier",
    "submit_revision",
    "export_revision",
]


@dataclass(frozen=True)
class Actor:
    id: str
    tenant_id: str
    name: str
    tenant_name: str
    role: str
    csrf_token: str
    expires_at: datetime

    @property
    def permissions(self) -> list[str]:
        return BASE_PERMISSIONS + (
            ["review_revision"] if self.role in {"reviewer", "tenant_admin"} else []
        )


def session_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def require_origin(request: Request) -> None:
    if request.headers.get("origin") not in get_settings().origins:
        raise Problem(403, "invalid_origin", "Origem da requisição não autorizada.")


def authenticate(request: Request) -> Actor:
    token = request.cookies.get("ed_session", "")
    if not token or len(token) > 128:
        raise Problem(401, "session_required", "Entre para continuar a investigação.")
    with transaction() as connection:
        row = (
            connection.execute(
                text("""
            SELECT u.id,u.tenant_id,u.name,u.role,t.name AS tenant_name,s.csrf_token,s.expires_at
            FROM sessions s JOIN users u ON u.id=s.user_id JOIN tenants t ON t.id=u.tenant_id
            WHERE s.token_hash=:token AND s.expires_at>now() AND u.enabled AND t.enabled
        """),
                {"token": session_digest(token)},
            )
            .mappings()
            .first()
        )
    if row is None:
        raise Problem(401, "session_expired", "Sua sessão expirou. Entre novamente.")
    actor = Actor(**row)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request)
        if not secrets.compare_digest(actor.csrf_token, request.headers.get("x-csrf-token", "")):
            raise Problem(403, "invalid_csrf", "A sessão precisa ser atualizada antes de salvar.")
    return actor


def login(email: str, password: str, request: Request) -> tuple[str, Actor]:
    require_origin(request)
    key = session_digest(email.casefold())
    reserve_password_attempt(key)
    with transaction() as connection:
        row = (
            connection.execute(
                text("""
            SELECT u.*,t.name AS tenant_name FROM users u JOIN tenants t ON t.id=u.tenant_id
            WHERE lower(u.email)=:email AND u.enabled AND t.enabled
        """),
                {"email": email.casefold()},
            )
            .mappings()
            .first()
        )
    valid: bool
    with password_capacity():
        try:
            valid = PASSWORDS.verify(row["password_hash"] if row else DUMMY_HASH, password)
        except VerifyMismatchError:
            valid = False
    if row is None or not valid:
        raise Problem(401, "invalid_credentials", "E-mail ou senha incorretos.")
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with transaction() as connection:
        expires = connection.execute(
            text("""
            INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at)
            VALUES(:token,:user,:csrf,now()+make_interval(hours=>:hours)) RETURNING expires_at
        """),
            {
                "token": session_digest(token),
                "user": row["id"],
                "csrf": csrf,
                "hours": get_settings().session_hours,
            },
        ).scalar_one()
        # Count admitted attempts, including successful ones. Clearing this row after a
        # success would erase reservations held by concurrent password checks.
    return token, Actor(
        row["id"], row["tenant_id"], row["name"], row["tenant_name"], row["role"], csrf, expires
    )


def session_payload(actor: Actor) -> dict:
    settings = get_settings()
    return {
        "user": {"id": actor.id, "name": actor.name, "role": actor.role},
        "tenant": {"id": actor.tenant_id, "name": actor.tenant_name},
        "csrf_token": actor.csrf_token,
        "expires_at": actor.expires_at,
        "permissions": actor.permissions,
        "runtime": {
            "generation_enabled": settings.generation_enabled,
            "provider": settings.ai_provider,
            "model_display_name": settings.azure_openai_deployment,
            "disabled_reason": None
            if settings.generation_enabled
            else "Credencial do gerador não configurada no backend. A investigação manual está disponível.",
        },
    }


def authorize_collection(connection: Connection, actor: Actor, collection_id: str) -> dict:
    row = (
        connection.execute(
            text("""
        SELECT c.* FROM collections c JOIN collection_grants g ON g.tenant_id=c.tenant_id AND g.collection_id=c.id
        WHERE c.tenant_id=:tenant AND c.id=:collection AND g.user_id=:user AND c.tombstoned_at IS NULL
    """),
            {"tenant": actor.tenant_id, "collection": collection_id, "user": actor.id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found()
    return dict(row)


def authorize_incident(connection: Connection, actor: Actor, incident_id: str) -> dict:
    row = (
        connection.execute(
            text("""
        SELECT i.* FROM incidents i JOIN incident_members m ON m.tenant_id=i.tenant_id AND m.incident_id=i.id
        WHERE i.tenant_id=:tenant AND i.id=:incident AND m.user_id=:user
    """),
            {"tenant": actor.tenant_id, "incident": incident_id, "user": actor.id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found()
    authorize_collection(connection, actor, row["collection_id"])
    return dict(row)


def actor_for_worker(connection: Connection, tenant_id: str, user_id: str) -> Actor:
    row = (
        connection.execute(
            text("""
        SELECT u.id,u.tenant_id,u.name,u.role,t.name AS tenant_name,'' AS csrf_token,now() AS expires_at
        FROM users u JOIN tenants t ON t.id=u.tenant_id WHERE u.id=:user AND u.tenant_id=:tenant AND u.enabled AND t.enabled
    """),
            {"user": user_id, "tenant": tenant_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found()
    return Actor(**row)
