# 玩家管理系統

from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .cards import AbstractCard, CardColor
    from .skills import SkillBehavior


class HandManager:
    # 手牌管理器
    def __init__(self, max_hand_size: int = 50):
        self._cards: List['AbstractCard'] = []
        self._max_hand_size = max_hand_size

    @property
    def cards(self) -> List['AbstractCard']:
        # 獲取所有手牌
        return self._cards.copy()

    def add_card(self, card: 'AbstractCard') -> bool:
        if len(self._cards) >= self._max_hand_size:
            return False

        self._cards.append(card)
        return True

    def remove_card(self, card: 'AbstractCard') -> bool:
        # 從手牌中移除指定卡牌
        try:
            self._cards.remove(card)
            return True
        except ValueError:
            return False

    def remove_card_at(self, index: int) -> Optional['AbstractCard']:
        # 根據索引移除卡牌
        if not 0 <= index < len(self._cards):
            return None

        return self._cards.pop(index)

    def get_card(self, index: int) -> Optional['AbstractCard']:
        # 根據索引獲取卡牌
        if not 0 <= index < len(self._cards):
            return None

        return self._cards[index]

    def get_card_at(self, index: int) -> Optional['AbstractCard']:
        # 根據索引獲取卡牌
        return self.get_card(index)

    def get_cards(self) -> List['AbstractCard']:
        # 獲取所有手牌
        return self._cards.copy()

    def get_playable_cards(self, current_color: 'CardColor', current_number: Optional[int], draw_penalty: int = 0) -> List['AbstractCard']:
        # 取得可以打出的牌列表
        from .cards import CardColor, CardType, NumberCard

        playable = []

        # [累積懲罰機制] 如果有累積懲罰，只能打出可以累加懲罰的牌
        if draw_penalty > 0:
            for card in self._cards:
                # 只能打出 Draw2 (且顏色相同) 或 WildDraw4
                if card.card_type == CardType.DRAW2:
                    playable.append(card)
                elif card.card_type == CardType.WILD_DRAW4:
                    playable.append(card)
            return playable

        # [正常出牌邏輯] 沒有累積懲罰時的規則
        for card in self._cards:
            # 黑色牌永遠可以打
            if card.color == CardColor.BLACK:
                playable.append(card)
            # 顏色相同
            elif card.color == current_color:
                playable.append(card)
            # 數字相同(只對數字牌檢查)
            elif (isinstance(card, NumberCard) and
                  current_number is not None and
                  card.number == current_number):
                playable.append(card)

        return playable

    def get_size(self) -> int:
        # 獲取手牌數量
        return len(self._cards)

    def is_empty(self) -> bool:
        # 檢查手牌是否為空
        return len(self._cards) == 0

    def has_card(self, card: 'AbstractCard') -> bool:
        # 檢查手牌中是否有指定卡牌
        return card in self._cards

    def can_play(self, card: 'AbstractCard', field_color: 'CardColor', field_value: str) -> bool:
        # 檢查是否能打出某張牌
        if not self.has_card(card):
            return False

        return card.can_play_on(field_color, field_value)

    def find_playable_cards(self, field_color: 'CardColor', field_value: str) -> List['AbstractCard']:
        # 找出所有可以打出的牌
        return [card for card in self._cards if card.can_play_on(field_color, field_value)]

    def sort_by_color(self) -> None:
        # 依顏色排序手牌
        self._cards.sort(key=lambda card: card.color.value)

    def sort_by_value(self) -> None:
        # 依數值排序手牌
        self._cards.sort(key=lambda card: card.value)

    def sort_by_type(self) -> None:
        # 依卡牌類型排序手牌
        self._cards.sort(key=lambda card: card.card_type.value)

    def clear(self) -> None:
        # 清空所有手牌
        self._cards.clear()

    def swap_with(self, other: 'HandManager') -> None:
        
        # 與另一個手牌管理器交換手牌

        self._cards, other._cards = other._cards, self._cards

    def to_dict(self, hide_cards: bool = False) -> dict:
        # hide_cards: 是否隱藏卡牌內容
        # Returns: 包含手牌資訊的字典
        if hide_cards:
            return {
                'card_count': len(self._cards),
            }
        else:
            return {
                'cards': [card.to_dict() for card in self._cards],
                'card_count': len(self._cards),
            }

    def __len__(self) -> int:
        return len(self._cards)

    def __str__(self) -> str:
        return f"HandManager({len(self._cards)} cards)"

    def __repr__(self) -> str:
        return f"<HandManager: {len(self._cards)} cards>"


class Player:
    
    # 玩家類別，代表遊戲中的一個玩家,包含手牌、技能和相關狀態

    def __init__(
        self,
        player_id: int,
        name: str,
        skill: Optional['SkillBehavior'] = None,
        is_ai: bool = False
    ):
      
        self.player_id = player_id
        self.name = name
        self.hand_manager = HandManager()
        self.skill = skill
        self.is_ai = is_ai

        # 回合計數(用於判斷技能觸發)
        self.turn_count = 0

        # 技能使用統計
        self.skill_used_count = 0
        self.skill_used_this_turn = False
        self.last_skill_turn_count = -3
        self.finished_rank: Optional[int] = None

    def play_card(self, card: 'AbstractCard') -> Optional['AbstractCard']:
        # 打出一張牌

        if self.hand_manager.remove_card(card):
            return card
        return None

    def play_card_at(self, index: int) -> Optional['AbstractCard']:
        #　根據索引打出一張牌

        return self.hand_manager.remove_card_at(index)

    def draw_card(self, card: 'AbstractCard') -> bool:
        # 抽一張牌

        return self.hand_manager.add_card(card)

    def draw_cards(self, cards: List['AbstractCard']) -> int:
        # 抽多張牌

        count = 0
        for card in cards:
            if self.hand_manager.add_card(card):
                count += 1
            else:
                break  # 手牌已滿
        return count

    def get_hand_size(self) -> int:
        # 獲取手牌數量

        return self.hand_manager.get_size()

    def has_cards(self) -> bool:
        # 檢查是否還有手牌

        return not self.hand_manager.is_empty()

    def has_won(self) -> bool:
        # Backward-compatible alias for finished-state checks.
        return self.has_finished()

    def has_finished(self) -> bool:
        # 檢查是否已經完成出牌並被記錄名次。
        return self.finished_rank is not None

    def mark_finished(self, rank: int) -> None:
        # 標記玩家已完成出牌。
        self.finished_rank = rank

    def get_hand(self) -> HandManager:
        # 取得手牌管理器

        return self.hand_manager

    def can_use_skill(self, **kwargs) -> bool:
        # 檢查是否可以使用技能

        if self.skill is None:
            return False

        if self.skill_used_this_turn:
            return False

        return self.skill.can_use(
            self.turn_count,
            last_skill_turn_count=self.last_skill_turn_count,
            **kwargs
        )

    def use_skill(self, engine, **kwargs) -> dict:
        # 使用技能

        if self.skill is None:
            return {
                'success': False,
                'message': '此玩家沒有技能'
            }

        if not self.can_use_skill(**kwargs):
            return {
                'success': False,
                'message': '技能無法使用'
            }

        result = self.skill.execute_skill(engine, **kwargs)

        if result.get('success'):
            self.skill_used_count += 1
            self.skill_used_this_turn = True
            self.last_skill_turn_count = self.turn_count

        return result

    def preview_skill(self, engine, **kwargs) -> dict:
        # 預覽技能資訊；不消耗技能、不改變冷卻。
        if self.skill is None:
            return {
                'success': False,
                'message': '此玩家沒有技能'
            }

        if not self.can_use_skill(**kwargs):
            return {
                'success': False,
                'message': '技能無法使用'
            }

        return self.skill.preview(engine, **kwargs)

    def start_turn(self) -> None:
        # 開始新回合
        self.turn_count += 1
        self.skill_used_this_turn = False

    def increment_turn(self) -> None:
        # 增加回合計數
        self.turn_count += 1

    def reset_turn_count(self) -> None:
        # 重置回合計數(新遊戲開始時)
        self.turn_count = 0
        self.last_skill_turn_count = -3

    def reset_skill(self) -> None:
        # 重置技能狀態(新遊戲開始時)
        self.skill_used_count = 0
        self.skill_used_this_turn = False
        self.last_skill_turn_count = -3
        if self.skill and hasattr(self.skill, 'reset'):
            self.skill.reset()

    def reset_finished_state(self) -> None:
        # 重置出完牌狀態(新遊戲開始時)
        self.finished_rank = None

    def swap_hands_with(self, other: 'Player') -> None:
        # 與另一個玩家交換手牌
        self.hand_manager.swap_with(other.hand_manager)

    def to_dict(self, hide_hand: bool = False) -> dict:
        # 轉換為字典格式(用於序列化)

        return {
            'player_id': self.player_id,
            'name': self.name,
            'hand': self.hand_manager.to_dict(hide_cards=hide_hand),
            'skill': self.skill.to_dict() if self.skill else None,
            'is_ai': self.is_ai,
            'turn_count': self.turn_count,
            'skill_used_count': self.skill_used_count,
            'skill_used_this_turn': self.skill_used_this_turn,
            'last_skill_turn_count': self.last_skill_turn_count,
            'finished_rank': self.finished_rank,
            'has_finished': self.has_finished(),
        }

    def __str__(self) -> str:
        skill_name = self.skill.name if self.skill else "無技能"
        return f"{self.name} ({skill_name})"

    def __repr__(self) -> str:
        return f"<Player {self.player_id}: {self.name}, {self.get_hand_size()} cards>"

    def __eq__(self, other) -> bool:
        if not isinstance(other, Player):
            return False
        return self.player_id == other.player_id

    def __hash__(self) -> int:
        return hash(self.player_id)
