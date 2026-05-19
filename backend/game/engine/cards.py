# 卡牌系統 

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional, Protocol

if TYPE_CHECKING:
    from .game_engine import GameEngine


class CardType(Enum):
    # 卡牌類型列舉
    NUMBER = "number"
    SKIP = "skip"
    REVERSE = "reverse"
    DRAW2 = "draw2"
    WILD = "wild"
    WILD_DRAW4 = "wild_draw4"
    SWAP_HAND = "swap_hand"
    STEAL_CARD = "steal_card"
    NEIGHBOR_SWAP = "neighbor_swap"
    TARGET_DRAW2 = "target_draw2"


class CardColor(Enum):
    # 卡牌顏色列舉
    RED = "red"
    BLUE = "blue"
    GREEN = "green"
    YELLOW = "yellow"
    BLACK = "black"  # 黑色萬用牌


# 協議介面 (Protocol)

class GameContext(Protocol):
    def skip_next_player(self) -> None:
        # 跳過下一位玩家
        ...

    def reverse_order(self) -> None:
        # 反轉出牌順序
        ...

    def add_draw_penalty(self, count: int) -> None:
        # 累積抽牌懲罰
        ...

    def change_color(self, color: CardColor) -> None:
        # 更換場上顏色
        ...

    def swap_hands_with_target(self, target_index: int) -> None:
        # 與目標玩家交換手牌
        ...

    def steal_and_return_card(self, target_index: int, return_card_index: Optional[int]) -> None:
        # 從目標玩家偷牌並還牌
        ...

    def neighbor_swap(self) -> None:
        # 每個玩家與鄰座交換牌
        ...

    def target_draw_cards(self, target_index: int, count: int) -> None:
        # 指定玩家抽牌
        ...


@dataclass
class PlayCardCommand:
    card: 'AbstractCard'
    player_id: str

    # 可選參數（依卡牌類型而定）
    chosen_color: Optional[CardColor] = None  # 變色牌需要
    target_player_index: Optional[int] = None  # 指定目標牌需要
    return_card_index: Optional[int] = None  # 偷牌需要

    def execute(self, context: GameContext) -> None:
        #　執行打牌命令
        self.card.execute_effect(context, self)

    def validate(self) -> bool:
        # 變色牌需要選擇顏色
        if self.card.card_type in [CardType.WILD, CardType.WILD_DRAW4]:
            if not self.chosen_color or self.chosen_color == CardColor.BLACK:
                return False

        # 需要目標玩家的卡牌
        if self.card.card_type in [CardType.SWAP_HAND, CardType.STEAL_CARD, CardType.TARGET_DRAW2]:
            if self.target_player_index is None:
                return False

        # 偷牌需要指定還牌索引
        if self.card.card_type == CardType.STEAL_CARD:
            # return_card_index 可以為 None（由系統自動選擇）
            pass

        return True



class AbstractCard(ABC):
    def __init__(self, color: CardColor, value: str, card_type: CardType):
        self._color = color
        self._value = value
        self._card_type = card_type

    @property
    def color(self) -> CardColor:
        return self._color

    @property
    def value(self) -> str:
        return self._value

    @property
    def card_type(self) -> CardType:
        return self._card_type

    def can_play_on(self, field_color: CardColor, field_value: str) -> bool:
        # 黑色牌可以打在任何牌上
        if self.color == CardColor.BLACK:
            return True

        # 顏色相同或值相同
        return self.color == field_color or self.value == field_value

    @abstractmethod
    def execute_effect(self, context: GameContext, command: PlayCardCommand) -> None:
        pass

    def to_dict(self) -> dict:
        return {
            'color': self.color.value,
            'value': self.value,
            'type': self.card_type.value,
        }

    def __str__(self) -> str:
        return f"{self.color.value} {self.value}"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.color.value} {self.value}>"

    def __eq__(self, other) -> bool:
        if not isinstance(other, AbstractCard):
            return False
        return (self.color == other.color and
                self.value == other.value and
                self.card_type == other.card_type)

    def __hash__(self) -> int:
        return hash((self.color, self.value, self.card_type))


class NumberCard(AbstractCard):
    def __init__(self, color: CardColor, number: int):
        if not 0 <= number <= 9:
            raise ValueError("Number must be between 0 and 9")

        if color == CardColor.BLACK:
            raise ValueError("Number card cannot be black")

        super().__init__(color, str(number), CardType.NUMBER)
        self.number = number

    def execute_effect(self, context: GameContext, command: PlayCardCommand) -> None:
        pass


class SkipCard(AbstractCard):
    # 跳過下一位玩家

    def __init__(self, color: CardColor):
        if color == CardColor.BLACK:
            raise ValueError("Skip card cannot be black")

        super().__init__(color, "skip", CardType.SKIP)

    def execute_effect(self, context: GameContext, command: PlayCardCommand) -> None:
        context.skip_next_player()


class ReverseCard(AbstractCard):
    # 迴轉牌 - 反轉出牌順序

    def __init__(self, color: CardColor):
        if color == CardColor.BLACK:
            raise ValueError("Reverse card cannot be black")

        super().__init__(color, "reverse", CardType.REVERSE)

    def execute_effect(self, context: GameContext, command: PlayCardCommand) -> None:
        context.reverse_order()


class Draw2Card(AbstractCard):
    # 抽2張牌 - 下一位玩家抽2張牌
    def __init__(self, color: CardColor):
        if color == CardColor.BLACK:
            raise ValueError("Draw2 card cannot be black")

        super().__init__(color, "draw2", CardType.DRAW2)

    def execute_effect(self, context: GameContext, command: PlayCardCommand) -> None:
        context.add_draw_penalty(2)


class WildCard(AbstractCard):
    # 換色牌 - 可以改變場上顏色

    def __init__(self):
        super().__init__(CardColor.BLACK, "wild", CardType.WILD)

    def execute_effect(self, context: GameContext, command: PlayCardCommand) -> None:
        if command.chosen_color and command.chosen_color != CardColor.BLACK:
            context.change_color(command.chosen_color)


class WildDraw4Card(AbstractCard):
    # 換色+抽4張牌

    def __init__(self):
        super().__init__(CardColor.BLACK, "wild_draw4", CardType.WILD_DRAW4)

    def execute_effect(self, context: GameContext, command: PlayCardCommand) -> None:
        # 先累積懲罰
        context.add_draw_penalty(4)

        # 再更換顏色
        if command.chosen_color and command.chosen_color != CardColor.BLACK:
            context.change_color(command.chosen_color)


class SwapHandCard(AbstractCard):
    # 換手牌 - 挑選一位玩家交換手牌
    def __init__(self):
        super().__init__(CardColor.BLACK, "swap_hand", CardType.SWAP_HAND)

    def execute_effect(self, context: GameContext, command: PlayCardCommand) -> None:
        if command.target_player_index is not None:
            context.swap_hands_with_target(command.target_player_index)


class StealCardCard(AbstractCard):
    # 偷牌 - 挑人抽1張手牌丟1張回去
    def __init__(self, color: CardColor):
        if color == CardColor.BLACK:
            raise ValueError("Steal card cannot be black")

        super().__init__(color, "steal_card", CardType.STEAL_CARD)

    def execute_effect(self, context: GameContext, command: PlayCardCommand) -> None:
        # 從目標玩家抽一張牌，然後給回一張牌
        if command.target_player_index is not None:
            context.steal_and_return_card(
                command.target_player_index,
                command.return_card_index
            )


class NeighborSwapCard(AbstractCard):
    # 隔壁交換 - 每人抽隔壁1張牌
    def __init__(self):
        super().__init__(CardColor.BLACK, "neighbor_swap", CardType.NEIGHBOR_SWAP)

    def execute_effect(self, context: GameContext, command: PlayCardCommand) -> None:
        context.neighbor_swap()


class TargetDraw2Card(AbstractCard):
    # 指定抽2張 - 指定一人抽2張牌

    def __init__(self):
        super().__init__(CardColor.BLACK, "target_draw2", CardType.TARGET_DRAW2)

    def execute_effect(self, context: GameContext, command: PlayCardCommand) -> None:
        if command.target_player_index is not None:
            context.target_draw_cards(command.target_player_index, 2)


class DeckFactory:
    # 使用工廠模式建立不同類型的牌組
    @staticmethod
    def create_standard_deck() -> list[AbstractCard]:
        deck = []

        # 四種顏色
        colors = [CardColor.RED, CardColor.BLUE, CardColor.GREEN, CardColor.YELLOW]

        for color in colors:
            # 數字 0: 1張
            deck.append(NumberCard(color, 0))

            # 數字 1-9: 各2張
            for number in range(1, 10):
                deck.append(NumberCard(color, number))
                deck.append(NumberCard(color, number))

            # 跳過: 2張
            deck.append(SkipCard(color))
            deck.append(SkipCard(color))

            # 迴轉: 2張
            deck.append(ReverseCard(color))
            deck.append(ReverseCard(color))

            # 抽2: 2張
            deck.append(Draw2Card(color))
            deck.append(Draw2Card(color))

            # 偷牌: 1張
            deck.append(StealCardCard(color))

        # 黑色牌
        # 換色: 4張
        for _ in range(4):
            deck.append(WildCard())

        # 換色+抽4: 4張
        for _ in range(4):
            deck.append(WildDraw4Card())

        # 換手牌: 2張
        for _ in range(2):
            deck.append(SwapHandCard())

        # 隔壁交換: 2張
        for _ in range(2):
            deck.append(NeighborSwapCard())

        # 指定抽2: 1張
        deck.append(TargetDraw2Card())

        return deck

    @staticmethod
    def create_shuffled_deck() -> list[AbstractCard]:
        # 建立已洗牌的標準牌庫
        deck = DeckFactory.create_standard_deck()
        random.shuffle(deck)
        return deck

    @staticmethod
    def validate_deck(deck: list[AbstractCard]) -> bool:
        if len(deck) != 117:
            return False

        # 統計各類型卡牌數量
        type_counts = {}
        for card in deck:
            card_type = card.card_type
            type_counts[card_type] = type_counts.get(card_type, 0) + 1

        # 驗證數量是否正確
        expected_counts = {
            CardType.NUMBER: 76,  # 4色 * (1個0 + 2*9個1-9) = 4 * 19
            CardType.SKIP: 8,     # 4色 * 2張
            CardType.REVERSE: 8,  # 4色 * 2張
            CardType.DRAW2: 8,    # 4色 * 2張
            CardType.STEAL_CARD: 4,  # 4色 * 1張
            CardType.WILD: 4,
            CardType.WILD_DRAW4: 4,
            CardType.SWAP_HAND: 2,
            CardType.NEIGHBOR_SWAP: 2,
            CardType.TARGET_DRAW2: 1,
        }

        return type_counts == expected_counts



def create_standard_deck() -> list[AbstractCard]:
    # 建立標準牌庫（向後相容的便利函式）

    return DeckFactory.create_standard_deck()
