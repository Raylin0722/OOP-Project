# backend/game/game_consumer.py
# 遊戲 WebSocket Consumer
# 整合 GameEngine 與 WebSocket，提供即時遊戲功能：
# 1. 遊戲狀態同步
# 2. 玩家出牌
# 3. 技能使用
# 4. 遊戲事件廣播
#

import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any
from urllib.parse import parse_qs
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction

from .engine import (
    GameEngine, GamePhase, GameState, PlayerHandState,
    Player, SkillFactory,
    CardColor, CardType, PlayCardCommand,
    DeckFactory,
)
from .ai_player import get_default_ai_player
from .models import Room, RoomMember, MatchRecord, MatchParticipant, PlayerProfile


TEST_AI_TURN_DELAY_SECONDS = 1.1
DISCONNECTED_AI_REPLACE_SECONDS = 180


class GameConsumer(AsyncWebsocketConsumer):
    # 遊戲 WebSocket Consumer，處理遊戲進行中的所有 WebSocket 通訊

    # 類別變數：存儲所有房間的遊戲引擎實例
    # key: room_code, value: GameEngine
    game_engines: Dict[str, GameEngine] = {}
    disconnected_players: Dict[str, Dict[str, Dict[str, Any]]] = {}
    room_monitor_tasks: Dict[str, asyncio.Task] = {}
    game_events: Dict[str, list[Dict[str, Any]]] = {}
    ai_turn_locks: Dict[str, asyncio.Lock] = {}
    start_game_locks: Dict[str, asyncio.Lock] = {}
    last_game_results: Dict[str, Dict[str, Any]] = {}

    async def connect(self):
        """建立 WebSocket 連接"""
        self.room_code = self.scope['url_route']['kwargs']['code']
        self.group_name = f'game_{self.room_code}'
        self.user = self.scope.get('user')
        query_params = parse_qs(self.scope.get('query_string', b'').decode())
        self.is_debug_connection = query_params.get('debug', ['0'])[0] == '1'

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4401)
            return

        # 驗證是否為房間成員
        if not await self._is_room_member():
            await self.close(code=4403)
            return
        if not self.is_debug_connection and self._is_rejoin_blocked():
            await self.close(code=4408)
            return

        # 加入房間群組
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        if not self.is_debug_connection:
            await self._handle_player_reconnected()
            await self._ensure_started_for_playing_room()

        # 發送當前遊戲狀態
        await self._send_game_state()
    async def disconnect(self, close_code):
        # 斷開 WebSocket 連接
        if not getattr(self, 'is_debug_connection', False):
            await self._handle_player_disconnected()
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        # 接收客戶端訊息
        try:
            data = json.loads(text_data)
            action = data.get('action')

            if action == 'start_game':
                await self.handle_start_game(data)
            elif action == 'play_card':
                await self.handle_play_card(data)
            elif action == 'draw_card':
                await self.handle_draw_card()
            elif action == 'use_skill':
                await self.handle_use_skill(data)
            elif action == 'force_settlement':
                await self.handle_force_settlement()
            elif action == 'get_state':
                await self._send_game_state()
            elif action == 'debug_state':
                await self._send_debug_state()
            else:
                await self.send_error(f'Unknown action: {action}')

        except json.JSONDecodeError:
            await self.send_error('Invalid JSON')
        except Exception as e:
            await self.send_error(f'Error: {str(e)}')

    # 遊戲動作處理
    async def handle_start_game(self, data=None):
        # 處理開始遊戲
        # 只有房主可以開始遊戲
        lock = GameConsumer.start_game_locks.setdefault(self.room_code, asyncio.Lock())
        async with lock:
            if GameConsumer.game_engines.get(self.room_code):
                await self._send_game_state()
                return
            await self._start_game_unlocked(data)
            return

    async def _start_game_unlocked(self, data=None):
        is_host = await self._is_host()
        room_is_playing = await self._is_room_playing()
        if not is_host and not room_is_playing:
            await self.send_error('Only host can start the game')
            return

        # 獲取房間成員
        members = await self._get_room_members()

        test_mode = bool((data or {}).get('test_mode'))

        if len(members) < 2 and not test_mode:
            await self.send_error('Need at least 2 players')
            return

        # 決定這場遊戲總共需要幾個玩家
        assigned_skill_types = await self._assign_random_skills()

        # 建立玩家列表
        players = []
        for member in members:
            skill_type = assigned_skill_types.pop(0)
            skill = SkillFactory.create_skill(skill_type)
            player = Player(
                player_id=str(member['user_id']),
                name=member['nickname'],
                skill=skill,
                is_ai=bool(member.get('is_ai')),
            )
            players.append(player)

        # 建立遊戲引擎
        while test_mode and len(players) < 4:
            skill_type = assigned_skill_types.pop(0)
            skill = SkillFactory.create_skill(skill_type)
            ai_number = len(players)
            players.append(Player(
                player_id=f'ai_{ai_number}',
                name=f'AI Player {ai_number}',
                skill=skill,
                is_ai=True,
            ))
            print(f'[test-ai] added AI player ai_{ai_number} to room {self.room_code}', flush=True)

        engine = GameEngine(players)
        result = engine.start_game()

        # 存儲遊戲引擎
        GameConsumer.game_engines[self.room_code] = engine
        await self._mark_room_playing(test_mode)

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
        self._ensure_room_monitor()
        # Schedule AI turns in background to avoid blocking this consumer
        asyncio.create_task(self._run_test_ai_turns(engine))

    async def _ensure_started_for_playing_room(self):
        if GameConsumer.game_engines.get(self.room_code):
            return
        if not await self._is_room_playing():
            return
        await self.handle_start_game({'auto_start': True})

    async def handle_force_settlement(self):
        engine = GameConsumer.game_engines.get(self.room_code)
        if not engine:
            await self.send_error('Game not started')
            return

        if not await self._is_host():
            await self.send_error('Only host can force settlement')
            return

        result = engine.force_end_game(
            end_reason='forced_settlement',
            end_reason_text='forced_settlement',
        )
        if not result.get('success'):
            await self.send_error(result.get('error', 'Failed to force settlement'))
            return

        result['forced_by'] = self.user.id
        result['forced_by_name'] = getattr(self.user, 'username', '')
        self._record_game_event('forced_settlement', result)
        await self._finish_game(engine, result)

    async def _finish_game(self, engine, result):
        if not result or not result.get('success') or not result.get('game_over'):
            return

        GameConsumer.last_game_results[self.room_code] = result

        final_rankings = result.get('final_rankings') or engine.get_competition_rankings()
        result['final_rankings'] = final_rankings

        try:
            results = await self._persist_match_result(
                engine,
                final_rankings=final_rankings,
                end_reason=result.get('end_reason'),
            )
            result['match_results'] = results
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'match_results',
                    'payload': {'results': results},
                }
            )
        except Exception as exc:
            error_message = str(exc)
            result['match_results'] = []
            result['persistence_error'] = error_message
            print(f'[persist-match] failed to persist results for room {self.room_code}: {error_message}', flush=True)

        reset_result = await self._reset_room_after_game()

        if reset_result.get('room_deleted'):
            await self.channel_layer.group_send(
                f'room_{self.room_code}',
                {
                    'type': 'room.deleted',
                }
            )
        else:
            await self.channel_layer.group_send(
                f'room_{self.room_code}',
                {
                    'type': 'room.updated',
                    'payload': {
                        'test_mode': False,
                        'game_finished': True,
                        'game_end_reason': result.get('end_reason'),
                        'game_end_reason_text': result.get('end_reason_text'),
                        'ai_cleared': reset_result.get('ai_cleared', 0),
                    },
                }
            )

        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'game_ended',
                'payload': result,
            }
        )
        self._schedule_finished_room_cleanup()

    def _schedule_finished_room_cleanup(self):
        monitor_task = GameConsumer.room_monitor_tasks.pop(self.room_code, None)
        if monitor_task and not monitor_task.done():
            monitor_task.cancel()

        asyncio.create_task(self._cleanup_finished_room_after_delay())

    async def _cleanup_finished_room_after_delay(self):
        await asyncio.sleep(1)
        engine = GameConsumer.game_engines.get(self.room_code)
        if engine and engine.phase == GamePhase.FINISHED:
            GameConsumer.game_engines.pop(self.room_code, None)
            GameConsumer.disconnected_players.pop(self.room_code, None)
            GameConsumer.ai_turn_locks.pop(self.room_code, None)
            GameConsumer.start_game_locks.pop(self.room_code, None)

    async def handle_play_card(self, data):
        # 處理打牌動作
        engine = GameConsumer.game_engines.get(self.room_code)
        if not engine:
            await self.send_error('Game not started')
            return

        # [15分鐘超時機制] 檢查遊戲是否超時

        if engine.check_timeout():
            result = engine.force_end_game()
            await self._finish_game(engine, result)
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
                target_error = self._validate_target_player_index(engine, current_player, target_player_index)
                if target_error:
                    await self.send_error(target_error)
                    return
                command_kwargs['target_player_index'] = target_player_index
            else:
                await self.send_error('This card requires target_player_index')
                return

        # 如果是偷牌
        if card.card_type == CardType.STEAL_CARD:
            if target_player_index is not None and return_card_index is not None:
                target_error = self._validate_target_player_index(engine, current_player, target_player_index)
                if target_error:
                    await self.send_error(target_error)
                    return
                command_kwargs['target_player_index'] = target_player_index
                command_kwargs['return_card_index'] = return_card_index
            else:
                await self.send_error('Steal card requires target_player_index and return_card_index')
                return

        command = PlayCardCommand(**command_kwargs)

        # 執行打牌
        result = engine.play_turn(command)
        if not result.get('success'):
            await self.send_error(result.get('error', 'Failed to play card'))
            return

        result.setdefault('player_id', current_player.player_id)
        result.setdefault('player_name', current_player.name)

        # 廣播打牌結果
        self._record_game_event('card_played', result)
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'card_played',
                'payload': result
            }
        )
        asyncio.create_task(self._broadcast_game_state())
        if result.get('game_over'):
            await self._finish_game(engine, result)
            return

        # Run AI turns asynchronously so we don't block this handler
        asyncio.create_task(self._run_test_ai_turns(engine))

    def _validate_target_player_index(self, engine, current_player, target_player_index):
        try:
            target_index = int(target_player_index)
        except (TypeError, ValueError):
            return 'Invalid target_player_index'

        if not (0 <= target_index < len(engine.players)):
            return 'Invalid target_player_index'

        target_player = engine.players[target_index]
        if str(target_player.player_id) == str(current_player.player_id):
            return 'Cannot target yourself'

        if target_player.has_finished():
            return 'Cannot target a finished player'

        return None

    async def handle_draw_card(self):
        # 處理抽牌動作
        engine = GameConsumer.game_engines.get(self.room_code)
        if not engine:
            await self.send_error('Game not started')
            return

        # [15分鐘超時機制] 檢查遊戲是否超時

        if engine.check_timeout():
            result = engine.force_end_game()
            await self._finish_game(engine, result)
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
        self._record_game_event('card_drawn', {
            'player_id': current_player.player_id,
            'player_name': current_player.name,
            'count': len(drawn),
            'next_player': engine.get_current_player().player_id,
        })
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'card_drawn',
                'payload': {
                    'player_id': current_player.player_id,
                    'player_name': current_player.name,
                    'count': len(drawn),
                    'next_player': engine.get_current_player().player_id,
                }
            }
        )
        asyncio.create_task(self._broadcast_game_state())
        # Run AI turns asynchronously so we don't block this handler
        asyncio.create_task(self._run_test_ai_turns(engine))

    async def handle_use_skill(self, data):
        # 處理使用技能
        engine = GameConsumer.game_engines.get(self.room_code)
        if not engine:
            await self.send_error('Game not started')
            return

        # [15分鐘超時機制] 檢查遊戲是否超時

        if engine.check_timeout():
            result = engine.force_end_game()
            await self._finish_game(engine, result)
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

        try:
            skill_params = self._normalize_skill_params(current_player, data.get('params', {}) or {})
        except ValueError as exc:
            await self.send_error(str(exc))
            return

        merged_params = {**skill_check_params, **skill_params}
        result = current_player.use_skill(engine, **merged_params)
        if not result.get('success'):
            await self.send_error(result.get('message', 'Failed to use skill'))
            return

        result.setdefault('player_id', current_player.player_id)
        result.setdefault('player_name', current_player.name)

        self._record_game_event('skill_used', result)

        # 廣播技能使用結果

        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'skill_used',
                'payload': result
            }
        )
        asyncio.create_task(self._broadcast_game_state())
        if result.get('game_over'):
            await self._finish_game(engine, result)
            return

        # Run AI turns asynchronously so we don't block this handler
        asyncio.create_task(self._run_test_ai_turns(engine))
    def _normalize_skill_params(self, current_player, skill_params):
        """Normalize frontend skill parameters into engine-level objects.

        Frontend should send simple JSON values. Some skill implementations need
        actual card objects, so this method converts card indexes/names into the
        corresponding card object from the current player's hand.
        """
        params = dict(skill_params or {})

        if 'discard_card_index' in params and 'discard_card' not in params:
            try:
                discard_index = int(params.pop('discard_card_index'))
            except (TypeError, ValueError):
                raise ValueError('Invalid discard_card_index')

            discard_card = current_player.get_hand().get_card_at(discard_index)
            if discard_card is None:
                raise ValueError('Invalid discard_card_index')

            params['discard_card'] = discard_card

        if 'discard_card_name' in params and 'discard_card' not in params:
            discard_card_name = str(params.pop('discard_card_name'))
            for card in current_player.get_hand().get_cards():
                if str(card) == discard_card_name:
                    params['discard_card'] = card
                    break
            if 'discard_card' not in params:
                raise ValueError('Discard card not found in hand')

        if 'new_order' in params:
            raw_order = params.get('new_order')
            if not isinstance(raw_order, (list, tuple)):
                raise ValueError('Invalid new_order')
            try:
                params['new_order'] = [int(index) for index in raw_order]
            except (TypeError, ValueError):
                raise ValueError('Invalid new_order')

        return params


    # 事件處理器 
    async def _run_test_ai_turns(self, engine):
        # Test mode helper: AI players use a simple first-playable-card policy.
        lock = GameConsumer.ai_turn_locks.setdefault(self.room_code, asyncio.Lock())
        if lock.locked():
            return

        async with lock:
            await self._run_test_ai_turns_locked(engine)

    async def _run_test_ai_turns_locked(self, engine):
        max_ai_turns = len(engine.players) * 2

        for _ in range(max_ai_turns):
            if engine.phase != GamePhase.PLAYING:
                return

            current_player = engine.get_current_player()
            if not self._is_test_ai_player(current_player):
                print(f'[test-ai] current player is human {current_player.player_id}; waiting', flush=True)
                return

            await self._broadcast_game_state()
            await asyncio.sleep(TEST_AI_TURN_DELAY_SECONDS)
            result = self._play_test_ai_turn(engine, current_player)
            print(f'[test-ai] room={self.room_code} player={current_player.player_id} result={result}', flush=True)
            event_type = 'card_played' if result.get('action') == 'play_card' else 'card_drawn'
            self._record_game_event(event_type, result)

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': event_type,
                    'payload': result,
                }
            )
            await self._broadcast_game_state()

            if result.get('game_over'):
                await self._finish_game(engine, result)
                return

    def _play_test_ai_turn(self, engine, current_player):
        model_result = self._play_model_ai_turn(engine, current_player)
        if model_result:
            return model_result

        return self._play_first_playable_ai_turn(engine, current_player)

    def _play_model_ai_turn(self, engine, current_player):
        current_index = engine.current_player_index
        try:
            decision = get_default_ai_player().decide(engine, current_index)
        except Exception as exc:
            print(f'[test-ai] model decision failed; fallback to first_playable: {exc}', flush=True)
            return None

        payload = decision.payload
        action = payload.get('action')
        if action == 'draw_card':
            result = self._draw_for_player(engine, current_player, 'model_draw')
            result['ai_policy'] = 'dqn_checkpoint'
            result['rlcard_action'] = decision.rlcard_action
            return result

        if action == 'use_skill':
            print(f'[test-ai] model chose unsupported skill action {decision.rlcard_action}; fallback', flush=True)
            return None

        if action != 'play_card':
            print(f'[test-ai] model chose unknown action {payload}; fallback', flush=True)
            return None

        card = self._find_ai_payload_card(current_player, payload)
        if not card or not engine._can_play_card(card):
            print(f'[test-ai] model card unavailable/unplayable {decision.rlcard_action}; fallback', flush=True)
            return None

        command_kwargs = {
            'card': card,
            'player_id': current_player.player_id,
        }

        if card.card_type in [CardType.WILD, CardType.WILD_DRAW4]:
            color = payload.get('chosen_color') or payload.get('color')
            try:
                command_kwargs['chosen_color'] = CardColor(color) if color else self._choose_test_ai_color(current_player, engine.current_color)
            except ValueError:
                command_kwargs['chosen_color'] = self._choose_test_ai_color(current_player, engine.current_color)

        if card.card_type in [CardType.SWAP_HAND, CardType.TARGET_DRAW2, CardType.STEAL_CARD]:
            target_index = payload.get('target_player_index')
            if target_index is None or target_index == engine.current_player_index or not 0 <= target_index < len(engine.players):
                target_index = self._first_other_player_index(engine)
            command_kwargs['target_player_index'] = target_index

        if card.card_type == CardType.STEAL_CARD:
            command_kwargs['return_card_index'] = payload.get('return_card_index', 0)

        command = PlayCardCommand(**command_kwargs)
        if not command.validate():
            print(f'[test-ai] model command invalid {decision.rlcard_action}; fallback', flush=True)
            return None

        result = engine.play_turn(command)
        if not result.get('success'):
            print(f'[test-ai] model play failed {decision.rlcard_action}: {result}; fallback', flush=True)
            return None

        result['action'] = 'play_card'
        result['player_id'] = current_player.player_id
        result['ai_policy'] = 'dqn_checkpoint'
        result['rlcard_action'] = decision.rlcard_action
        return result

    def _play_first_playable_ai_turn(self, engine, current_player):
        hand = current_player.get_hand()
        cards = hand.get_cards()

        for card in cards:
            if not engine._can_play_card(card):
                continue

            command = self._build_test_ai_command(engine, current_player, card)
            if not command.validate():
                continue

            result = engine.play_turn(command)
            if not result.get('success'):
                print(f'[test-ai] failed to play {card}: {result}', flush=True)
                continue

            result['action'] = 'play_card'
            result['player_id'] = current_player.player_id
            result['ai_policy'] = 'first_playable'
            return result

        count = max(1, engine.draw_penalty)
        drawn = engine.draw_cards_for_player(current_player, count)
        if engine.draw_penalty > 0:
            engine.draw_penalty = 0
        engine.next_player()

        return {
            'success': True,
            'action': 'draw_card',
            'player_id': current_player.player_id,
            'player_name': current_player.name,
            'count': len(drawn),
            'next_player': engine.get_current_player().player_id,
            'ai_policy': 'first_playable',
        }

    def _find_ai_payload_card(self, current_player, payload):
        card_name = str(payload.get('card_name') or '').strip()
        if not card_name:
            return None

        parts = card_name.split()
        wanted_color = parts[0] if len(parts) >= 2 else None
        wanted_value = parts[-1] if parts else ''

        for card in current_player.get_hand().get_cards():
            if card.value != wanted_value:
                continue
            if card.color == CardColor.BLACK:
                return card
            if wanted_color is None or card.color.value == wanted_color:
                return card

        return None

    def _build_test_ai_command(self, engine, current_player, card):
        command_kwargs = {
            'card': card,
            'player_id': current_player.player_id,
        }

        if card.card_type in [CardType.WILD, CardType.WILD_DRAW4]:
            command_kwargs['chosen_color'] = self._choose_test_ai_color(current_player, engine.current_color)

        if card.card_type in [CardType.SWAP_HAND, CardType.TARGET_DRAW2, CardType.STEAL_CARD]:
            command_kwargs['target_player_index'] = self._first_other_player_index(engine)

        if card.card_type == CardType.STEAL_CARD:
            command_kwargs['return_card_index'] = 0

        return PlayCardCommand(**command_kwargs)

    def _choose_test_ai_color(self, current_player, fallback_color):
        color_counts = {}
        for card in current_player.get_hand().get_cards():
            if card.color == CardColor.BLACK:
                continue
            color_counts[card.color] = color_counts.get(card.color, 0) + 1

        if color_counts:
            return max(color_counts, key=color_counts.get)

        return fallback_color if fallback_color != CardColor.BLACK else CardColor.RED

    def _first_other_player_index(self, engine):
        current_index = engine.current_player_index
        for index in range(len(engine.players)):
            if index != current_index:
                return index
        return current_index

    @staticmethod
    def _is_test_ai_player(player):
        return str(player.player_id).startswith('ai_')

    async def _handle_player_disconnected(self):
        engine = GameConsumer.game_engines.get(getattr(self, 'room_code', None))
        if not engine or engine.phase != GamePhase.PLAYING:
            return

        player = self._find_player_by_original_id(engine, str(self.user.id))
        if not player or self._is_test_ai_player(player):
            return

        player.is_disconnected = True
        disconnected = GameConsumer.disconnected_players.setdefault(self.room_code, {})
        disconnected[str(self.user.id)] = {
            'disconnected_at': datetime.now(),
            'name': player.name,
            'replaced': bool(getattr(player, 'is_ai_replacement', False)),
        }
        await self._broadcast_game_state()
        self._ensure_room_monitor()

    async def _handle_player_reconnected(self):
        engine = GameConsumer.game_engines.get(getattr(self, 'room_code', None))
        if not engine:
            return

        player_id = str(self.user.id)
        disconnected = GameConsumer.disconnected_players.get(self.room_code, {})
        info = disconnected.pop(player_id, None)
        player = self._find_player_by_original_id(engine, player_id)

        if not player:
            return

        if info and getattr(player, 'is_ai_replacement', False):
            player.player_id = player_id
            player.name = getattr(player, 'original_name', info.get('name', player.name))
            player.is_ai = False
            player.is_ai_replacement = False

        player.is_disconnected = False
        await self._broadcast_game_state()

    def _ensure_room_monitor(self):
        task = GameConsumer.room_monitor_tasks.get(self.room_code)
        if task and not task.done():
            return

        GameConsumer.room_monitor_tasks[self.room_code] = asyncio.create_task(
            self._monitor_disconnected_players(self.room_code, self.group_name)
        )

    async def _monitor_disconnected_players(self, room_code, group_name):
        try:
            while True:
                await asyncio.sleep(1)
                engine = GameConsumer.game_engines.get(room_code)
                disconnected = GameConsumer.disconnected_players.get(room_code, {})

                if not engine or engine.phase != GamePhase.PLAYING:
                    break

                await self.channel_layer.group_send(group_name, {'type': 'game_state_updated'})

                now = datetime.now()
                replaced_any = False
                for player_id, info in list(disconnected.items()):
                    elapsed = (now - info['disconnected_at']).total_seconds()
                    if not info.get('replaced') and elapsed >= DISCONNECTED_AI_REPLACE_SECONDS:
                        replaced_any = self._replace_disconnected_player_with_ai(engine, player_id, info) or replaced_any

                if replaced_any:
                    await self.channel_layer.group_send(group_name, {'type': 'game_state_updated'})

                current_player = engine.get_current_player()
                if self._is_test_ai_player(current_player):
                    await self._run_test_ai_turns(engine)
                    continue

                original_id = str(getattr(current_player, 'original_player_id', current_player.player_id))
                remaining = engine.get_turn_remaining_time()
                if remaining and remaining.total_seconds() > 0:
                    continue

                reason = 'disconnect_turn_timeout' if original_id in disconnected else 'turn_timeout'
                result = self._draw_for_player(engine, current_player, reason)
                self._record_game_event('card_drawn', result)
                await self.channel_layer.group_send(
                    group_name,
                    {
                        'type': 'card_drawn',
                        'payload': result,
                    }
                )
                await self._run_test_ai_turns(engine)
        finally:
            if GameConsumer.room_monitor_tasks.get(room_code) is asyncio.current_task():
                GameConsumer.room_monitor_tasks.pop(room_code, None)

    def _replace_disconnected_player_with_ai(self, engine, player_id, info):
        player = self._find_player_by_original_id(engine, player_id)
        if not player:
            return False

        original_name = getattr(player, 'original_name', info.get('name', player.name))
        player.original_player_id = player_id
        player.original_name = original_name
        player.player_id = f'ai_replacement_{player_id}'
        player.name = f'{original_name}（AI代打）'
        player.is_ai = True
        player.is_ai_replacement = True
        player.is_disconnected = True
        player.settlement_penalty = True
        info['replaced'] = True
        return True

    def _find_player_by_original_id(self, engine, player_id):
        for player in engine.players:
            original_id = str(getattr(player, 'original_player_id', player.player_id))
            if original_id == str(player_id):
                return player
        return None

    def _is_rejoin_blocked(self):
        engine = GameConsumer.game_engines.get(getattr(self, 'room_code', None))
        if not engine:
            return False

        player = self._find_player_by_original_id(engine, str(self.user.id))
        if not player:
            return False

        return bool(getattr(player, 'is_ai_replacement', False) or getattr(player, 'settlement_penalty', False))

    def _draw_for_player(self, engine, player, reason):
        count = max(1, engine.draw_penalty)
        drawn = engine.draw_cards_for_player(player, count)
        if engine.draw_penalty > 0:
            engine.draw_penalty = 0
        engine.next_player()

        return {
            'success': True,
            'action': 'draw_card',
            'player_id': player.player_id,
            'player_name': player.name,
            'count': len(drawn),
            'next_player': engine.get_current_player().player_id,
            'reason': reason,
        }

    async def _broadcast_game_state(self):
        await self.channel_layer.group_send(
            self.group_name,
            {'type': 'game_state_updated'}
        )


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


    async def game_state_updated(self, event):
        await self._send_game_state()

    async def match_results(self, event):
        await self.send(text_data=json.dumps({
            'type': 'match_results',
            **event['payload']
        }))
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
                engine.draw_penalty,
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

    async def _send_debug_state(self):
        engine = GameConsumer.game_engines.get(self.room_code)
        if not engine:
            await self.send(text_data=json.dumps({
                'type': 'debug_state',
                'state': None,
                'players': [],
                'events': [],
            }))
            return

        game_state = GameState.from_engine(engine).to_dict()
        current_player = engine.get_current_player()
        players = []
        for index, player in enumerate(engine.players):
            players.append({
                'index': index,
                'player_id': player.player_id,
                'original_player_id': getattr(player, 'original_player_id', player.player_id),
                'name': player.name,
                'is_current': index == engine.current_player_index,
                'is_ai': bool(getattr(player, 'is_ai', False)),
                'is_ai_replacement': bool(getattr(player, 'is_ai_replacement', False)),
                'is_disconnected': bool(getattr(player, 'is_disconnected', False)),
                'settlement_penalty': bool(getattr(player, 'settlement_penalty', False)),
                'skill_name': player.skill.name if player.skill else 'None',
                'hand_size': player.get_hand_size(),
                'hand': [str(card) for card in player.get_hand().get_cards()],
                'playable_cards': PlayerHandState.from_player(
                    player,
                    engine.current_color,
                    engine.current_number,
                    engine.draw_penalty,
                ).playable_cards,
            })

        await self.send(text_data=json.dumps({
            'type': 'debug_state',
            'state': game_state,
            'current_player': {
                'player_id': current_player.player_id,
                'name': current_player.name,
                'index': engine.current_player_index,
            },
            'players': players,
            'discard_pile': [str(card) for card in engine.discard_pile],
            'last_game_result': GameConsumer.last_game_results.get(self.room_code),
            'events': GameConsumer.game_events.get(self.room_code, [])[-100:],
        }))

    def _record_game_event(self, event_type, payload):
        events = GameConsumer.game_events.setdefault(self.room_code, [])
        events.append({
            'time': datetime.now().isoformat(timespec='seconds'),
            'type': event_type,
            'payload': payload,
        })
        del events[:-100]

    async def send_error(self, message: str):
        # 發送錯誤訊息
        await self.send(text_data=json.dumps({
            'type': 'error',
            'message': message,
        }))
    @database_sync_to_async
    def _is_room_member(self):
        # 檢查是否為房間成員
        return Room.objects.filter(
            code=self.room_code,
            members__user=self.user,
        ).exists()

    @database_sync_to_async
    def _is_host(self):
        #　檢查是否為房主
        room = Room.objects.filter(code=self.room_code).first()
        return room and room.host_id == self.user.id

    @database_sync_to_async
    def _is_room_playing(self):
        return Room.objects.filter(code=self.room_code, status=Room.Status.PLAYING).exists()

    @database_sync_to_async
    def _get_room_members(self):
        # 獲取房間成員列表
        members = RoomMember.objects.filter(
            room__code=self.room_code,
        ).select_related('user__player_profile').order_by('joined_at', 'id')

        payload = []
        for index, member in enumerate(members):
            if member.is_ai or member.user_id is None:
                payload.append({
                    'user_id': f'ai_{member.id or index}',
                    'nickname': member.ai_name or f'AI Player {index + 1}',
                    'is_ai': True,
                })
                continue

            payload.append({
                'user_id': member.user.id,
                'nickname': member.user.player_profile.nickname if hasattr(member.user, 'player_profile') else member.user.username,
                'is_ai': False,
            })

        return payload

    async def _assign_random_skills(self) -> list[str]:
        """隨機分配 4 個不重複技能。"""
        import random

        skill_types = ['seer', 'painter', 'scout', 'queen']
        return random.sample(skill_types, 4)

    @database_sync_to_async
    def _set_room_playing(self):
        Room.objects.filter(code=self.room_code).update(status=Room.Status.PLAYING)

    @database_sync_to_async
    def _reset_room_after_game(self):
        """
        Reset room after a game finishes.

        - Remove temporary AI RoomMember rows.
        - Never leave room.host pointing to an AI member.
        - Delete the room if no human members remain.
        """
        try:
            room = Room.objects.select_for_update().get(code=self.room_code)
        except Room.DoesNotExist:
            return {
                'room_deleted': True,
                'ai_cleared': 0,
            }

        ai_cleared, _ = RoomMember.objects.filter(
            room=room,
            user__isnull=True,
            is_ai=True,
        ).delete()

        human_members = list(
            RoomMember.objects
            .select_related('user')
            .filter(room=room, user__isnull=False, is_ai=False)
            .order_by('joined_at', 'id')
        )

        if not human_members:
            room.delete()
            try:
                from .views import TEST_MODE_ROOM_CODES
                TEST_MODE_ROOM_CODES.discard(self.room_code)
            except Exception:
                pass
            return {
                'room_deleted': True,
                'ai_cleared': ai_cleared,
            }

        if room.host_id not in {member.user_id for member in human_members}:
            room.host = human_members[0].user

        room.status = Room.Status.FULL if len(human_members) >= 4 else Room.Status.WAITING
        room.save(update_fields=['host', 'status'])

        try:
            from .views import TEST_MODE_ROOM_CODES
            TEST_MODE_ROOM_CODES.discard(self.room_code)
        except Exception:
            pass

        return {
            'room_deleted': False,
            'ai_cleared': ai_cleared,
            'human_count': len(human_members),
            'host_id': room.host_id,
            'status': room.status,
        }

    async def _mark_room_playing(self, test_mode=False):
        await self._set_room_playing()
        await self.channel_layer.group_send(
            f'room_{self.room_code}',
            {
                'type': 'room.updated',
                'payload': {'test_mode': bool(test_mode)},
            }
        )

    @database_sync_to_async
    def _persist_match_result(self, engine, final_rankings=None, end_reason=None):
        """
        Persist match result: create MatchRecord and MatchParticipant entries,
        update PlayerProfile.total_score and win_rate.
        """
        User = get_user_model()

        award_for_rank = {1: 10, 2: 5, 3: -5, 4: -10}

        start_time = engine.game_start_time or timezone.now()
        end_time = timezone.now()

        results = []
        with transaction.atomic():
            match = MatchRecord.objects.create(start_time=start_time, end_time=end_time)

            rankings = final_rankings or engine.get_competition_rankings()
            print(
                f'[persist-match] create match={match.id} room={self.room_code} '
                f'end_reason={end_reason} rankings={rankings}',
                flush=True,
            )

            for ranking in rankings:
                rank = ranking.get('rank')
                hand_size = ranking.get('hand_size')
                ranking_player_id = ranking.get('player_id')
                player = engine._find_player_by_id(ranking_player_id)
                player_id = getattr(player, 'original_player_id', ranking_player_id)

                # Skip pure AI players. AI replacement players keep original_player_id
                # and are handled as disconnected human players.
                if str(player_id).startswith('ai_'):
                    print(f'[persist-match] skip pure AI player_id={player_id}', flush=True)
                    continue

                try:
                    user = User.objects.get(id=int(player_id))
                except Exception as exc:
                    print(f'[persist-match] skip unknown user player_id={player_id}: {exc}', flush=True)
                    continue

                # Detect whether this player was replaced by AI due to disconnect.
                is_replaced = bool(getattr(player, 'is_ai_replacement', False))

                base_change = award_for_rank.get(rank, 0)
                extra_penalty = -5 if is_replaced else 0
                score_change = base_change + extra_penalty

                # Ensure trophies never drop below zero when applied.
                profile, _ = PlayerProfile.objects.get_or_create(
                    user=user,
                    defaults={'nickname': user.username}
                )
                new_total = (profile.total_score or 0) + score_change
                if new_total < 0:
                    score_change = - (profile.total_score or 0)
                    new_total = 0

                # For replaced players we do NOT create MatchParticipant, so this
                # match does not count in career stats, but the disconnect penalty
                # still affects trophies.
                if not is_replaced:
                    MatchParticipant.objects.create(
                        match=match,
                        user=user,
                        player_rank=rank,
                        score_change=score_change,
                    )

                profile.total_score = new_total
                profile.save(update_fields=['total_score'])

                if not is_replaced:
                    total_matches = MatchParticipant.objects.filter(user=user).count()
                    wins = MatchParticipant.objects.filter(user=user, player_rank=1).count()
                    profile.win_rate = (wins / total_matches) if total_matches > 0 else 0.0
                    profile.save(update_fields=['win_rate'])

                results.append({
                    'user_id': user.id,
                    'username': user.username,
                    'rank': rank,
                    'hand_size': hand_size,
                    'score_change': score_change,
                    'is_disconnected': is_replaced,
                    'final_total_score': profile.total_score,
                    'win_rate': getattr(profile, 'win_rate', None) if not is_replaced else None,
                })

            print(f'[persist-match] saved participants={len(results)} room={self.room_code}', flush=True)

        return results
