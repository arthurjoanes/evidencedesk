from fastapi import APIRouter, Request, Response
from pydantic import Field
from sqlalchemy import text

from evidencedesk.api import CurrentActor, Input
from evidencedesk.config import get_settings
from evidencedesk.database import transaction
from evidencedesk.identity.service import login, session_digest, session_payload

router = APIRouter(prefix="/auth", tags=["Sessão"])


class LoginInput(Input):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
def login_route(body: LoginInput, request: Request, response: Response) -> dict:
    token, actor = login(body.email, body.password, request)
    settings = get_settings()
    response.set_cookie(
        "ed_session",
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/v1",
    )
    return session_payload(actor)


@router.get("/session")
def current_session(actor: CurrentActor) -> dict:
    return session_payload(actor)


@router.post("/logout", status_code=204)
def logout(actor: CurrentActor, request: Request) -> Response:
    with transaction() as connection:
        connection.execute(
            text("DELETE FROM sessions WHERE token_hash=:token"),
            {"token": session_digest(request.cookies.get("ed_session", ""))},
        )
    response = Response(status_code=204)
    response.delete_cookie("ed_session", path="/api/v1")
    return response
