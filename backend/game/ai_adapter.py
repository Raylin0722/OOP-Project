"""Adapters between the local game engine and the custom RLCard UNO model.

The trained DQN/NFSP agents expect the custom RLCard UNO state format:

    {
        "obs": 12 x 4 x 19 tensor-like data,
        "legal_actions": OrderedDict(action_id -> None),
        "raw_obs": {...},
        "raw_legal_actions": [...]
    }

This module intentionally does not import rlcard. Keeping the adapter pure
lets the Django backend run even before the AI package/model is installed in
the container.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable, Optional

from .engine.cards import AbstractCard, CardColor, CardType, NumberCard


COLORS = ("r", "g", "b", "y")
COLOR_TO_RLCARD = {
    "red": "r",
    "green": "g",
    "blue": "b",
    "yellow": "y",
    "black": "r",
}
RLCARD_TO_ENGINE_COLOR = {
    "r": "red",
    "g": "green",
    "b": "blue",
    "y": "yellow",
}
TRAIT_TO_INDEX = {
    "0": 0,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "skip": 10,
    "reverse": 11,
    "draw_2": 12,
    "steal_1_swap": 13,
    "wild": 14,
    "wild_draw_4": 15,
    "swap_hands": 16,
    "everyone_steal_neighbor": 17,
    "target_draw_2": 18,
}
ENGINE_VALUE_TO_RLCARD = {
    "draw2": "draw_2",
    "wild": "wild",
    "wild_draw4": "wild_draw_4",
    "skip": "skip",
    "reverse": "reverse",
    "steal_card": "steal_1_swap",
    "swap_hand": "swap_hands",
    "neighbor_swap": "everyone_steal_neighbor",
    "target_draw2": "target_draw_2",
}
SKILL_TO_RLCARD = {
    "SeerSkill": "skill_1",
    "PainterSkill": "skill_2",
    "ScoutSkill": "skill_3",
    "QueenSkill": "skill_4",
}


def build_action_space() -> OrderedDict[str, int]:
    action_space: OrderedDict[str, int] = OrderedDict()
    action_id = 0

    for color in COLORS:
        for trait in (
            "0",
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "skip",
            "reverse",
            "draw_2",
            "wild",
            "wild_draw_4",
        ):
            action_space[f"{color}-{trait}"] = action_id
            action_id += 1

    for action in ("draw", "skill_1", "skill_2_r", "skill_2_g", "skill_2_b", "skill_2_y", "skill_3", "skill_4"):
        action_space[action] = action_id
        action_id += 1

    for color in COLORS:
        for target_index in range(10):
            action_space[f"{color}-steal_1_swap-p{target_index}"] = action_id
            action_id += 1

    for color in COLORS:
        for target_index in range(10):
            action_space[f"{color}-swap_hands-p{target_index}"] = action_id
            action_id += 1

    for color in COLORS:
        action_space[f"{color}-everyone_steal_neighbor"] = action_id
        action_id += 1

    for color in COLORS:
        for target_index in range(10):
            action_space[f"{color}-target_draw_2-p{target_index}"] = action_id
            action_id += 1

    return action_space


ACTION_SPACE = build_action_space()
ACTION_LIST = list(ACTION_SPACE.keys())


def card_to_rlcard(card: AbstractCard | str | None, fallback_color: str = "red") -> Optional[str]:
    """Convert an engine card into the custom RLCard string format."""
    if card is None:
        return None

    if isinstance(card, str):
        parts = card.strip().split()
        if len(parts) >= 2:
            color, value = parts[0], "_".join(parts[1:])
        else:
            color, value = "black", parts[0] if parts else ""
    else:
        color = card.color.value
        value = card.value

    rl_color = COLOR_TO_RLCARD.get(color, COLOR_TO_RLCARD.get(fallback_color, "r"))
    rl_trait = ENGINE_VALUE_TO_RLCARD.get(value, value)
    return f"{rl_color}-{rl_trait}"


def cards_to_rlcard(cards: Iterable[AbstractCard | str], fallback_color: str = "red") -> list[str]:
    return [converted for card in cards if (converted := card_to_rlcard(card, fallback_color))]


def action_to_engine_payload(action: str) -> dict[str, Any]:
    """Convert an RLCard action string into a payload GameConsumer can send."""
    if action == "draw":
        return {"action": "draw_card", "card_index": None, "card_name": None}

    if action.startswith("skill_"):
        return {"action": "use_skill", "params": {"rlcard_action": action}}

    parts = action.split("-")
    color = RLCARD_TO_ENGINE_COLOR.get(parts[0])
    trait = parts[1] if len(parts) > 1 else ""
    target_player_index = None

    if len(parts) >= 3 and parts[2].startswith("p"):
        target_player_index = int(parts[2][1:])

    value = {
        "draw_2": "draw2",
        "wild_draw_4": "wild_draw4",
        "steal_1_swap": "steal_card",
        "swap_hands": "swap_hand",
        "everyone_steal_neighbor": "neighbor_swap",
        "target_draw_2": "target_draw2",
    }.get(trait, trait)

    payload = {
        "action": "play_card",
        "card_index": None,
        "card_name": f"{color} {value}" if color else value,
    }
    if color and trait in {"wild", "wild_draw_4", "swap_hands", "target_draw_2"}:
        payload["chosen_color"] = color
    if target_player_index is not None:
        payload["target_player_index"] = target_player_index
    return payload


def build_rlcard_raw_state(engine: Any, player_index: Optional[int] = None) -> dict[str, Any]:
    """Build the raw state shape used by the customized RLCard UNO env."""
    current_index = engine.current_player_index if player_index is None else player_index
    current_player = engine.players[current_index]
    fallback_color = engine.current_color.value
    hand_cards = current_player.get_hand().get_cards()
    top_card = engine.discard_pile[-1] if engine.discard_pile else None

    raw_state = {
        "hand": cards_to_rlcard(hand_cards, fallback_color),
        "target": card_to_rlcard(top_card, fallback_color) or f"{COLOR_TO_RLCARD[fallback_color]}-0",
        "current_player": current_index,
        "num_cards": [player.get_hand_size() for player in engine.players],
        "direction": 1 if engine.is_clockwise else -1,
        "pending_draw_count": engine.draw_penalty,
        "legal_actions": build_legal_actions(engine, current_index),
        "player_skills": [_skill_to_rlcard(player.skill) for player in engine.players],
        "skill_cooldowns": [_skill_cooldown(player) for player in engine.players],
        "skill3_remaining": [_skill_remaining(player, 3) for player in engine.players],
        "skill4_remaining": [_skill_remaining(player, 4) for player in engine.players],
        "top_discard_function_card": card_to_rlcard(engine.find_top_function_card(), fallback_color),
    }
    return raw_state


def build_model_state(engine: Any, player_index: Optional[int] = None) -> dict[str, Any]:
    """Build the state dictionary accepted by RLCard-style agents."""
    raw_state = build_rlcard_raw_state(engine, player_index)
    legal_actions = OrderedDict(
        (ACTION_SPACE[action], None)
        for action in raw_state["legal_actions"]
        if action in ACTION_SPACE
    )
    return {
        "obs": encode_observation(raw_state),
        "legal_actions": legal_actions,
        "raw_obs": raw_state,
        "raw_legal_actions": list(raw_state["legal_actions"]),
        "action_record": [],
    }


def build_legal_actions(engine: Any, player_index: int) -> list[str]:
    player = engine.players[player_index]
    cards = player.get_hand().get_cards()
    actions: list[str] = []

    for card in cards:
        if not engine._can_play_card(card):
            continue

        actions.extend(_card_legal_actions(card, engine, player_index))

    return actions or ["draw"]


def encode_observation(raw_state: dict[str, Any]) -> list[list[list[float]]]:
    obs = _zeros(12, 4, len(TRAIT_TO_INDEX))
    _encode_hand(obs, raw_state["hand"])
    _encode_target(obs[3], raw_state["target"])

    skill = raw_state.get("player_skills", [None])[raw_state.get("current_player", 0)]
    if skill in {"skill_1", "skill_2", "skill_3", "skill_4"}:
        obs[4][int(skill[-1]) - 1] = [1.0] * len(TRAIT_TO_INDEX)

    current_player = raw_state.get("current_player", 0)
    cooldowns = raw_state.get("skill_cooldowns", [])
    if current_player < len(cooldowns):
        obs[5][0] = [min(cooldowns[current_player], 5) / 5] * len(TRAIT_TO_INDEX)

    pending_draw = raw_state.get("pending_draw_count", 0)
    obs[6][0] = [min(pending_draw, 20) / 20] * len(TRAIT_TO_INDEX)

    for player_id, count in enumerate(raw_state.get("num_cards", [])[:4]):
        obs[7][player_id] = [min(count, 30) / 30] * len(TRAIT_TO_INDEX)

    if raw_state.get("direction", 1) == 1:
        obs[8][0] = [1.0] * len(TRAIT_TO_INDEX)
    else:
        obs[8][1] = [1.0] * len(TRAIT_TO_INDEX)

    if raw_state.get("top_discard_function_card"):
        _encode_target(obs[9], raw_state["top_discard_function_card"])

    for player_id, player_skill in enumerate(raw_state.get("player_skills", [])[:4]):
        if player_skill in {"skill_1", "skill_2", "skill_3", "skill_4"}:
            obs[10][player_id][int(player_skill[-1]) - 1] = 1.0

    for player_id, cooldown in enumerate(cooldowns[:4]):
        obs[11][player_id] = [min(cooldown, 5) / 5] * len(TRAIT_TO_INDEX)

    return obs


def _card_legal_actions(card: AbstractCard, engine: Any, player_index: int) -> list[str]:
    fallback_color = engine.current_color.value
    base = card_to_rlcard(card, fallback_color)
    if not base:
        return []

    if card.card_type == CardType.WILD:
        return [f"{color}-wild" for color in COLORS]

    if card.card_type == CardType.WILD_DRAW4:
        return [f"{color}-wild_draw_4" for color in COLORS]

    if card.card_type == CardType.NEIGHBOR_SWAP:
        return [f"{color}-everyone_steal_neighbor" for color in COLORS]

    if card.card_type in {CardType.SWAP_HAND, CardType.TARGET_DRAW2}:
        trait = ENGINE_VALUE_TO_RLCARD[card.value]
        return [
            f"{color}-{trait}-p{target_index}"
            for color in COLORS
            for target_index in range(len(engine.players))
            if target_index != player_index
        ]

    if card.card_type == CardType.STEAL_CARD:
        color = COLOR_TO_RLCARD[card.color.value]
        return [
            f"{color}-steal_1_swap-p{target_index}"
            for target_index in range(len(engine.players))
            if target_index != player_index
        ]

    return [base]


def _encode_hand(obs: list[list[list[float]]], hand: Iterable[str]) -> None:
    for color in range(4):
        for trait in range(len(TRAIT_TO_INDEX)):
            obs[0][color][trait] = 1.0

    counts: dict[str, int] = {}
    for card in hand:
        counts[card] = counts.get(card, 0) + 1

    for card, count in counts.items():
        color, trait = _split_rlcard(card)
        if trait >= TRAIT_TO_INDEX["wild"]:
            if obs[1][0][trait] == 0:
                for color_index in range(4):
                    obs[0][color_index][trait] = 0.0
                    obs[1][color_index][trait] = 1.0
            continue

        obs[0][color][trait] = 0.0
        obs[min(count, 2)][color][trait] = 1.0


def _encode_target(plane: list[list[float]], target: str) -> None:
    color, trait = _split_rlcard(target)
    plane[color][trait] = 1.0


def _split_rlcard(card: str) -> tuple[int, int]:
    color, trait = card.split("-", 1)
    return COLORS.index(color), TRAIT_TO_INDEX[trait]


def _zeros(depth: int, rows: int, cols: int) -> list[list[list[float]]]:
    return [[[0.0 for _ in range(cols)] for _ in range(rows)] for _ in range(depth)]


def _skill_to_rlcard(skill: Any) -> Optional[str]:
    return SKILL_TO_RLCARD.get(skill.__class__.__name__) if skill else None


def _skill_cooldown(player: Any) -> int:
    return max(0, 2 - (player.turn_count % 2))


def _skill_remaining(player: Any, skill_number: int) -> int:
    skill = player.skill
    if not skill:
        return 0
    if skill_number == 3 and skill.__class__.__name__ == "ScoutSkill":
        return max(0, getattr(skill, "max_use_count", 0) - getattr(skill, "used_count", 0))
    if skill_number == 4 and skill.__class__.__name__ == "QueenSkill":
        return max(0, getattr(skill, "max_use_count", 0) - getattr(skill, "used_count", 0))
    return 0
