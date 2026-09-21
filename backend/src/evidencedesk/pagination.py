import base64
import hashlib
import hmac
import json
from datetime import datetime

from evidencedesk.config import get_settings
from evidencedesk.errors import Problem


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def encode_cursor(context: dict, last_id: str) -> str:
    payload = json.dumps(
        {"context": fingerprint(context), "last": last_id}, separators=(",", ":")
    ).encode()
    signature = hmac.new(
        get_settings().cursor_secret.get_secret_value().encode(), payload, hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(signature + payload).decode().rstrip("=")


def decode_cursor(cursor: str | None, context: dict) -> str:
    if cursor is None:
        return ""
    try:
        if len(cursor) > 1000:
            raise ValueError
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        expected = hmac.new(
            get_settings().cursor_secret.get_secret_value().encode(), raw[32:], hashlib.sha256
        ).digest()
        if not hmac.compare_digest(raw[:32], expected):
            raise ValueError
        payload = json.loads(raw[32:])
        if payload["context"] != fingerprint(context) or not isinstance(payload["last"], str):
            raise ValueError
        return payload["last"]
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise Problem(
            409, "cursor_context_changed", "O recorte mudou. Recarregue a lista desde o início."
        ) from None


def page(items: list[dict], limit: int, context: dict, total: int | None = None) -> dict:
    more = len(items) > limit
    visible = items[:limit]
    result = {
        "items": visible,
        "next_cursor": encode_cursor(context, visible[-1]["id"]) if more else None,
        "total": total,
    }
    if "snapshot" in context:
        result["evidence_snapshot_id"] = context["snapshot"]
    return result


def decode_recent_cursor(cursor: str | None, context: dict) -> tuple[datetime | None, str]:
    value = decode_cursor(cursor, context)
    if not value:
        return None, ""
    try:
        position = json.loads(value)
        if not isinstance(position, list) or len(position) != 2:
            raise ValueError
        created_at, item_id = position
        if not isinstance(item_id, str) or not item_id or len(item_id) > 200:
            raise ValueError
        timestamp = datetime.fromisoformat(created_at)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError
        return timestamp, item_id
    except (ValueError, TypeError):
        raise Problem(
            409, "cursor_context_changed", "O recorte mudou. Recarregue a lista desde o início."
        ) from None


def recent_page(items: list[dict], limit: int, context: dict) -> dict:
    result = page(items, limit, context)
    if result["next_cursor"]:
        last = result["items"][-1]
        position = json.dumps([last["created_at"].isoformat(), last["id"]])
        result["next_cursor"] = encode_cursor(context, position)
    return result
