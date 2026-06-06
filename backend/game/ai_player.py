"""Checkpoint-backed AI player for the custom UNO game.

This module is intentionally lazy: torch and the OOP-AI vendored rlcard package
are imported only when an AI action is requested.
"""

from __future__ import annotations

import os
import sys
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

from .ai_adapter import ACTION_LIST, action_to_engine_payload, build_model_state


DEFAULT_AI_ROOT = "/oop-ai"
DEFAULT_CHECKPOINT = "/oop-ai/experiments/200k-rand-v1/checkpoint_dqn.pt"


@dataclass
class AIDecision:
    action_id: int
    rlcard_action: str
    payload: dict[str, Any]
    info: dict[str, Any]


class DQNCheckpointPlayer:
    def __init__(
        self,
        checkpoint_path: Optional[str] = None,
        ai_project_root: Optional[str] = None,
        device: str = "cpu",
    ) -> None:
        self.checkpoint_path = checkpoint_path or os.environ.get("AI_CHECKPOINT_PATH", DEFAULT_CHECKPOINT)
        self.ai_project_root = ai_project_root or os.environ.get("AI_PROJECT_ROOT", DEFAULT_AI_ROOT)
        self.device = os.environ.get("AI_DEVICE", device)
        self._agent = None

    def decide(self, engine: Any, player_index: Optional[int] = None) -> AIDecision:
        state = build_model_state(engine, player_index)
        return self.decide_from_state(state)

    def load(self) -> None:
        self._load_agent()

    def decide_from_state(self, state: dict[str, Any]) -> AIDecision:
        agent = self._load_agent()
        state = self._normalize_state(state)
        action_id, info = agent.eval_step(state)
        action_id = int(action_id)
        rlcard_action = ACTION_LIST[action_id]
        return AIDecision(
            action_id=action_id,
            rlcard_action=rlcard_action,
            payload=action_to_engine_payload(rlcard_action),
            info=info or {},
        )

    def _load_agent(self) -> Any:
        if self._agent is not None:
            return self._agent

        self._ensure_ai_path()

        import torch
        from rlcard.agents import DQNAgent

        checkpoint = torch.load(
            self.checkpoint_path,
            map_location=self.device,
            weights_only=False,
        )
        checkpoint["device"] = self.device
        if "q_estimator" in checkpoint:
            checkpoint["q_estimator"]["device"] = self.device

        self._agent = DQNAgent.from_checkpoint(checkpoint)
        self._agent.device = self.device
        return self._agent

    def _ensure_ai_path(self) -> None:
        vendor_path = os.path.join(self.ai_project_root, "vendor", "rlcard")
        if vendor_path not in sys.path:
            sys.path.insert(0, vendor_path)

    def _normalize_state(self, state: dict[str, Any]) -> dict[str, Any]:
        legal_actions = state.get("legal_actions")
        if isinstance(legal_actions, dict):
            state = dict(state)
            state["legal_actions"] = OrderedDict(
                (int(action_id), value)
                for action_id, value in legal_actions.items()
            )
        return state


_default_player: Optional[DQNCheckpointPlayer] = None


def get_default_ai_player() -> DQNCheckpointPlayer:
    global _default_player
    if _default_player is None:
        _default_player = DQNCheckpointPlayer()
    return _default_player
