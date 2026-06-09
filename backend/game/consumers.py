import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .models import MatchmakingTicket, Room
from .views import _room_payload
from .services.matchmaking_service import MatchmakingService


async def _safe_group_add(channel_layer, group_name, channel_name):
    try:
        await channel_layer.group_add(group_name, channel_name)
        return True
    except Exception as exc:
        print(f'[channel-layer] group_add failed group={group_name}: {exc}', flush=True)
        return False


async def _safe_group_discard(channel_layer, group_name, channel_name):
    try:
        await channel_layer.group_discard(group_name, channel_name)
        return True
    except Exception as exc:
        print(f'[channel-layer] group_discard failed group={group_name}: {exc}', flush=True)
        return False


class RoomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.code = self.scope['url_route']['kwargs']['code']
        self.group_name = f'room_{self.code}'
        self.user = self.scope.get('user')

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4401)
            return

        if not await self._is_room_member():
            await self.close(code=4403)
            return

        if not await _safe_group_add(self.channel_layer, self.group_name, self.channel_name):
            await self.close(code=4500)
            return
        await self.accept()
        await self._send_room_update()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await _safe_group_discard(self.channel_layer, self.group_name, self.channel_name)

    async def room_updated(self, event):
        if not await self._is_room_member():
            await self.send(text_data=json.dumps({'type': 'room_left'}))
            await self.close()
            return

        await self._send_room_update(event.get('payload') or {})

    async def room_deleted(self, event):
        await self.send(text_data=json.dumps({'type': 'room_deleted'}))
        await self.close()

    async def _send_room_update(self, extra_payload=None):
        room = await self._room_payload()
        if room is None:
            await self.send(text_data=json.dumps({'type': 'room_deleted'}))
            await self.close()
            return

        payload = {
            'type': 'room_update',
            'room': room,
        }
        if extra_payload:
            payload.update(extra_payload)

        await self.send(text_data=json.dumps(payload))

    @database_sync_to_async
    def _is_room_member(self):
        return Room.objects.filter(code=self.code, members__user=self.user).exists()

    @database_sync_to_async
    def _room_payload(self):
        room = (
            Room.objects
            .select_related('host')
            .prefetch_related('members__user__player_profile')
            .filter(code=self.code)
            .first()
        )
        if room is None:
            return None
        return _room_payload(room, self.user)


class MatchmakingConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get('user')

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4401)
            return

        self.group_name = f'user_{self.user.id}'
        if not await _safe_group_add(self.channel_layer, self.group_name, self.channel_name):
            await self.close(code=4500)
            return
        await self.accept()
        await self._send_current_status()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await _safe_group_discard(self.channel_layer, self.group_name, self.channel_name)

    async def matchmaking_updated(self, event):
        await self.send(text_data=json.dumps(event['payload']))

    async def _send_current_status(self):
        payload = await self._status_payload()
        await self.send(text_data=json.dumps(payload))

    @database_sync_to_async
    def _status_payload(self):
        ticket = (
            MatchmakingTicket.objects
            .select_related('source_room')
            .filter(
                user=self.user,
                status=MatchmakingTicket.Status.WAITING,
            )
            .first()
        )

        if ticket is not None:
            payload = {
                'type': 'waiting',
                'ticket': MatchmakingService().ticket_payload(ticket),
            }

            if ticket.source_room_id:
                payload['room'] = _room_payload(ticket.source_room, self.user)

            return payload

        return {
            'type': 'idle',
            'ticket': None,
        }