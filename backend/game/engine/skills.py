# 包含所有角色技能類別：
# SkillBehavior: 技能抽象介面
# SeerSkill: 占卜師 - 看牌庫頂4張並排序
# PainterSkill: 巫師 - 更換場地顏色
# ScoutSkill: 斥侯 - 丟手牌換牌堆頂功能牌
# QueenSkill: 女皇 - 轉移抽牌懲罰

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional, Protocol

if TYPE_CHECKING:
    from .game_engine import GameEngine
    from .cards import AbstractCard, CardColor
    from .player import Player


class SkillContext(Protocol):
    # 技能上下文介面

    def peek_top_cards(self, count: int) -> List['AbstractCard']:
        # 查看牌庫頂指定數量的牌
        ...

    def reorder_top_cards(self, new_order: List[int]) -> None:
        # 重新排列牌庫頂的牌
        ...

    def get_current_color(self) -> 'CardColor':
        # 獲取當前場地顏色
        ...

    def change_color(self, color: 'CardColor') -> None:
        # 更換場地顏色
        ...

    def find_top_function_card(self) -> Optional['AbstractCard']:
        # 尋找牌堆頂的功能牌
        ...

    def get_current_player(self) -> 'Player':
        # 獲取當前玩家
        ...

    def add_to_discard_pile(self, card: 'AbstractCard') -> None:
        # 將牌加入棄牌堆
        ...

    def remove_from_deck(self, card: 'AbstractCard') -> None:
        # 從牌庫移除指定牌
        ...

    def get_draw_penalty(self) -> int:
        # 獲取當前抽牌懲罰數量
        ...

    def next_player(self) -> None:
        # 切換到下一位玩家
        ...



class SkillBehavior(ABC):
    # 定義技能的基本行為

    def __init__(self, name: str, description: str):
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        # 獲取技能名稱
        return self._name

    @property
    def description(self) -> str:
        # 獲取技能描述
        return self._description

    @abstractmethod
    def can_use(self, turn_count: int, **kwargs) -> bool:
        # 檢查是否可以使用技能
        pass

    @abstractmethod
    def execute_skill(self, context: SkillContext, **kwargs) -> dict:
        # 執行技能效果
        pass

    def to_dict(self) -> dict:
        # 轉換為字典格式（用於序列化）

        return {
            'name': self.name,
            'description': self.description,
        }

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.name}>"


# 具體技能類別 

class SeerSkill(SkillBehavior):
    """
    占卜師技能

    效果：看牌庫頂4張並隨意排順序
    觸發條件：每2次輪到自己
    使用次數：無限（符合條件即可）
    """

    def __init__(self):
        super().__init__(
            name="占卜師",
            description="每2次輪到自己可以看牌庫頂4張並隨意排順序"
        )
        self.use_interval = 2  # 每2回合可用一次

    def can_use(self, turn_count: int, **kwargs) -> bool:
        # 檢查是否可以使用技能
        # Returns: 是否可以使用（使用後需再經過自己2次回合）
        last_skill_turn_count = kwargs.get('last_skill_turn_count', -3)
        return last_skill_turn_count + self.use_interval < turn_count

    def execute_skill(self, context: SkillContext, **kwargs) -> dict:
        # 執行占卜師技能
        # Returns:執行結果
        new_order = kwargs.get('new_order')

        if new_order is None:
            return {
                'success': False,
                'message': '需要提供新的牌序'
            }

        # 獲取牌庫頂4張牌
        top_cards = context.peek_top_cards(4)

        if len(top_cards) < 4:
            return {
                'success': False,
                'message': f'牌庫只剩 {len(top_cards)} 張牌，無法使用技能'
            }

        # 驗證新順序
        if not self._validate_order(new_order, len(top_cards)):
            return {
                'success': False,
                'message': '無效的牌序'
            }

        # 重新排列牌庫頂的牌
        context.reorder_top_cards(new_order)

        return {
            'success': True,
            'message': f'{self.name}技能發動！重新排列牌庫頂4張牌',
            'cards_viewed': [card.to_dict() for card in top_cards]
        }

    def _validate_order(self, order: List[int], length: int) -> bool:
        # 驗證牌序是否有效
        # Returns:  是否有效
        if not isinstance(order, (list, tuple)):
            return False

        if len(order) != length:
            return False

        # 檢查是否為 0 到 length-1 的排列
        return sorted(order) == list(range(length))


class PainterSkill(SkillBehavior):
    """
    巫師技能

    效果：更換場地顏色一次
    觸發條件：每2次輪到自己
    使用次數：無限（符合條件即可）
    """

    def __init__(self):
        super().__init__(
            name="巫師",
            description="每2次輪到自己可以更換場地顏色一次"
        )
        self.use_interval = 2  # 每2回合可用一次

    def can_use(self, turn_count: int, **kwargs) -> bool:
        # 檢查是否可以使用技能
        # Returns: 是否可以使用（使用後需再經過自己2次回合）
        last_skill_turn_count = kwargs.get('last_skill_turn_count', -3)
        return last_skill_turn_count + self.use_interval < turn_count

    def execute_skill(self, context: SkillContext, **kwargs) -> dict:
        # 執行巫師技能
        # Returns: 執行結果
        from .cards import CardColor

        new_color = kwargs.get('new_color')

        if new_color is None:
            return {
                'success': False,
                'message': '需要提供新的顏色'
            }

        # 轉換顏色
        if isinstance(new_color, str):
            try:
                new_color = CardColor(new_color)
            except ValueError:
                return {
                    'success': False,
                    'message': f'無效的顏色: {new_color}'
                }

        # 黑色不能作為場地顏色
        if new_color == CardColor.BLACK:
            return {
                'success': False,
                'message': '不能將場地顏色改為黑色'
            }

        # 更換場地顏色
        old_color = context.get_current_color()
        context.change_color(new_color)

        return {
            'success': True,
            'message': f'{self.name}技能發動！場地顏色從 {old_color.value} 改為 {new_color.value}',
            'old_color': old_color.value,
            'new_color': new_color.value
        }


class ScoutSkill(SkillBehavior):
    """
    斥侯技能

    效果：丟一張手牌來獲得牌堆最上面的那張功能牌
    觸發條件：任何時候
    使用次數：每場遊戲3次
    """

    def __init__(self):
        super().__init__(
            name="斥侯",
            description="每場遊戲3次可以丟一張手牌來獲得牌堆最上面的那張功能牌"
        )
        self.max_use_count = 3  # 每場最多3次
        self.used_count = 0      # 已使用次數

    def can_use(self, turn_count: int, **kwargs) -> bool:
        # 檢查是否可以使用技能
        # Returns:是否可以使用（還有剩餘次數）
        return self.used_count < self.max_use_count

    def execute_skill(self, context: SkillContext, **kwargs) -> dict:
        # 執行斥侯技能
        # Returns:執行結果
        from .cards import CardType

        if not self.can_use(0):
            return {
                'success': False,
                'message': f'{self.name}技能已使用 {self.used_count}/{self.max_use_count} 次'
            }

        discard_card = kwargs.get('discard_card')

        if discard_card is None:
            return {
                'success': False,
                'message': '需要選擇一張手牌丟棄'
            }

        # 尋找牌堆頂的功能牌
        function_card = context.find_top_function_card()

        if function_card is None:
            return {
                'success': False,
                'message': '牌堆中沒有功能牌'
            }

        # 執行交換
        current_player = context.get_current_player()

        # 丟棄手牌
        if not current_player.hand_manager.has_card(discard_card):
            return {
                'success': False,
                'message': '手中沒有這張牌'
            }

        current_player.hand_manager.remove_card(discard_card)
        context.add_to_discard_pile(discard_card)

        # 獲得功能牌
        context.remove_from_deck(function_card)
        current_player.hand_manager.add_card(function_card)

        # 增加使用次數
        self.used_count += 1

        return {
            'success': True,
            'message': f'{self.name}技能發動！丟棄 {discard_card}，獲得 {function_card}',
            'discarded_card': discard_card.to_dict(),
            'gained_card': function_card.to_dict(),
            'remaining_uses': self.max_use_count - self.used_count
        }

    def reset(self):
        #　重置技能使用次數（新遊戲開始時
        self.used_count = 0

    def to_dict(self) -> dict:
        # 包含使用次數的序列化
        data = super().to_dict()
        data.update({
            'max_uses': self.max_use_count,
            'used_count': self.used_count,
            'remaining_uses': self.max_use_count - self.used_count
        })
        return data


class QueenSkill(SkillBehavior):
    """
    女皇技能

    效果：不抽牌直接 pass 到下一位，下一位繼承抽牌效果
    觸發條件：需要抽牌時
    使用次數：每場遊戲2次
    """

    def __init__(self):
        super().__init__(
            name="女皇",
            description="每場遊戲2次需抽牌時可以不抽牌直接pass到下一位（下一個玩家繼承抽牌效果）"
        )
        self.max_use_count = 2  # 每場最多2次
        self.used_count = 0      # 已使用次數

    def can_use(self, turn_count: int, **kwargs) -> bool:
        # 檢查是否可以使用技能
        # Returns: 是否可以使用（還有剩餘次數且有抽牌懲罰）
        has_penalty = kwargs.get('has_draw_penalty', False)
        return self.used_count < self.max_use_count and has_penalty

    def execute_skill(self, context: SkillContext, **kwargs) -> dict:
        # 執行女皇技能

        if not self.can_use(0, has_draw_penalty=True):
            return {
                'success': False,
                'message': f'{self.name}技能已使用 {self.used_count}/{self.max_use_count} 次或沒有抽牌懲罰'
            }

        # 獲取當前抽牌懲罰
        penalty = context.get_draw_penalty()

        if penalty == 0:
            return {
                'success': False,
                'message': '沒有抽牌懲罰'
            }

        # 轉移懲罰到下一位玩家
        # 不清除懲罰，直接跳過當前玩家
        current_player = context.get_current_player()
        context.next_player()
        next_player = context.get_current_player()

        # 增加使用次數
        self.used_count += 1

        return {
            'success': True,
            'message': f'{self.name}技能發動！{current_player.name} 不抽牌，{next_player.name} 繼承 {penalty} 張抽牌懲罰',
            'penalty_transferred': penalty,
            'from_player': current_player.name,
            'to_player': next_player.name,
            'remaining_uses': self.max_use_count - self.used_count
        }

    def reset(self):
        # 重置技能使用次數（新遊戲開始時）
        self.used_count = 0

    def to_dict(self) -> dict:
        # 包含使用次數的序列化
        data = super().to_dict()
        data.update({
            'max_uses': self.max_use_count,
            'used_count': self.used_count,
            'remaining_uses': self.max_use_count - self.used_count
        })
        return data


# 工廠類別
class SkillFactory:
    
    # 使用工廠模式建立不同類型的技能
    @staticmethod
    def create_skill(skill_type: str) -> Optional[SkillBehavior]:
        # 根據技能類型建立技能實例
        # Returns:技能實例，如果類型無效則返回 None
        skill_map = {
            'seer': SeerSkill,
            'painter': PainterSkill,
            'scout': ScoutSkill,
            'queen': QueenSkill,
        }

        skill_class = skill_map.get(skill_type.lower())

        if skill_class:
            return skill_class()

        return None

    @staticmethod
    def get_all_skill_types() -> List[str]:
        # 獲取所有可用的技能類型
        # Returns:技能類型列表
        return ['seer', 'painter', 'scout', 'queen']

    @staticmethod
    def get_skill_description(skill_type: str) -> Optional[str]:
        # 獲取技能描述
        # Returns:技能描述，如果類型無效則返回 None

        skill = SkillFactory.create_skill(skill_type)
        return skill.description if skill else None

    @staticmethod
    def validate_skill_type(skill_type: str) -> bool:
        # 驗證技能類型是否有效
        # Returns: 是否為有效的技能類型
        return skill_type.lower() in SkillFactory.get_all_skill_types()
