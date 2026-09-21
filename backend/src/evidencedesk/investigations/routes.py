import asyncio
import json
import time

from fastapi import APIRouter, Header, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import text

from evidencedesk.api import CurrentActor, Input
from evidencedesk.audit import record_action
from evidencedesk.database import lock_policy, transaction
from evidencedesk.errors import Problem
from evidencedesk.identity.service import authenticate
from evidencedesk.investigations.service import append_event, create_run, run_payload
from evidencedesk.investigations.streams import release_stream, reserve_stream
from evidencedesk.jobs.service import cancel

router = APIRouter(tags=["Investigações"])


class RunInput(Input):
    evidence_snapshot_id: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=5, max_length=3000)


@router.post("/incidents/{incident_id}/runs", status_code=202)
def new_run(
    incident_id: str,
    body: RunInput,
    actor: CurrentActor,
    response: Response,
    idempotency_key: str | None = Header(default=None),
) -> dict:
    with transaction(actor.tenant_id) as connection:
        policy = lock_policy(connection, actor.tenant_id, mutation=True)
        run_id = create_run(
            connection,
            actor,
            incident_id,
            body.evidence_snapshot_id,
            body.question,
            idempotency_key,
            policy,
        )
        record_action(connection, actor, "run.requested", run_id, policy)
        response.headers["Location"] = f"/api/v1/runs/{run_id}"
        return run_payload(connection, actor, run_id)


@router.get("/runs/{run_id}")
def get_run(run_id: str, actor: CurrentActor) -> dict:
    with transaction(actor.tenant_id) as connection:
        return run_payload(connection, actor, run_id)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, actor: CurrentActor) -> dict:
    with transaction(actor.tenant_id) as connection:
        policy = lock_policy(connection, actor.tenant_id)
        before = run_payload(connection, actor, run_id)
        cancel(connection, actor, run_id)
        result = run_payload(connection, actor, run_id)
        if result["state"] != before["state"]:
            append_event(
                connection,
                actor.tenant_id,
                run_id,
                "terminal",
                {"state": result["state"], "stage": result["stage"]},
            )
            result = run_payload(connection, actor, run_id)
        record_action(connection, actor, "run.cancelled", run_id, policy)
        return result


def read_events(request: Request, run_id: str, last_id: int) -> tuple[dict, list[dict]]:
    actor = authenticate(request)
    with transaction(actor.tenant_id) as connection:
        # A row lock makes snapshot and watermark agree with concurrent stage commits.
        connection.execute(
            text("SELECT id FROM investigation_runs WHERE tenant_id=:tenant AND id=:id FOR SHARE"),
            {"tenant": actor.tenant_id, "id": run_id},
        )
        snapshot = run_payload(connection, actor, run_id)
        events = (
            connection.execute(
                text(
                    "SELECT seq,type,payload FROM run_events WHERE tenant_id=:tenant AND run_id=:id AND seq>:last ORDER BY seq LIMIT 50"
                ),
                {"tenant": actor.tenant_id, "id": run_id, "last": last_id},
            )
            .mappings()
            .all()
        )
        return snapshot, [dict(event) for event in events]


@router.get("/runs/{run_id}/events")
async def events(
    run_id: str,
    actor: CurrentActor,
    request: Request,
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    try:
        last = int(last_event_id or "0")
        if last < 0:
            raise ValueError
    except ValueError:
        raise Problem(422, "invalid_event_cursor", "Cursor de eventos inválido.") from None
    await asyncio.to_thread(read_events, request, run_id, last)
    stream_token = await asyncio.to_thread(reserve_stream, actor.id)

    async def stream():
        position = last
        deadline = time.monotonic() + 300
        for tick in range(300):
            if time.monotonic() >= deadline or await request.is_disconnected():
                return
            try:
                snapshot, batch = await asyncio.to_thread(read_events, request, run_id, position)
            except Problem:
                yield 'event: access_revoked\ndata: {"type":"access_revoked"}\n\n'
                return
            if position > snapshot["last_event_id"] or (batch and batch[0]["seq"] > position + 1):
                yield f"event: resync_required\ndata: {json.dumps({'seq': snapshot['last_event_id'], 'type': 'resync_required', 'payload': {}})}\n\n"
                return
            for event in batch:
                position = event["seq"]
                yield f"id: {position}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"
            if (
                snapshot["state"] in {"succeeded", "failed", "cancelled"}
                and position >= snapshot["last_event_id"]
            ):
                yield f"event: snapshot\ndata: {json.dumps({'seq': position, 'type': 'snapshot', 'payload': jsonable_encoder(snapshot)})}\n\n"
                return
            if tick % 15 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    async def limited_stream():
        try:
            async for event in stream():
                yield event
        finally:
            await asyncio.shield(asyncio.to_thread(release_stream, stream_token))

    return StreamingResponse(
        limited_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )
