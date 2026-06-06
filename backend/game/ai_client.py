"""Client used by the backend to ask the separate AI service for decisions."""

from __future__ import annotations

import json
import os
from typing import Any, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .ai_adapter import build_model_state
from .ai_player import AIDecision, get_default_ai_player


DEFAULT_AI_SERVICE_URL = "http://ai_service:9000"


def get_ai_decision(engine: Any, player_index: Optional[int] = None) -> AIDecision:
    service_url = os.environ.get("AI_SERVICE_URL", DEFAULT_AI_SERVICE_URL).strip()
    if service_url:
        return _decide_via_service(service_url, engine, player_index)

    return get_default_ai_player().decide(engine, player_index)


def _decide_via_service(service_url: str, engine: Any, player_index: Optional[int]) -> AIDecision:
    state = build_model_state(engine, player_index)
    body = json.dumps(state).encode("utf-8")
    request = Request(
        f"{service_url.rstrip('/')}/decide",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        timeout = float(os.environ.get("AI_SERVICE_TIMEOUT", "5"))
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AI service returned {exc.code}: {message}") from exc

    if "error" in payload:
        raise RuntimeError(f"AI service error: {payload['error']}")

    return AIDecision(
        action_id=int(payload["action_id"]),
        rlcard_action=payload["rlcard_action"],
        payload=payload["payload"],
        info=payload.get("info") or {},
    )
