import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ..models import MatchmakingTicket, Room, RoomMember
from .exceptions import ServiceError
from .room_service import RoomService


MATCHMAKING_TIMEOUT_SECONDS = 30
MATCHMAKING_SCORE_WINDOWS = (
    (0, 100),
    (10, 200),
    (20, 300),
)


class MatchmakingService:
    """Encapsulates matchmaking business logic.

    The view layer should only parse HTTP requests and format responses. This
    service owns solo matchmaking, room matchmaking, ticket cancellation,
    status lookup, match completion, score-window calculation, AI fallback, and
    matchmaking-related broadcast side effects.
    """

    def __init__(self, room_payload_builder=None, room_broadcast=None, matchmaking_broadcast=None):
        self.room_service = RoomService()
        self.room_payload_builder = room_payload_builder
        self.room_broadcast = room_broadcast
        self.matchmaking_broadcast = matchmaking_broadcast

    def ticket_payload(self, ticket):
        if ticket is None:
            return None

        waited_for = int((timezone.now() - ticket.created_at).total_seconds())

        return {
            'status': ticket.get_status_display(),
            'score': ticket.score,
            'waited_for': waited_for,
            'started_at': ticket.created_at.isoformat(),
            'timeout_seconds': MATCHMAKING_TIMEOUT_SECONDS,
            'score_window': self.matchmaking_score_window(waited_for),
            'source_room_code': ticket.source_room.code if ticket.source_room_id else None,
        }

    def matchmaking_score_window(self, waited_seconds):
        window = MATCHMAKING_SCORE_WINDOWS[0][1]
        for threshold, score_window in MATCHMAKING_SCORE_WINDOWS:
            if waited_seconds >= threshold:
                window = score_window
        return window

    def generate_room_code(self):
        for _ in range(20):
            code = f'{random.SystemRandom().randint(0, 999999):06d}'
            if not Room.objects.filter(code=code).exists():
                return code
        raise RuntimeError('Could not generate room code.')

    def room_payload(self, room, user=None):
        if self.room_payload_builder is None:
            return None
        return self.room_payload_builder(room, user)

    def broadcast_room_update(self, room, payload=None):
        if self.room_broadcast is not None:
            self.room_broadcast(room, payload)

    def broadcast_matchmaking_update(self, user_id, payload):
        if self.matchmaking_broadcast is not None:
            self.matchmaking_broadcast(user_id, payload)

    def broadcast_cancelled_tickets(self, tickets, room=None):
        for ticket in tickets:
            self.broadcast_matchmaking_update(ticket.user_id, {
                'type': 'cancelled',
                'ticket': None,
                'room': self.room_payload(room, ticket.user) if room is not None else None,
            })

    def join_solo(self, user):
        existing_membership = self.room_service.active_membership(user)
        if existing_membership is not None and existing_membership.room.status == Room.Status.PLAYING:
            return {
                'room': existing_membership.room,
                'ticket': None,
            }

        profile = getattr(user, 'player_profile', None)
        score = profile.total_score if profile else 0

        with transaction.atomic():
            RoomMember.objects.filter(
                user=user,
                room__status__in=[Room.Status.WAITING, Room.Status.FULL],
            ).delete()
            MatchmakingTicket.objects.filter(user=user).delete()
            ticket = MatchmakingTicket.objects.create(
                user=user,
                score=score,
                status=MatchmakingTicket.Status.WAITING,
            )

        self.broadcast_matchmaking_update(user.id, {
            'type': 'waiting',
            'ticket': self.ticket_payload(ticket),
        })

        # Matching is handled asynchronously by matchmaking_worker.
        # Do not complete matching in the API request, otherwise SQLite can race
        # with the worker and raise "database is locked" errors.
        return {
            'room': None,
            'ticket': ticket,
        }

    def cancel(self, user):
        cancelled_tickets = []
        cancelled_room = None

        with transaction.atomic():
            ticket = (
                MatchmakingTicket.objects
                .select_for_update()
                .select_related('source_room', 'user')
                .filter(
                    user=user,
                    status=MatchmakingTicket.Status.WAITING,
                )
                .first()
            )

            if ticket and ticket.source_room_id:
                room = Room.objects.select_for_update().filter(pk=ticket.source_room_id).first()
                if room is None:
                    ticket.status = MatchmakingTicket.Status.CANCELLED
                    ticket.save(update_fields=['status'])
                    cancelled_tickets = [ticket]
                elif room.host_id != user.id:
                    raise ServiceError('only the host can cancel room matchmaking.', status=403, code='host_required')
                else:
                    cancelled_room = room
                    cancelled_tickets = self.room_service.cancel_room_matchmaking(room)
            else:
                solo_tickets = list(
                    MatchmakingTicket.objects
                    .select_for_update()
                    .select_related('user')
                    .filter(
                        user=user,
                        status=MatchmakingTicket.Status.WAITING,
                        source_room__isnull=True,
                    )
                )
                ticket_ids = [solo_ticket.id for solo_ticket in solo_tickets]
                if ticket_ids:
                    MatchmakingTicket.objects.filter(id__in=ticket_ids).update(
                        status=MatchmakingTicket.Status.CANCELLED,
                    )
                cancelled_tickets = solo_tickets

        if cancelled_room is not None:
            cancelled_room = Room.objects.filter(pk=cancelled_room.pk).first()
            if cancelled_room is not None:
                self.broadcast_room_update(cancelled_room)

        self.broadcast_cancelled_tickets(cancelled_tickets, cancelled_room)

        if not cancelled_tickets:
            self.broadcast_matchmaking_update(user.id, {
                'type': 'cancelled',
                'ticket': None,
            })

        return {
            'ticket': None,
            'room': cancelled_room,
            'cancelled_tickets': cancelled_tickets,
        }

    def status(self, user):
        membership = self.room_service.active_membership(user)
        if membership is not None and membership.room.status == Room.Status.PLAYING:
            return {
                'room': membership.room,
                'ticket': None,
            }

        ticket = (
            MatchmakingTicket.objects
            .select_related('source_room')
            .filter(
                user=user,
                status=MatchmakingTicket.Status.WAITING,
            )
            .first()
        )

        if ticket and ticket.source_room_id:
            return {
                'room': ticket.source_room,
                'ticket': ticket,
            }

        return {
            'room': None,
            'ticket': ticket,
        }

    def start_room_matchmaking(self, room, anchor_user):
        members = list(
            room.members
            .select_related('user', 'user__player_profile')
            .filter(user__isnull=False)
            .order_by('joined_at', 'id')
        )
        users = [member.user for member in members]
        if not users:
            return None, None

        with transaction.atomic():
            room = Room.objects.select_for_update().get(pk=room.pk)
            MatchmakingTicket.objects.filter(user__in=users).delete()
            tickets = []
            for user in users:
                profile = getattr(user, 'player_profile', None)
                tickets.append(MatchmakingTicket.objects.create(
                    user=user,
                    score=profile.total_score if profile else 0,
                    status=MatchmakingTicket.Status.WAITING,
                    source_room=room,
                ))
            RoomMember.objects.filter(
                room=room,
                user__in=users,
            ).update(is_ready=True)

        self.broadcast_room_update(room)

        for ticket in tickets:
            self.broadcast_matchmaking_update(ticket.user_id, {
                'type': 'waiting',
                'ticket': self.ticket_payload(ticket),
                'room': self.room_payload(room, ticket.user),
            })

        # Matching is performed by the standalone management command:
        # python manage.py matchmaking_worker
        # Keep this method read/write only for ticket creation to avoid racing SQLite writes.
        user_ticket = next((ticket for ticket in tickets if ticket.user_id == anchor_user.id), None)
        return room, user_ticket or (tickets[0] if tickets else None)

    def create_match_room(self, tickets, ai_count=0):
        users = [ticket.user for ticket in tickets]
        if not users:
            return None

        room = Room.objects.create(
            code=self.generate_room_code(),
            host=users[0],
            status=Room.Status.PLAYING,
        )
        for user in users:
            RoomMember.objects.create(room=room, user=user, is_ready=True)

        for index in range(ai_count):
            RoomMember.objects.create(
                room=room,
                user=None,
                is_ai=True,
                ai_name=f'AI Player {index + 1}',
                is_ready=True,
            )

        ticket_ids = [ticket.id for ticket in tickets]
        MatchmakingTicket.objects.filter(id__in=ticket_ids).update(
            status=MatchmakingTicket.Status.MATCHED,
            matched_room=room,
        )
        RoomMember.objects.filter(
            user__in=users,
            room__status__in=[Room.Status.WAITING, Room.Status.FULL],
        ).exclude(room=room).delete()

        for user in users:
            self.broadcast_matchmaking_update(user.id, {
                'type': 'matched',
                'room': self.room_payload(room, user),
            })
        self.broadcast_room_update(room)
        return room

    def complete_existing_room_matchmaking(self, room, room_tickets, extra_tickets, ai_count=0):
        room_users = [ticket.user for ticket in room_tickets]
        extra_users = [ticket.user for ticket in extra_tickets]
        all_users = room_users + extra_users

        for user in extra_users:
            RoomMember.objects.get_or_create(
                room=room,
                user=user,
                defaults={
                    'is_ai': False,
                    'is_ready': True,
                },
            )

        RoomMember.objects.filter(
            room=room,
            user__in=all_users,
        ).update(is_ready=True)

        for index in range(ai_count):
            RoomMember.objects.create(
                room=room,
                user=None,
                is_ai=True,
                ai_name=f'AI Player {index + 1}',
                is_ready=True,
            )

        room.status = Room.Status.PLAYING
        room.save(update_fields=['status'])

        ticket_ids = [ticket.id for ticket in room_tickets + extra_tickets]
        MatchmakingTicket.objects.filter(id__in=ticket_ids).update(
            status=MatchmakingTicket.Status.MATCHED,
            matched_room=room,
        )

        RoomMember.objects.filter(
            user__in=extra_users,
            room__status__in=[Room.Status.WAITING, Room.Status.FULL],
        ).exclude(room=room).delete()

        for user in all_users:
            self.broadcast_matchmaking_update(user.id, {
                'type': 'matched',
                'room': self.room_payload(room, user),
            })

        self.broadcast_room_update(room)
        return room

    def try_complete_room_matchmaking(self, room):
        room_tickets = list(
            MatchmakingTicket.objects
            .select_for_update()
            .select_related('user', 'user__player_profile', 'source_room')
            .filter(
                status=MatchmakingTicket.Status.WAITING,
                source_room=room,
            )
            .order_by('created_at', 'id')
        )

        if not room_tickets:
            return None

        current_member_count = room.members.count()
        needed = max(0, 4 - current_member_count)

        if needed <= 0:
            return self.complete_existing_room_matchmaking(
                room,
                room_tickets,
                extra_tickets=[],
                ai_count=0,
            )

        now = timezone.now()
        oldest_ticket = room_tickets[0]
        waited_for = int((now - oldest_ticket.created_at).total_seconds())
        score_window = self.matchmaking_score_window(waited_for)

        average_score = sum(ticket.score for ticket in room_tickets) / len(room_tickets)

        solo_tickets = list(
            MatchmakingTicket.objects
            .select_for_update()
            .select_related('user', 'user__player_profile')
            .filter(
                status=MatchmakingTicket.Status.WAITING,
                source_room__isnull=True,
            )
            .exclude(user_id__in=[ticket.user_id for ticket in room_tickets])
            .order_by('created_at', 'id')
        )

        close_solo_tickets = sorted(
            [
                ticket for ticket in solo_tickets
                if abs(ticket.score - average_score) <= score_window
            ],
            key=lambda ticket: (abs(ticket.score - average_score), ticket.created_at, ticket.id),
        )

        if len(close_solo_tickets) >= needed:
            return self.complete_existing_room_matchmaking(
                room,
                room_tickets,
                extra_tickets=close_solo_tickets[:needed],
                ai_count=0,
            )

        if now - oldest_ticket.created_at >= timedelta(seconds=MATCHMAKING_TIMEOUT_SECONDS):
            fallback_tickets = sorted(
                solo_tickets,
                key=lambda ticket: (abs(ticket.score - average_score), ticket.created_at, ticket.id),
            )[:needed]

            return self.complete_existing_room_matchmaking(
                room,
                room_tickets,
                extra_tickets=fallback_tickets,
                ai_count=needed - len(fallback_tickets),
            )

        return None

    def try_complete_matchmaking(self, anchor_user=None):
        with transaction.atomic():
            anchor_ticket = None

            if anchor_user is not None:
                anchor_ticket = (
                    MatchmakingTicket.objects
                    .select_for_update()
                    .select_related('user', 'user__player_profile', 'source_room')
                    .filter(
                        user=anchor_user,
                        status=MatchmakingTicket.Status.WAITING,
                    )
                    .first()
                )

            if anchor_ticket is not None and anchor_ticket.source_room_id:
                room = (
                    Room.objects
                    .select_for_update()
                    .filter(pk=anchor_ticket.source_room_id)
                    .first()
                )
                if room is None:
                    return None

                return self.try_complete_room_matchmaking(room)

            room_ticket = (
                MatchmakingTicket.objects
                .select_for_update()
                .select_related('source_room')
                .filter(
                    status=MatchmakingTicket.Status.WAITING,
                    source_room__isnull=False,
                )
                .order_by('created_at', 'id')
                .first()
            )

            if room_ticket is not None:
                room = Room.objects.select_for_update().filter(pk=room_ticket.source_room_id).first()
                if room is not None:
                    room_result = self.try_complete_room_matchmaking(room)
                    if room_result is not None:
                        return room_result

            tickets = list(
                MatchmakingTicket.objects
                .select_for_update()
                .select_related('user', 'user__player_profile')
                .filter(
                    status=MatchmakingTicket.Status.WAITING,
                    source_room__isnull=True,
                )
                .order_by('created_at', 'id')
            )

            if not tickets:
                return None

            anchor_ticket = None
            if anchor_user is not None:
                anchor_ticket = next((ticket for ticket in tickets if ticket.user_id == anchor_user.id), None)

            anchor_ticket = anchor_ticket or tickets[0]
            now = timezone.now()
            anchor_waited_for = int((now - anchor_ticket.created_at).total_seconds())
            score_window = self.matchmaking_score_window(anchor_waited_for)

            close_tickets = sorted(
                [
                    ticket for ticket in tickets
                    if abs(ticket.score - anchor_ticket.score) <= score_window
                ],
                key=lambda ticket: (abs(ticket.score - anchor_ticket.score), ticket.created_at, ticket.id),
            )

            if len(close_tickets) >= 4:
                return self.create_match_room(close_tickets[:4])

            oldest_ticket = tickets[0]
            waited_for = now - oldest_ticket.created_at

            if waited_for >= timedelta(seconds=MATCHMAKING_TIMEOUT_SECONDS):
                fallback_tickets = sorted(
                    tickets,
                    key=lambda ticket: (abs(ticket.score - oldest_ticket.score), ticket.created_at, ticket.id),
                )[:4]

                return self.create_match_room(
                    fallback_tickets,
                    ai_count=4 - len(fallback_tickets),
                )

        return None
