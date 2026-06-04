# backend/game/game_consumer.py
# 遊戲 WebSocket Consumer

# 整合 GameEngine 與 WebSocket，提供即時遊戲功能：
# 1. 遊戲狀態同步
# 2. 玩家出牌
# 3. 技能使用
# 4. 遊戲事件廣播
#

import json
from typing import Optional, Dict, Any
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from .engine import (
    GameEngine, GamePhase, GameState, PlayerHandState,
    Player, SkillFactory,
    CardColor, CardType, PlayCardCommand,
    DeckFactory,
)
from .models import Room, RoomMember


class GameConsumer(AsyncWebsocketConsumer):
    # 遊戲 WebSocket Consumer，處理遊戲進行中的所有 WebSocket 通訊

    # 類別變數：存儲所有房間的遊戲引擎實例
    # key: room_code, value: GameEngine
    game_engines: Dict[str, GameEngine] = {}

    async def connect(self):
        """建立 WebSocket 連接"""
        self.room_code = self.scope['url_route']['kwargs']['code']
        self.group_name = f'game_{self.room_code}'
        self.user = self.scope.get('user')

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4401)
            return

        # 驗證是否為房間成員
        if not await self._is_room_member():
            await self.close(code=4403)
            return

        # 加入房間群組
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # 發送當前遊戲狀態
        await self._send_game_state()

    async def disconnect(self, close_code):
        # 斷開 WebSocket 連接
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        # 接收客戶端訊息
        try:
            data = json.loads(text_data)
            action = data.get('action')

            if action == 'start_game':
                await self.handle_start_game()
            elif action == 'play_card':
                await self.handle_play_card(data)
            elif action == 'draw_card':
                await self.handle_draw_card()
            elif action == 'use_skill':
                await self.handle_use_skill(data)
            elif action == 'get_state':
                await self._send_game_state()
            else:
                await self.send_error(f'Unknown action: {action}')

        except json.JSONDecodeError:
            await self.send_error('Invalid JSON')
        except Exception as e:
            await self.send_error(f'Error: {str(e)}')

    # 遊戲動作處理

    async def handle_start_game(self):
        # 處理開始遊戲
        # 只有房主可以開始遊戲
        is_host = await self._is_host()
        if not is_host:
            await self.send_error('Only host can start the game')
            return

        # 獲取房間成員
        members = await self._get_room_members()

        if len(members) < 2:
            await self.send_error('Need at least 2 players')
            return

        # 建立玩家列表
        players = []
        for member in members:
            skill_type = await self._assign_random_skill()
            skill = SkillFactory.create_skill(skill_type)
            player = Player(
                player_id=str(member['user_id']),
                name=member['nickname'],
                skill=skill
            )
            players.append(player)

        # 建立遊戲引擎
        engine = GameEngine(players)
        result = engine.start_game()

        # 存儲遊戲引擎
        GameConsumer.game_engines[self.room_code] = engine

        # 廣播遊戲開始
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'game_started',
                'payload': {
                    'success': result['success'],
                    'phase': result['phase'],
                    'current_player': result['current_player'],
                    'first_card': result['first_card'],
                }
            }
        )

    async def handle_play_card(self, data):
        # 處理打牌動作
        engine = GameConsumer.game_engines.get(self.room_code)
        if not engine:
            await self.send_error('Game not started')
            return

        # [15分鐘超時機制] 檢查遊戲是否超時
        if engine.check_timeout():
            result = engine.force_end_game()
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'game_ended',
                    'payload': result
                }
            )
            return

        # 驗證是否為當前玩家
        current_player = engine.get_current_player()
        if str(current_player.player_id) != str(self.user.id):
            await self.send_error('Not your turn')
            return

        # 解析打牌參數
        card_index = data.get('card_index')
        chosen_color = data.get('chosen_color')
        target_player_index = data.get('target_player_index')
        return_card_index = data.get('return_card_index')

        if card_index is None:
            await self.send_error('Missing card_index')
            return

        # 獲取要打出的牌
        hand = current_player.get_hand()
        card = hand.get_card_at(card_index)

        if not card:
            await self.send_error('Invalid card_index')
            return

        # 建立打牌命令
        command_kwargs = {
            'card': card,
            'player_id': current_player.player_id,
        }

        # 如果是變色牌，需要指定顏色
        if card.card_type in [CardType.WILD, CardType.WILD_DRAW4]:
            if chosen_color:
                try:
                    command_kwargs['chosen_color'] = CardColor(chosen_color)
                except ValueError:
                    await self.send_error(f'Invalid color: {chosen_color}')
                    return
            else:
                await self.send_error('Wild card requires chosen_color')
                return

        # 如果是指定目標的牌
        if card.card_type in [CardType.SWAP_HAND, CardType.TARGET_DRAW2]:
            if target_player_index is not None:
                command_kwargs['target_player_index'] = target_player_index
            else:
                await self.send_error('This card requires target_player_index')
                return

        # 如果是偷牌
        if card.card_type == CardType.STEAL_CARD:
            if target_player_index is not None and return_card_index is not None:
                command_kwargs['target_player_index'] = target_player_index
                command_kwargs['return_card_index'] = return_card_index
            else:
                await self.send_error('Steal card requires target_player_index and return_card_index')
                return

        command = PlayCardCommand(**command_kwargs)

        # 執行打牌
        result = engine.play_turn(command)

        # 廣播打牌結果
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'card_played',
                'payload': result
            }
        )

    async def handle_draw_card(self):
        # 處理抽牌動作
        engine = GameConsumer.game_engines.get(self.room_code)
        if not engine:
            await self.send_error('Game not started')
            return

        # [15分鐘超時機制] 檢查遊戲是否超時
        if engine.check_timeout():
            result = engine.force_end_game()
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'game_ended',
                    'payload': result
                }
            )
            return

        # 驗證是否為當前玩家
        current_player = engine.get_current_player()
        if str(current_player.player_id) != str(self.user.id):
            await self.send_error('Not your turn')
            return

        # 抽牌
        count = max(1, engine.draw_penalty)
        drawn = engine.draw_cards_for_player(current_player, count)

        # 清除抽牌懲罰
        if engine.draw_penalty > 0:
            engine.draw_penalty = 0

        # 切換到下一位玩家
        engine.next_player()

        # 廣播抽牌事件
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'card_drawn',
                'payload': {
                    'player_id': current_player.player_id,
                    'count': len(drawn),
                    'next_player': engine.get_current_player().player_id,
                }
            }
        )

    async def handle_use_skill(self, data):
        # 處理使用技能
        engine = GameConsumer.game_engines.get(self.room_code)
        if not engine:
            await self.send_error('Game not started')
            return

        # [15分鐘超時機制] 檢查遊戲是否超時
        if engine.check_timeout():
            result = engine.force_end_game()
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'game_ended',
                    'payload': result
                }
            )
            return

        # 驗證是否為當前玩家
        current_player = engine.get_current_player()
        if str(current_player.player_id) != str(self.user.id):
            await self.send_error('Not your turn')
            return

        # [女皇技能修復] 傳遞累積懲罰資訊給 can_use_skill
        skill_check_params = {
            'has_draw_penalty': engine.draw_penalty > 0
        }

        # 檢查是否可以使用技能
        if not current_player.can_use_skill(**skill_check_params):
            await self.send_error('Cannot use skill now')
            return

        skill_params = data.get('params', {})
        merged_params = {**skill_check_params, **skill_params}
        result = current_player.use_skill(engine, **merged_params)

        # 廣播技能使用結果
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'skill_used',
                'payload': result
            }
        )

    # 事件處理器 

    async def game_started(self, event):
        # 遊戲開始事件
        await self.send(text_data=json.dumps({
            'type': 'game_started',
            **event['payload']
        }))

        # 發送完整遊戲狀態
        await self._send_game_state()

    async def card_played(self, event):
        # 打牌事件
        await self.send(text_data=json.dumps({
            'type': 'card_played',
            **event['payload']
        }))

        # 發送更新的遊戲狀態
        await self._send_game_state()

    async def card_drawn(self, event):
        # 抽牌事件
        await self.send(text_data=json.dumps({
            'type': 'card_drawn',
            **event['payload']
        }))

        # 發送更新的遊戲狀態
        await self._send_game_state()

    async def skill_used(self, event):
        # 技能使用事件
        await self.send(text_data=json.dumps({
            'type': 'skill_used',
            **event['payload']
        }))

        # 發送更新的遊戲狀態
        await self._send_game_state()

    async def game_ended(self, event):
        # 遊戲結束事件 (15分鐘超時或正常結束)
        await self.send(text_data=json.dumps({
            'type': 'game_ended',
            **event['payload']
        }))

        # 發送最終遊戲狀態
        await self._send_game_state()

    # 輔助方法

    async def _send_game_state(self):
        # 發送遊戲狀態
        engine = GameConsumer.game_engines.get(self.room_code)

        if not engine:
            await self.send(text_data=json.dumps({
                'type': 'game_state',
                'state': None
            }))
            return

        # 建立遊戲狀態快照
        game_state = GameState.from_engine(engine)

        # 建立玩家手牌狀態（只發送給該玩家）
        player = None
        for p in engine.players:
            if str(p.player_id) == str(self.user.id):
                player = p
                break

        hand_state = None
        if player:
            hand_state = PlayerHandState.from_player(
                player,
                engine.current_color,
                engine.current_number,
                engine.draw_penalty  # [累積懲罰機制] 傳遞累積懲罰數
            )
            # 添加 is_my_turn 屬性
            hand_dict = hand_state.to_dict()
            current_player = engine.get_current_player()
            hand_dict['is_my_turn'] = (str(player.player_id) == str(current_player.player_id))
        else:
            hand_dict = None

        await self.send(text_data=json.dumps({
            'type': 'game_state',
            'state': game_state.to_dict(),
            'hand': hand_dict
        }))

    async def send_error(self, message: str):
        # 發送錯誤訊息
        await self.send(text_data=json.dumps({
            'type': 'error',
            'message': message
        }))

    @database_sync_to_async
    def _is_room_member(self):
        # 檢查是否為房間成員
        return Room.objects.filter(
            code=self.room_code,
            members__user=self.user
        ).exists()

    @database_sync_to_async
    def _is_host(self):
        #　檢查是否為房主
        room = Room.objects.filter(code=self.room_code).first()
        return room and room.host_id == self.user.id

    @database_sync_to_async
    def _get_room_members(self):
        # 獲取房間成員列表
        members = RoomMember.objects.filter(
            room__code=self.room_code
        ).select_related('user__player_profile').all()

        return [
            {
                'user_id': member.user.id,
                'nickname': member.user.player_profile.nickname if hasattr(member.user, 'player_profile') else member.user.username,
            }
            for member in members
        ]

    @database_sync_to_async
    def _assign_random_skill(self):
        # 隨機分配技能
        import random
        skill_types = ['seer', 'painter', 'scout', 'queen']
        return random.choice(skill_types)
