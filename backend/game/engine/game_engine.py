# backend/game/engine/game_engine.py
# 遊戲引擎模組 - 負責整體遊戲流程控制

from typing import List, Optional, Tuple
from enum import Enum
import random
from datetime import datetime, timedelta

from .cards import (
    AbstractCard, CardColor, CardType, PlayCardCommand,
    DeckFactory, NumberCard
)
from .player import Player


class GamePhase(Enum):
    WAITING = "waiting"      # 等待玩家
    STARTING = "starting"    # 開始遊戲
    PLAYING = "playing"      # 遊戲中
    FINISHED = "finished"    # 遊戲結束


class GameEngine:
    def __init__(self, players: List[Player]):
        if not (2 <= len(players) <= 4):
            raise ValueError(f"Player count must be 2-4, got {len(players)}")

        # 玩家管理
        self.players = players
        self.current_player_index = 0

        # 牌庫管理
        self.draw_deck: List[AbstractCard] = []
        self.discard_pile: List[AbstractCard] = []

        # 遊戲狀態
        self.phase = GamePhase.WAITING
        self.current_color = CardColor.RED  # 預設紅色
        self.current_number: Optional[int] = None  # 當前數字（用於匹配）
        self.is_clockwise = True  # 出牌順序
        self.draw_penalty = 0  # 累積抽牌懲罰

        # 遊戲記錄
        self.turn_count = 0  # 總回合數
        self.winners: List[Tuple[Player, int]] = []  # (玩家, 排名)

        # 時間限制 (15分鐘)
        self.game_start_time: Optional[datetime] = None
        self.game_time_limit = timedelta(minutes=15)


    def start_game(self) -> dict:
        if self.phase != GamePhase.WAITING:
            return {'success': False, 'error': 'Game already started'}

        self.phase = GamePhase.STARTING

        # 1. 建立並洗牌
        self.draw_deck = DeckFactory.create_shuffled_deck()

        # 2. 發牌（每人5張）
        for _ in range(5):
            for player in self.players:
                if len(self.draw_deck) > 0:
                    card = self.draw_deck.pop()
                    player.draw_card(card)

        # 3. 翻開第一張牌作為起始牌
        if len(self.draw_deck) > 0:
            first_card = self.draw_deck.pop()
            self.discard_pile.append(first_card)

            # 設定初始顏色和數字
            self.current_color = first_card.color
            if isinstance(first_card, NumberCard):
                self.current_number = first_card.number
            else:
                self.current_number = None

        # 4. 設定遊戲階段
        self.phase = GamePhase.PLAYING
        self.turn_count = 0

        # 記錄遊戲開始時間
        self.game_start_time = datetime.now()

        # 第一位玩家開始回合
        current_player = self.get_current_player()
        current_player.start_turn()

        return {
            'success': True,
            'phase': self.phase.value,
            'current_player': current_player.player_id,
            'first_card': str(first_card) if first_card else None,
            'deck_size': len(self.draw_deck),
            'game_start_time': self.game_start_time.isoformat(),
            'time_limit_seconds': int(self.game_time_limit.total_seconds()),
        }

    def play_turn(self, command: PlayCardCommand) -> dict:
        # 執行一個回合的出牌動作
        if self.phase != GamePhase.PLAYING:
            return {'success': False, 'error': 'Game not in playing phase'}

        # 1. 驗證命令
        if not command.validate():
            return {'success': False, 'error': 'Invalid command parameters'}

        # 2. 驗證是否為當前玩家
        current_player = self.get_current_player()
        if command.player_id != current_player.player_id:
            return {
                'success': False,
                'error': f'Not current player. Expected {current_player.player_id}, got {command.player_id}'
            }

        # 3. 驗證玩家是否持有此牌
        if not current_player.get_hand().has_card(command.card):
            return {'success': False, 'error': 'Player does not have this card'}

        # 4. 驗證是否可以打出此牌
        if not self._can_play_card(command.card):
            return {
                'success': False,
                'error': f'Cannot play {command.card}. Current: {self.current_color.value}, {self.current_number}'
            }

        # 5. 打出卡牌
        played_card = current_player.play_card(command.card)
        if not played_card:
            return {'success': False, 'error': 'Failed to play card'}

        # 6. 加入棄牌堆
        self.discard_pile.append(played_card)

        # 7. 更新當前顏色和數字
        self._update_current_state(played_card, command)

        # 8. 執行卡牌效果
        command.execute(self)  # 這裡會呼叫 GameContext 的方法

        # 9. 檢查勝利條件
        if current_player.has_won():
            return self._handle_player_won(current_player)

        # 10. 下一位玩家
        self.next_player()

        return {
            'success': True,
            'card_played': str(played_card),
            'current_color': self.current_color.value,
            'current_number': self.current_number,
            'next_player': self.get_current_player().player_id,
            'draw_penalty': self.draw_penalty,
        }

    def draw_cards_for_player(self, player: Player, count: int) -> List[AbstractCard]:
        
       # 玩家抽牌
        drawn = []
        for _ in range(count):
            # 如果牌庫空了，重洗棄牌堆
            if len(self.draw_deck) == 0:
                self.reshuffle_discard_pile()

            # 如果還有牌，就抽牌
            if len(self.draw_deck) > 0:
                card = self.draw_deck.pop()
                player.draw_card(card)
                drawn.append(card)

        return drawn

    def reshuffle_discard_pile(self) -> None:
        
        # 重洗棄牌堆到牌庫
        if len(self.discard_pile) <= 1:
            # 棄牌堆只剩1張或沒牌，無法重洗
            return

        # 保留最上面的牌
        top_card = self.discard_pile.pop()

        # 將其餘牌洗入牌庫
        self.draw_deck = self.discard_pile[:]
        random.shuffle(self.draw_deck)

        # 清空棄牌堆並放回最上面的牌
        self.discard_pile.clear()
        self.discard_pile.append(top_card)

    def next_player(self) -> None:
        # 增加回合數
        self.turn_count += 1

        # 根據順序切換玩家
        if self.is_clockwise:
            self.current_player_index = (self.current_player_index + 1) % len(self.players)
        else:
            self.current_player_index = (self.current_player_index - 1) % len(self.players)

        # 開始新玩家的回合
        current_player = self.get_current_player()
        current_player.start_turn()

    def get_current_player(self) -> Player:
        return self.players[self.current_player_index]

    def check_winner(self) -> Optional[Player]:
        
        # 檢查是否有玩家獲勝
        for player in self.players:
            if player.has_won():
                return player
        return None

    def get_rankings(self) -> List[Tuple[Player, int]]:
        
        # 取得玩家排名（根據手牌數量）
        rankings = [(p, p.get_hand_size()) for p in self.players]
        rankings.sort(key=lambda x: x[1])  # 手牌少的排前面
        return rankings


    def skip_next_player(self) -> None:
        # 跳過下一位玩家
        # 先切換到下一位
        if self.is_clockwise:
            self.current_player_index = (self.current_player_index + 1) % len(self.players)
        else:
            self.current_player_index = (self.current_player_index - 1) % len(self.players)

    def reverse_order(self) -> None:
        # 反轉出牌順序
        self.is_clockwise = not self.is_clockwise

    def add_draw_penalty(self, count: int) -> None:
        # 增加抽牌懲罰
        self.draw_penalty += count

    def change_color(self, color: CardColor) -> None:
        # 改變當前場地顏色
        self.current_color = color
        self.current_number = None  # 換色後清除數字匹配

    def swap_hands(self, player1_index: int, player2_index: int) -> None:
        # 交換兩位玩家的手牌
        if not (0 <= player1_index < len(self.players)):
            return
        if not (0 <= player2_index < len(self.players)):
            return

        player1 = self.players[player1_index]
        player2 = self.players[player2_index]

        # 交換手牌管理器
        player1.hand_manager, player2.hand_manager = \
            player2.hand_manager, player1.hand_manager

    def steal_card(self, from_player_index: int, to_player_index: int,
                   card_index: int, return_card_index: int) -> None:
        # 從指定玩家偷一張牌並給一張回去
        if not (0 <= from_player_index < len(self.players)):
            return
        if not (0 <= to_player_index < len(self.players)):
            return

        from_player = self.players[from_player_index]
        to_player = self.players[to_player_index]

        # 偷牌
        stolen_card = from_player.get_hand().get_card_at(card_index)
        if stolen_card:
            from_player.get_hand().remove_card(stolen_card)
            to_player.draw_card(stolen_card)

        # 還牌
        return_card = to_player.get_hand().get_card_at(return_card_index)
        if return_card:
            to_player.get_hand().remove_card(return_card)
            from_player.draw_card(return_card)

    def neighbor_swap(self) -> None:
        # 每個玩家與鄰座交換牌
        # 每位玩家從右邊玩家抽一張牌
        temp_cards = []

        for i in range(len(self.players)):
            player = self.players[i]
            cards = player.get_hand().get_cards()

            if len(cards) > 0:
                # 隨機抽一張
                card = random.choice(cards)
                player.get_hand().remove_card(card)
                temp_cards.append(card)
            else:
                temp_cards.append(None)

        # 將抽到的牌給左邊玩家
        for i in range(len(self.players)):
            right_index = (i + 1) % len(self.players)
            card = temp_cards[right_index]
            if card:
                self.players[i].draw_card(card)

    def target_draw_penalty(self, target_player_index: int, count: int) -> None:
        # 指定玩家抽牌
        if not (0 <= target_player_index < len(self.players)):
            return

        target_player = self.players[target_player_index]
        self.draw_cards_for_player(target_player, count)

    def swap_hands_with_target(self, target_index: int) -> None:
        current_index = self.current_player_index
        if 0 <= target_index < len(self.players) and target_index != current_index:
            self.swap_hands(current_index, target_index)

    def steal_and_return_card(self, target_index: int, return_card_index: Optional[int]) -> None:
        # 從目標玩家偷牌並還牌
        current_index = self.current_player_index
        if 0 <= target_index < len(self.players) and target_index != current_index:
            current_player = self.players[current_index]
            target_player = self.players[target_index]

            # 偷一張牌
            target_cards = target_player.get_hand().get_cards()
            if len(target_cards) > 0:
                stolen_card = random.choice(target_cards)
                target_player.get_hand().remove_card(stolen_card)
                current_player.draw_card(stolen_card)

            # 還一張牌
            current_cards = current_player.get_hand().get_cards()
            if len(current_cards) > 0:
                if return_card_index is not None and 0 <= return_card_index < len(current_cards):
                    return_card = current_cards[return_card_index]
                else:
                    return_card = random.choice(current_cards)
                current_player.get_hand().remove_card(return_card)
                target_player.draw_card(return_card)

    def target_draw_cards(self, target_index: int, count: int) -> None:
        # 指定玩家抽牌
        self.target_draw_penalty(target_index, count)

    def peek_top_cards(self, count: int) -> List[AbstractCard]:
        # 查看牌庫頂部N張牌（不移除）
        actual_count = min(count, len(self.draw_deck))
        return self.draw_deck[-actual_count:] if actual_count > 0 else []

    def reorder_top_cards(self, new_order: List[int]) -> None:
        # 重新排列牌庫頂部的牌
        count = len(new_order)
        if count > len(self.draw_deck):
            return

        # 取出頂部的牌
        top_cards = [self.draw_deck.pop() for _ in range(count)]
        top_cards.reverse() 

        # 根據新順序放回
        reordered = [top_cards[i] for i in new_order]

        # 放回牌庫頂部（反向放回以保持順序）
        for card in reversed(reordered):
            self.draw_deck.append(card)

    def get_current_color(self) -> CardColor:
        # 取得當前場地顏色
        return self.current_color

    def find_top_function_card(self) -> Optional[AbstractCard]:
        # 找到牌庫最上方的功能牌
        for card in reversed(self.draw_deck):
            if card.card_type != CardType.NUMBER:
                return card
        return None

    def add_to_discard_pile(self, card: AbstractCard) -> None:
        # 將卡牌加入棄牌堆
        self.discard_pile.append(card)

    def remove_from_deck(self, card: AbstractCard) -> None:
        # 從牌庫移除卡牌
        if card in self.draw_deck:
            self.draw_deck.remove(card)

    def get_draw_penalty(self) -> int:
        # 取得當前累積抽牌懲罰數
        return self.draw_penalty

    def check_timeout(self) -> bool:
        # 檢查遊戲是否超時 (15分鐘)
        if self.game_start_time is None:
            return False

        elapsed = datetime.now() - self.game_start_time
        return elapsed >= self.game_time_limit

    def get_remaining_time(self) -> Optional[timedelta]:
        # 取得剩餘時間
        if self.game_start_time is None:
            return None

        elapsed = datetime.now() - self.game_start_time
        remaining = self.game_time_limit - elapsed
        return remaining if remaining.total_seconds() > 0 else timedelta(0)

    def force_end_game(self) -> dict:
        # 強制結束遊戲並結算積分 (15分鐘超時)
        if self.phase != GamePhase.PLAYING:
            return {'success': False, 'error': 'Game not in playing phase'}

        # 更新遊戲階段為結束
        self.phase = GamePhase.FINISHED

        # 根據手牌數量排名 (手牌少的排名高)
        rankings = self.get_rankings()

        # 前兩名記錄為獲勝者
        if len(rankings) >= 2:
            # 第一名
            if len(self.winners) == 0 or rankings[0][0] not in [w[0] for w in self.winners]:
                self.winners.append((rankings[0][0], 1))

            # 第二名
            if len(self.winners) == 1 or rankings[1][0] not in [w[0] for w in self.winners]:
                self.winners.append((rankings[1][0], 2))

        return {
            'success': True,
            'game_over': True,
            'reason': 'timeout',
            'time_limit_reached': True,
            'final_rankings': [
                {
                    'player_id': p.player_id,
                    'player_name': p.name,
                    'hand_size': size,
                    'rank': idx + 1
                }
                for idx, (p, size) in enumerate(rankings)
            ],
            'phase': self.phase.value,
        }


    def _can_play_card(self, card: AbstractCard) -> bool:
        # 判斷是否可以打出此牌

        # [累積懲罰機制] 如果有累積懲罰，可以選擇出牌或抽牌
        # 若出牌，必須符合：相同功能、相同數字、或黑色累加牌
        if self.draw_penalty > 0:
            # 黑色累加牌（WildDraw4）永遠可以打
            if card.card_type == CardType.WILD_DRAW4:
                return True

            # Draw2 可以打（不需要顏色相同，只要是 Draw2 就可以累加）
            if card.card_type == CardType.DRAW2:
                return True

            # 檢查是否與最後一張牌有相同功能或數字
            if len(self.discard_pile) > 0:
                last_card = self.discard_pile[-1]

                # 相同功能類型（如：skip 對 skip, reverse 對 reverse）
                if card.card_type == last_card.card_type:
                    return True

                # 相同數字（僅數字牌）
                if isinstance(card, NumberCard) and isinstance(last_card, NumberCard):
                    if card.number == last_card.number:
                        return True

            # 不符合以上條件，無法出牌
            return False

        # [正常出牌邏輯] 沒有累積懲罰時的規則
        # 黑色牌永遠可以打
        if card.color == CardColor.BLACK:
            return True

        # 顏色相同
        if card.color == self.current_color:
            return True

        # 數字相同（僅對數字牌檢查）
        if isinstance(card, NumberCard) and self.current_number is not None:
            if card.number == self.current_number:
                return True

        # 檢查功能牌是否相同（即使顏色不同）
        if len(self.discard_pile) > 0:
            last_card = self.discard_pile[-1]
            # 功能牌匹配：skip, reverse, draw2, steal_card 等
            if (card.card_type == last_card.card_type and
                card.card_type in [CardType.SKIP, CardType.REVERSE, CardType.DRAW2,
                                   CardType.STEAL_CARD]):
                return True

        return False

    def _update_current_state(self, card: AbstractCard, command: PlayCardCommand) -> None:
        # 更新當前遊戲狀態（顏色、數字）

        # [變色牌] 使用命令指定的顏色
        if card.card_type in [CardType.WILD, CardType.WILD_DRAW4]:
            if command.chosen_color:
                self.current_color = command.chosen_color
            self.current_number = None

        # [黑色特殊牌] 不改變顏色，下一位玩家可出任意牌
        elif card.color == CardColor.BLACK:
            # 保持原顏色不變，讓下一位可以出任意顏色
            # 不更新 current_color 和 current_number
            pass

        # [一般有色牌] 使用牌的顏色
        else:
            self.current_color = card.color

            # 更新數字（僅數字牌）
            if isinstance(card, NumberCard):
                self.current_number = card.number
            else:
                self.current_number = None

    def _handle_player_won(self, winner: Player) -> dict:
        # 處理玩家獲勝
        # 記錄獲勝者
        rank = len(self.winners) + 1
        self.winners.append((winner, rank))

        # 如果已經有2位獲勝者，或只剩1位玩家，遊戲結束
        remaining_players = [p for p in self.players if not p.has_won()]
        if len(self.winners) >= 2 or len(remaining_players) <= 1:
            self.phase = GamePhase.FINISHED

            # 計算最終排名
            final_rankings = self.get_rankings()

            return {
                'success': True,
                'game_over': True,
                'winner': winner.player_id,
                'rank': rank,
                'final_rankings': [
                    {'player_id': p.player_id, 'hand_size': size}
                    for p, size in final_rankings
                ],
                'phase': self.phase.value,
            }

        return {
            'success': True,
            'game_over': False,
            'winner': winner.player_id,
            'rank': rank,
        }

    def __repr__(self) -> str:
        return (
            f"GameEngine(phase={self.phase.value}, "
            f"players={len(self.players)}, "
            f"current={self.get_current_player().name}, "
            f"deck={len(self.draw_deck)}, "
            f"discard={len(self.discard_pile)})"
        )
