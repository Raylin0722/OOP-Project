# backend/game/engine/game_state.py
# 遊戲狀態管理模組


from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime

from .cards import AbstractCard, CardColor


@dataclass
class PlayerState:
    # 玩家狀態快照
    player_id: str
    name: str
    hand_size: int  # 手牌數量（不暴露具體牌）
    skill_name: str
    skill_used_count: int
    turn_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_player(player: 'Player') -> 'PlayerState':
        return PlayerState(
            player_id=player.player_id,
            name=player.name,
            hand_size=player.get_hand_size(),
            skill_name=player.skill.name if player.skill else "None",
            skill_used_count=player.skill_used_count,
            turn_count=player.turn_count,
        )


@dataclass
class GameState:
    # 遊戲狀態快照
    # 遊戲基本資訊
    phase: str  # 遊戲階段
    turn_count: int  # 總回合數
    timestamp: str  # 時間戳記

    # 當前狀態
    current_player_index: int
    current_color: str
    current_number: Optional[int]
    is_clockwise: bool
    draw_penalty: int

    # 牌庫資訊
    deck_size: int
    discard_pile_size: int
    discard_pile_top: Optional[str]  # 棄牌堆最上面的牌

    # 玩家資訊
    players: List[Dict[str, Any]]

    # 獲勝者
    winners: List[Dict[str, Any]]  # [{'player_id': str, 'rank': int}, ...]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_engine(engine: 'GameEngine') -> 'GameState':
        # 從 GameEngine 建立狀態快照
        # 取得棄牌堆最上面的牌
        discard_top = None
        if len(engine.discard_pile) > 0:
            discard_top = str(engine.discard_pile[-1])

        # 建立玩家狀態列表
        player_states = [
            PlayerState.from_player(p).to_dict()
            for p in engine.players
        ]

        # 建立獲勝者列表
        winners_list = [
            {'player_id': player.player_id, 'rank': rank}
            for player, rank in engine.winners
        ]

        return GameState(
            phase=engine.phase.value,
            turn_count=engine.turn_count,
            timestamp=datetime.now().isoformat(),
            current_player_index=engine.current_player_index,
            current_color=engine.current_color.value,
            current_number=engine.current_number,
            is_clockwise=engine.is_clockwise,
            draw_penalty=engine.draw_penalty,
            deck_size=len(engine.draw_deck),
            discard_pile_size=len(engine.discard_pile),
            discard_pile_top=discard_top,
            players=player_states,
            winners=winners_list,
        )


@dataclass
class PlayerHandState:
    # 玩家手牌狀態
    player_id: str
    cards: List[str]  # 手牌字串表示
    playable_cards: List[int]  # 可以打出的牌索引

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_player(player: 'Player', current_color: 'CardColor',
                    current_number: Optional[int], draw_penalty: int = 0) -> 'PlayerHandState':
        # 從 Player 建立手牌狀態
        hand = player.get_hand()
        cards = hand.get_cards()
        playable = hand.get_playable_cards(current_color, current_number, draw_penalty)

        # 找出可打出牌的索引
        playable_indices = []
        for i, card in enumerate(cards):
            if card in playable:
                playable_indices.append(i)

        return PlayerHandState(
            player_id=player.player_id,
            cards=[str(card) for card in cards],
            playable_cards=playable_indices,
        )


@dataclass
class GameAction:
    # 遊戲動作記錄
    action_id: int
    timestamp: str
    player_id: str
    action_type: str  # 'play_card', 'draw_card', 'use_skill', 'skip'
    details: Dict[str, Any]  # 動作詳細資訊

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def create_play_card(action_id: int, player_id: str,
                        card: str, **kwargs) -> 'GameAction':
        # 建立打牌動作
        return GameAction(
            action_id=action_id,
            timestamp=datetime.now().isoformat(),
            player_id=player_id,
            action_type='play_card',
            details={'card': card, **kwargs}
        )

    @staticmethod
    def create_draw_card(action_id: int, player_id: str,
                        count: int) -> 'GameAction':
        # 建立抽牌動作
        return GameAction(
            action_id=action_id,
            timestamp=datetime.now().isoformat(),
            player_id=player_id,
            action_type='draw_card',
            details={'count': count}
        )

    @staticmethod
    def create_use_skill(action_id: int, player_id: str,
                        skill_name: str, **kwargs) -> 'GameAction':
        # 建立使用技能動作
        return GameAction(
            action_id=action_id,
            timestamp=datetime.now().isoformat(),
            player_id=player_id,
            action_type='use_skill',
            details={'skill_name': skill_name, **kwargs}
        )

    @staticmethod
    def create_skip_turn(action_id: int, player_id: str,
                        reason: str) -> 'GameAction':
        # 建立跳過回合動作
        return GameAction(
            action_id=action_id,
            timestamp=datetime.now().isoformat(),
            player_id=player_id,
            action_type='skip',
            details={'reason': reason}
        )


class GameHistory:
    # 遊戲歷史記錄器

    def __init__(self):
        self.actions: List[GameAction] = []
        self.states: List[GameState] = []
        self._action_counter = 0

    def record_action(self, action: GameAction) -> None:
        # 記錄一個動作
        self.actions.append(action)

    def record_state(self, state: GameState) -> None:
        # 記錄一個狀態快照
        self.states.append(state)

    def get_next_action_id(self) -> int:
        # 取得下一個動作ID
        self._action_counter += 1
        return self._action_counter

    def to_dict(self) -> Dict[str, Any]:
        return {
            'actions': [action.to_dict() for action in self.actions],
            'states': [state.to_dict() for state in self.states],
        }

    def get_summary(self) -> Dict[str, Any]:
        # 取得歷史
        if len(self.states) == 0:
            return {'total_actions': 0, 'total_turns': 0}

        first_state = self.states[0]
        last_state = self.states[-1]

        return {
            'total_actions': len(self.actions),
            'total_turns': last_state.turn_count,
            'start_time': first_state.timestamp,
            'end_time': last_state.timestamp,
            'final_phase': last_state.phase,
        }

    def __len__(self) -> int:
        return len(self.actions)

    def __repr__(self) -> str:
        return f"GameHistory(actions={len(self.actions)}, states={len(self.states)})"
