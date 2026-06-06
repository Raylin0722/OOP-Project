"""Small HTTP service that owns the checkpoint-backed AI model."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from game.ai_player import get_default_ai_player


HOST = os.environ.get("AI_SERVICE_HOST", "0.0.0.0")
PORT = int(os.environ.get("AI_SERVICE_PORT", "9000"))


class AIRequestHandler(BaseHTTPRequestHandler):
    server_version = "OOPAI/1.0"

    def do_GET(self) -> None:
        if self.path != "/healthz":
            self._send_json({"error": "not found"}, status=404)
            return

        self._send_json({"status": "ok"})

    def do_POST(self) -> None:
        if self.path != "/decide":
            self._send_json({"error": "not found"}, status=404)
            return

        try:
            state = self._read_json()
            decision = get_default_ai_player().decide_from_state(state)
            self._send_json(
                {
                    "action_id": decision.action_id,
                    "rlcard_action": decision.rlcard_action,
                    "payload": decision.payload,
                    "info": decision.info,
                }
            )
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[ai-service] {self.address_string()} {format % args}", flush=True)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), AIRequestHandler)
    print(f"[ai-service] listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
