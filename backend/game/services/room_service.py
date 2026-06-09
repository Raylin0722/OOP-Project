import random

from django.db import transaction
from django.utils import timezone

from ..models import MatchmakingTicket, Room, RoomMember

from .exceptions import ServiceError


ROOM_VISIBILITY_TOGGLE_COOLDOWN_SECONDS = 10


class RoomService:
    """Encapsulates room-management business logic.

    Views should only parse HTTP requests and format responses. This service owns
    room creation, joining, leaving, ready state, visibility, kicking members,
    host transfer, room lifecycle actions, presence cleanup, and room matchmaking
    cancellation side effects that belong to room membership changes.
    """

    def __init__(
        self,
        room_payload_builder=None,
        room_broadcast=None,
        room_deleted_broadcast=None,
        matchmaking_broadcast=None,
        test_mode_room_codes=None,
    ):
        self.room_payload_builder = room_payload_builder
        self.room_broadcast = room_broadcast
        self.room_deleted_broadcast = room_deleted_broadcast
        self.matchmaking_broadcast = matchmaking_broadcast
        self.test_mode_room_codes = test_mode_room_codes

    def room_payload(self, room, user=None):
        if self.room_payload_builder is None or room is None:
            return None
        return self.room_payload_builder(room, user)

    def broadcast_room_update(self, room, payload=None):
        if self.room_broadcast is not None and room is not None:
            self.room_broadcast(room, payload)

    def broadcast_room_deleted(self, code):
        if self.room_deleted_broadcast is not None:
            self.room_deleted_broadcast(code)

    def broadcast_matchmaking_update(self, user_id, payload):
        if self.matchmaking_broadcast is not None and user_id is not None:
            self.matchmaking_broadcast(user_id, payload)

    def broadcast_cancelled_tickets(self, tickets, room=None):
        for ticket in tickets:
            self.broadcast_matchmaking_update(ticket.user_id, {
                'type': 'cancelled',
                'ticket': None,
                'room': self.room_payload(room, ticket.user) if room is not None else None,
            })

    def generate_room_code(self):
        for _ in range(20):
            code = f'{random.SystemRandom().randint(0, 999999):06d}'
            if not Room.objects.filter(code=code).exists():
                return code
        raise RuntimeError('Could not generate room code.')

    def get_room(self, code):
        room = (
            Room.objects
            .select_related('host')
            .prefetch_related('members__user__player_profile')
            .filter(code=code)
            .first()
        )
        if room is None:
            raise ServiceError('room not found.', status=404, code='room_not_found')
        return room

    def active_membership(self, user):
        return (
            RoomMember.objects
            .select_related('room', 'room__host', 'user', 'user__player_profile')
            .prefetch_related('room__members__user__player_profile')
            .filter(user=user, room__status__in=[Room.Status.WAITING, Room.Status.FULL, Room.Status.PLAYING])
            .order_by('-joined_at')
            .first()
        )

    def sync_room_status(self, room):
        member_count = room.members.count()
        if room.status == Room.Status.PLAYING:
            return
        next_status = Room.Status.FULL if member_count >= 4 else Room.Status.WAITING
        if room.status != next_status:
            room.status = next_status
            room.save(update_fields=['status'])

    def cancel_room_matchmaking(self, room):
        tickets = list(
            MatchmakingTicket.objects
            .select_related('user')
            .filter(
                source_room=room,
                status=MatchmakingTicket.Status.WAITING,
            )
        )
        if not tickets:
            return []

        ticket_ids = [ticket.id for ticket in tickets]
        MatchmakingTicket.objects.filter(id__in=ticket_ids).update(
            status=MatchmakingTicket.Status.CANCELLED,
        )

        # 配對取消後回到房間等待狀態；非房主需重新確認準備，避免房主誤觸後立刻再次配對。
        RoomMember.objects.filter(room=room).exclude(user_id=room.host_id).update(is_ready=False)
        self.sync_room_status(room)
        return tickets

    def create_room(self, user):
        with transaction.atomic():
            RoomMember.objects.filter(
                user=user,
                room__status__in=[Room.Status.WAITING, Room.Status.FULL],
            ).delete()
            room = Room.objects.create(
                code=self.generate_room_code(),
                host=user,
                status=Room.Status.WAITING,
            )
            RoomMember.objects.create(room=room, user=user, is_ready=False)
        self.broadcast_room_update(room)
        return room

    def public_rooms(self):
        rooms = (
            Room.objects
            .select_related('host')
            .prefetch_related('members__user__player_profile')
            .filter(
                is_public=True,
                status=Room.Status.WAITING,
            )
            .order_by('-created_at')
        )

        available_rooms = []
        for room in rooms:
            member_count = room.members.count()
            is_matchmaking = room.source_matchmaking_tickets.filter(
                status=MatchmakingTicket.Status.WAITING,
            ).exists()

            if member_count >= 4 or is_matchmaking:
                continue

            available_rooms.append(room)

        return available_rooms

    def set_visibility(self, user, code, data):
        room = self.get_room(code)
        now = timezone.now()

        with transaction.atomic():
            room = Room.objects.select_for_update().get(pk=room.pk)

            if room.host_id != user.id:
                raise ServiceError('only host can change room visibility.', status=403, code='not_room_host')

            if room.status == Room.Status.PLAYING:
                raise ServiceError('cannot change visibility while playing.', status=400, code='room_playing')

            if room.last_visibility_changed_at:
                elapsed = (now - room.last_visibility_changed_at).total_seconds()
                if elapsed < ROOM_VISIBILITY_TOGGLE_COOLDOWN_SECONDS:
                    wait_seconds = max(1, int(ROOM_VISIBILITY_TOGGLE_COOLDOWN_SECONDS - elapsed))
                    error = ServiceError(
                        f'please wait {wait_seconds} seconds before changing visibility again.',
                        status=429,
                        code='visibility_toggle_cooldown',
                    )
                    error.wait_seconds = wait_seconds
                    error.room = room
                    raise error

            next_is_public = bool(data.get('is_public', not room.is_public))
            room.is_public = next_is_public
            room.last_visibility_changed_at = now
            room.save(update_fields=['is_public', 'last_visibility_changed_at'])

        self.broadcast_room_update(room)
        return room

    def join_room(self, user, data):
        code = str(data.get('code', '')).strip()
        if len(code) != 6 or not code.isdigit():
            raise ServiceError('room code must be 6 digits.', code='invalid_room_code')

        room = self.get_room(code)
        if room.status == Room.Status.PLAYING:
            raise ServiceError('room is already playing.', code='room_playing')
        if room.source_matchmaking_tickets.filter(status=MatchmakingTicket.Status.WAITING).exists():
            raise ServiceError('room is matchmaking.', code='room_matchmaking')

        with transaction.atomic():
            room = Room.objects.select_for_update().get(pk=room.pk)
            member_count = room.members.count()
            if not room.members.filter(user=user).exists() and member_count >= 4:
                raise ServiceError('room is full.', code='room_full')

            RoomMember.objects.filter(
                user=user,
                room__status__in=[Room.Status.WAITING, Room.Status.FULL],
            ).exclude(room=room).delete()
            RoomMember.objects.get_or_create(room=room, user=user)
            self.sync_room_status(room)

        self.broadcast_room_update(room)
        return room

    def current_room(self, user):
        membership = self.active_membership(user)
        if membership is None:
            return None

        room = membership.room
        self.sync_room_status(room)
        return room

    def set_ready(self, user, code, data):
        room = self.get_room(code)

        membership = room.members.filter(user=user).first()
        if membership is None:
            raise ServiceError('you are not in this room.', status=403, code='not_room_member')

        if room.source_matchmaking_tickets.filter(status=MatchmakingTicket.Status.WAITING).exists():
            raise ServiceError(
                'matchmaking is in progress; ready state cannot be changed.',
                status=409,
                code='room_matchmaking',
            )

        membership.is_ready = bool(data.get('is_ready', not membership.is_ready))
        membership.save(update_fields=['is_ready'])
        self.broadcast_room_update(room)
        return room

    def leave_room(self, user, code):
        room = self.get_room(code)
        membership = room.members.filter(user=user).first()
        if membership is None:
            return {
                'room': None,
                'room_deleted': False,
                'cancelled_tickets': [],
            }

        cancelled_room_tickets = []
        room_deleted = False

        with transaction.atomic():
            room = Room.objects.select_for_update().get(pk=room.pk)
            membership = RoomMember.objects.select_for_update().filter(room=room, user=user).first()
            if membership is None:
                return {
                    'room': None,
                    'room_deleted': False,
                    'cancelled_tickets': [],
                }

            cancelled_room_tickets = self.cancel_room_matchmaking(room)

            membership.delete()
            remaining = list(room.members.order_by('joined_at', 'id'))
            if not remaining:
                room.delete()
                room_deleted = True
            else:
                if room.host_id == user.id:
                    next_host_member = next((member for member in remaining if member.user_id is not None), None)
                    if next_host_member is None:
                        room.delete()
                        room_deleted = True
                    else:
                        room.host = next_host_member.user
                        room.save(update_fields=['host'])
                if not room_deleted:
                    self.sync_room_status(room)

        refreshed_room = None if room_deleted else Room.objects.filter(code=code).first()
        if room_deleted:
            self.broadcast_room_deleted(code)
            if self.test_mode_room_codes is not None:
                self.test_mode_room_codes.discard(code)
            self.broadcast_cancelled_tickets(cancelled_room_tickets)
        elif refreshed_room is not None:
            self.broadcast_room_update(refreshed_room)
            self.broadcast_cancelled_tickets(cancelled_room_tickets, refreshed_room)
        else:
            self.broadcast_cancelled_tickets(cancelled_room_tickets)

        return {
            'room': refreshed_room,
            'room_deleted': room_deleted,
            'cancelled_tickets': cancelled_room_tickets,
        }

    def kick_member(self, user, code, data):
        room = self.get_room(code)
        if room.host_id != user.id:
            raise ServiceError('only the host can kick players.', status=403, code='host_required')

        user_id = data.get('user_id')
        if user_id == user.id:
            raise ServiceError('host cannot kick themselves.', code='cannot_kick_self')

        cancelled_room_tickets = []
        with transaction.atomic():
            room = Room.objects.select_for_update().get(pk=room.pk)
            cancelled_room_tickets = self.cancel_room_matchmaking(room)
            deleted, _ = room.members.filter(user_id=user_id).delete()
            if not deleted:
                raise ServiceError('player is not in this room.', status=404, code='member_not_found')
            self.sync_room_status(room)

        refreshed_room = Room.objects.filter(code=code).first()
        if refreshed_room is not None:
            self.broadcast_room_update(refreshed_room)
            self.broadcast_cancelled_tickets(cancelled_room_tickets, refreshed_room)
        else:
            self.broadcast_cancelled_tickets(cancelled_room_tickets)

        return {
            'room': refreshed_room,
            'cancelled_tickets': cancelled_room_tickets,
        }

    def transfer_host(self, user, code, data):
        room = self.get_room(code)
        if room.host_id != user.id:
            raise ServiceError('only the host can transfer host.', status=403, code='host_required')

        user_id = data.get('user_id')
        membership = room.members.select_related('user').filter(user_id=user_id, user__isnull=False).first()
        if membership is None:
            raise ServiceError('player is not in this room.', status=404, code='member_not_found')

        room.host = membership.user
        room.save(update_fields=['host'])
        self.broadcast_room_update(room)
        return room

    def fill_room_with_ai(self, room, target_count=4):
        current_count = room.members.count()
        ai_count = max(0, target_count - current_count)
        for index in range(ai_count):
            RoomMember.objects.create(
                room=room,
                user=None,
                is_ai=True,
                ai_name=f'AI Player {index + 1}',
                is_ready=True,
            )
        return ai_count

    def start_room(self, user, code, data, matchmaking_service=None):
        room = self.get_room(code)
        if room.host_id != user.id:
            raise ServiceError('only the host can start the game.', status=403, code='host_required')

        test_mode = bool(data.get('test_mode'))
        members = list(room.members.all())
        non_host_members = [member for member in members if member.user_id != room.host_id]
        if not all(member.is_ready for member in non_host_members) and not test_mode:
            raise ServiceError('all players must be ready before starting.', code='players_not_ready')

        if len(members) < 4 and not test_mode:
            if matchmaking_service is None:
                raise ServiceError('matchmaking service is not available.', status=500, code='matchmaking_service_unavailable')
            matchmaking_room, ticket = matchmaking_service.start_room_matchmaking(room, user)
            return {
                'room': matchmaking_room,
                'ticket': ticket,
                'test_mode': False,
                'broadcast_payload': None,
                'message': 'Room matchmaking started.',
            }

        if len(members) != 4 and not test_mode:
            raise ServiceError('room needs 4 players before starting.', code='room_not_full')

        if test_mode:
            with transaction.atomic():
                room = Room.objects.select_for_update().get(pk=room.pk)
                self.fill_room_with_ai(room, target_count=4)
                room.status = Room.Status.PLAYING
                room.save(update_fields=['status'])
            if self.test_mode_room_codes is not None:
                self.test_mode_room_codes.add(room.code)
        else:
            room.status = Room.Status.PLAYING
            room.save(update_fields=['status'])
            if self.test_mode_room_codes is not None:
                self.test_mode_room_codes.discard(room.code)

        payload = {'test_mode': test_mode} if test_mode else None
        self.broadcast_room_update(room, payload)
        return {
            'room': room,
            'ticket': None,
            'test_mode': test_mode,
            'broadcast_payload': payload,
            'message': 'Game started.',
        }

    def end_room(self, user, code):
        room = self.get_room(code)
        if not room.members.filter(user=user).exists():
            raise ServiceError('you are not in this room.', status=403, code='not_room_member')

        room.delete()
        self.broadcast_room_deleted(code)
        if self.test_mode_room_codes is not None:
            self.test_mode_room_codes.discard(code)
        return {
            'room': None,
            'message': 'Game ended.',
        }

    def cleanup_user_presence(self, user):
        """Remove a user from matchmaking and all active room memberships.

        This is shared by logout and browser-close cleanup so ghost room members
        and stale matchmaking tickets are cleaned through one room-service flow.
        """
        if user is None or not getattr(user, 'is_authenticated', False):
            return []

        affected_room_codes = []
        cancelled_room_tickets = []

        MatchmakingTicket.objects.filter(
            user=user,
            status=MatchmakingTicket.Status.WAITING,
            source_room__isnull=True,
        ).update(status=MatchmakingTicket.Status.CANCELLED)

        memberships = list(
            RoomMember.objects
            .select_related('room')
            .filter(
                user=user,
                room__status__in=[Room.Status.WAITING, Room.Status.FULL, Room.Status.PLAYING],
            )
            .order_by('room_id')
        )

        for membership in memberships:
            room = membership.room
            room_code = room.code
            affected_room_codes.append(room_code)

            with transaction.atomic():
                room = Room.objects.select_for_update().filter(pk=room.pk).first()
                if room is None:
                    continue

                room_cancelled_tickets = self.cancel_room_matchmaking(room)
                if room_cancelled_tickets:
                    cancelled_room_tickets.extend((room_code, ticket) for ticket in room_cancelled_tickets)

                RoomMember.objects.filter(pk=membership.pk).delete()
                human_members = list(
                    RoomMember.objects
                    .select_related('user')
                    .filter(room=room, user__isnull=False, is_ai=False)
                    .order_by('joined_at', 'id')
                )

                if not human_members:
                    room.delete()
                    self.broadcast_room_deleted(room_code)
                    if self.test_mode_room_codes is not None:
                        self.test_mode_room_codes.discard(room_code)
                    continue

                update_fields = []
                if room.host_id == user.id:
                    room.host = human_members[0].user
                    update_fields.append('host')

                if room.status != Room.Status.PLAYING:
                    next_status = Room.Status.FULL if len(human_members) >= 4 else Room.Status.WAITING
                    if room.status != next_status:
                        room.status = next_status
                        update_fields.append('status')

                if update_fields:
                    room.save(update_fields=update_fields)

            refreshed_room = Room.objects.filter(code=room_code).first()
            if refreshed_room is not None:
                self.broadcast_room_update(refreshed_room)

        for room_code, ticket in cancelled_room_tickets:
            refreshed_room = Room.objects.filter(code=room_code).first()
            self.broadcast_matchmaking_update(ticket.user_id, {
                'type': 'cancelled',
                'ticket': None,
                'room': self.room_payload(refreshed_room, ticket.user) if refreshed_room is not None else None,
            })

        if user.id:
            self.broadcast_matchmaking_update(user.id, {'type': 'cancelled', 'ticket': None})

        return affected_room_codes

