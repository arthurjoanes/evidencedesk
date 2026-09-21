"""Loopback-only lab receiver. Stores bounded, sanitized alert metadata in memory."""

import json
from collections import deque
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

EVENTS = deque(maxlen=200)
LOCK = Lock()
MAX_BODY = 65_536
LABELS = {"alertname", "severity", "project", "environment", "job", "status"}


def sanitize(payload):
    if not isinstance(payload, dict) or payload.get("status") not in (
        "firing",
        "resolved",
    ):
        raise ValueError("Invalid webhook status.")
    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or not 1 <= len(alerts) <= 30:
        raise ValueError("Expected 1 to 30 alerts.")
    result = []
    for alert in alerts:
        if not isinstance(alert, dict) or alert.get("status") not in (
            "firing",
            "resolved",
        ):
            raise ValueError("Invalid alert.")
        labels = alert.get("labels", {})
        if not isinstance(labels, dict):
            raise ValueError("Invalid labels.")
        safe_labels = {
            key: value[:160]
            for key, value in labels.items()
            if key in LABELS and isinstance(value, str)
        }
        result.append({"status": alert["status"], "labels": safe_labels})
    return {
        "received_at": datetime.now(UTC).isoformat(),
        "status": payload["status"],
        "alerts": result,
    }


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def respond(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self.respond(200, {"status": "ok"})
        if self.path != "/events":
            return self.respond(404, {"error": "not_found"})
        with LOCK:
            events = list(EVENTS)
        self.respond(200, {"events": events, "retention": "last 200 deliveries; memory only"})

    def do_POST(self):
        if self.path != "/alerts":
            return self.respond(404, {"error": "not_found"})
        if self.headers.get("Transfer-Encoding"):
            return self.respond(400, {"error": "chunked_not_supported"})
        if self.headers.get_content_type() != "application/json":
            return self.respond(415, {"error": "json_required"})
        try:
            size = int(self.headers.get("Content-Length", "-1"))
            if not 0 < size <= MAX_BODY:
                return self.respond(413, {"error": "body_size"})
            event = sanitize(json.loads(self.rfile.read(size)))
        except (ValueError, UnicodeError, TimeoutError):
            return self.respond(400, {"error": "invalid_payload"})
        with LOCK:
            EVENTS.append(event)
        print(json.dumps(event, ensure_ascii=False), flush=True)
        self.respond(200, {"accepted": True})

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9187), Handler).serve_forever()
