import json
import random
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render  # [測試功能] 用於渲染 game_test.html
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import MatchParticipant, MatchmakingTicket, Room, RoomMember
from .services.auth_service import AuthService
from .services.exceptions import ServiceError

MATCHMAKING_TIMEOUT_SECONDS = 30
MATCHMAKING_SCORE_WINDOWS = (
    (0, 100),
    (10, 200),
    (20, 300),
)
TEST_MODE_ROOM_CODES = set()
ROOM_VISIBILITY_TOGGLE_COOLDOWN_SECONDS = 10


def _json_body(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return None


def _error(message, status=400, code='bad_request'):
    return JsonResponse({'error': {'code': code, 'message': message}}, status=status)


def _user_payload(user):
    profile = getattr(user, 'player_profile', None)
    total_games = MatchParticipant.objects.filter(user=user).count()
    wins = MatchParticipant.objects.filter(user=user, player_rank=1).count()
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'email_verified': user.is_active,
        'nickname': profile.nickname if profile else '',
        'total_score': profile.total_score if profile else 0,
        'win_rate': profile.win_rate if profile else 0.0,
        'total_games': total_games,
        'wins': wins,
    }


def _room_user_payload(user):
    profile = getattr(user, 'player_profile', None)
    return {
        'id': user.id,
        'username': user.username,
        'nickname': profile.nickname if profile else user.username,
    }


def _require_login(request):
    if not request.user.is_authenticated:
        return _error('not authenticated.', status=401, code='not_authenticated')
    return None


def _room_code():
    for _ in range(20):
        code = f'{random.SystemRandom().randint(0, 999999):06d}'
        if not Room.objects.filter(code=code).exists():
            return code
    raise RuntimeError('Could not generate room code.')


def _active_membership(user):
    return (
        RoomMember.objects
        .select_related('room', 'room__host', 'user', 'user__player_profile')
        .prefetch_related('room__members__user__player_profile')
        .filter(user=user, room__status__in=[Room.Status.WAITING, Room.Status.FULL, Room.Status.PLAYING])
        .order_by('-joined_at')
        .first()
    )


def _sync_room_status(room):
    member_count = room.members.count()
    if room.status == Room.Status.PLAYING:
        return
    next_status = Room.Status.FULL if member_count >= 4 else Room.Status.WAITING
    if room.status != next_status:
        room.status = next_status
        room.save(update_fields=['status'])


def _broadcast_cancelled_matchmaking_tickets(tickets, room=None):
    for ticket in tickets:
        _broadcast_matchmaking_update(ticket.user_id, {
            'type': 'cancelled',
            'ticket': None,
            'room': _room_payload(room, ticket.user) if room is not None else None,
        })


def _cancel_room_matchmaking(room):
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
    _sync_room_status(room)
    return tickets


def _game_reconnect_status(room, user):
    status = {
        'can_return': room.status == Room.Status.PLAYING,
        'reconnect_blocked': False,
        'auto_enter': room.status == Room.Status.PLAYING,
        'reason': '',
    }
    if room.status != Room.Status.PLAYING or user is None:
        return status

    try:
        from .game_consumer import GameConsumer
    except Exception:
        return status

    engine = GameConsumer.game_engines.get(room.code)
    if not engine:
        return status

    player = None
    for candidate in engine.players:
        original_id = str(getattr(candidate, 'original_player_id', candidate.player_id))
        if original_id == str(user.id):
            player = candidate
            break

    if not player:
        return status

    if getattr(player, 'is_ai_replacement', False) or getattr(player, 'settlement_penalty', False):
        status.update({
            'can_return': False,
            'reconnect_blocked': True,
            'auto_enter': False,
            'reason': '玩家已超過重連時間，由 AI 代打至本局結束。',
        })
    return status


def _blocked_by_active_game(user):
    membership = _active_membership(user)
    if membership is None or membership.room.status != Room.Status.PLAYING:
        return None

    game_status = _game_reconnect_status(membership.room, user)
    if game_status.get('reconnect_blocked'):
        return _error(
            game_status.get('reason') or 'current game must finish before starting a new one.',
            status=403,
            code='active_game_penalty',
        )
    return None


def _room_payload(room, user=None):
    members = list(
        room.members
        .select_related('user', 'user__player_profile')
        .order_by('joined_at', 'id')
    )
    member_payloads = []
    for member in members:
        payload = (
            _room_user_payload(member.user)
            if member.user_id
            else {
                'id': None,
                'username': member.ai_name,
                'nickname': member.ai_name,
            }
        )
        member_payloads.append({
            'user': payload,
            'is_ai': member.is_ai,
            'is_ready': member.is_ready,
            'is_host': member.user_id == room.host_id,
            'joined_at': member.joined_at.isoformat(),
        })

    member_count = len(member_payloads)
    non_host_members = [
        member for member in member_payloads
        if not member['is_host']
    ]
    can_start = (
        user is not None
        and user.id == room.host_id
        and member_count >= 1
        and all(member['is_ready'] for member in non_host_members)
        and room.status in [Room.Status.WAITING, Room.Status.FULL]
    )
    is_matchmaking = room.source_matchmaking_tickets.filter(
        status=MatchmakingTicket.Status.WAITING,
    ).exists()
    return {
        'id': room.room_id,
        'code': room.code,
        'host_id': room.host_id,
        'status': room.get_status_display(),
        'member_count': member_count,
        'max_members': 4,
        'can_start': can_start and not is_matchmaking,
        'is_public': room.is_public,
        'last_visibility_changed_at': (
            room.last_visibility_changed_at.isoformat()
            if room.last_visibility_changed_at
            else None
        ),
        'visibility_toggle_cooldown_seconds': ROOM_VISIBILITY_TOGGLE_COOLDOWN_SECONDS,
        'members': member_payloads,
        'game_status': _game_reconnect_status(room, user),
        'test_mode': room.code in TEST_MODE_ROOM_CODES,
        'is_matchmaking': is_matchmaking,
    }



def _cleanup_user_presence(user):
    """Remove a user from matchmaking and all active room memberships before logout.

    This keeps lobby rooms from retaining ghost members after manual logout or
    the frontend idle-timeout logout. Playing rooms are also cleaned at the DB
    level; the existing game socket leave flow still handles AI replacement when
    the socket is open.
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

            room_cancelled_tickets = _cancel_room_matchmaking(room)
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
                _broadcast_room_deleted(room_code)
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
            _broadcast_room_update(refreshed_room)

    for room_code, ticket in cancelled_room_tickets:
        refreshed_room = Room.objects.filter(code=room_code).first()
        _broadcast_matchmaking_update(ticket.user_id, {
            'type': 'cancelled',
            'ticket': None,
            'room': _room_payload(refreshed_room, ticket.user) if refreshed_room is not None else None,
        })

    if user.id:
        _broadcast_matchmaking_update(user.id, {'type': 'cancelled', 'ticket': None})

    return affected_room_codes

def _get_room_or_error(code):
    room = (
        Room.objects
        .select_related('host')
        .prefetch_related('members__user__player_profile')
        .filter(code=code)
        .first()
    )
    if room is None:
        return None, _error('room not found.', status=404, code='room_not_found')
    return room, None


def _broadcast_room_update(room, payload=None):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            f'room_{room.code}',
            {
                'type': 'room.updated',
                'payload': payload or {},
            },
        )
    except Exception as exc:
        print(f'[channel-layer] room update broadcast failed room={room.code}: {exc}', flush=True)


def _broadcast_room_deleted(code):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            f'room_{code}',
            {'type': 'room.deleted'},
        )
    except Exception as exc:
        print(f'[channel-layer] room deleted broadcast failed room={code}: {exc}', flush=True)


def _broadcast_matchmaking_update(user_id, payload):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            f'user_{user_id}',
            {
                'type': 'matchmaking.updated',
                'payload': payload,
            },
        )
    except Exception as exc:
        print(f'[channel-layer] matchmaking broadcast failed user={user_id}: {exc}', flush=True)


def _ticket_payload(ticket):
    if ticket is None:
        return None

    waited_for = int((timezone.now() - ticket.created_at).total_seconds())

    return {
        'status': ticket.get_status_display(),
        'score': ticket.score,
        'waited_for': waited_for,
        'started_at': ticket.created_at.isoformat(),
        'timeout_seconds': MATCHMAKING_TIMEOUT_SECONDS,
        'score_window': _matchmaking_score_window(waited_for),
        'source_room_code': ticket.source_room.code if ticket.source_room_id else None,
    }


def _create_match_room(tickets, ai_count=0):
    users = [ticket.user for ticket in tickets]
    if not users:
        return None

    room = Room.objects.create(
        code=_room_code(),
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
        _broadcast_matchmaking_update(user.id, {
            'type': 'matched',
            'room': _room_payload(room, user),
        })
    _broadcast_room_update(room)
    return room

def _complete_existing_room_matchmaking(room, room_tickets, extra_tickets, ai_count=0):
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
        _broadcast_matchmaking_update(user.id, {
            'type': 'matched',
            'room': _room_payload(room, user),
        })

    _broadcast_room_update(room)
    return room

def _fill_room_with_ai(room, target_count=4):
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


def _waiting_tickets():
    return list(
        MatchmakingTicket.objects
        .select_related('user', 'user__player_profile')
        .filter(status=MatchmakingTicket.Status.WAITING)
        .order_by('created_at', 'id')
    )


def _matchmaking_score_window(waited_seconds):
    window = MATCHMAKING_SCORE_WINDOWS[0][1]
    for threshold, score_window in MATCHMAKING_SCORE_WINDOWS:
        if waited_seconds >= threshold:
            window = score_window
    return window

def _try_complete_room_matchmaking(room):
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

    current_human_count = len(room_tickets)
    current_member_count = room.members.count()
    needed = max(0, 4 - current_member_count)

    if needed <= 0:
        return _complete_existing_room_matchmaking(
            room,
            room_tickets,
            extra_tickets=[],
            ai_count=0,
        )

    now = timezone.now()
    oldest_ticket = room_tickets[0]
    waited_for = int((now - oldest_ticket.created_at).total_seconds())
    score_window = _matchmaking_score_window(waited_for)

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
        return _complete_existing_room_matchmaking(
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

        return _complete_existing_room_matchmaking(
            room,
            room_tickets,
            extra_tickets=fallback_tickets,
            ai_count=needed - len(fallback_tickets),
        )

    return None

def _try_complete_matchmaking(anchor_user=None):
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

            return _try_complete_room_matchmaking(room)

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
                room_result = _try_complete_room_matchmaking(room)
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
        score_window = _matchmaking_score_window(anchor_waited_for)

        close_tickets = sorted(
            [
                ticket for ticket in tickets
                if abs(ticket.score - anchor_ticket.score) <= score_window
            ],
            key=lambda ticket: (abs(ticket.score - anchor_ticket.score), ticket.created_at, ticket.id),
        )

        if len(close_tickets) >= 4:
            return _create_match_room(close_tickets[:4])

        oldest_ticket = tickets[0]
        waited_for = now - oldest_ticket.created_at

        if waited_for >= timedelta(seconds=MATCHMAKING_TIMEOUT_SECONDS):
            fallback_tickets = sorted(
                tickets,
                key=lambda ticket: (abs(ticket.score - oldest_ticket.score), ticket.created_at, ticket.id),
            )[:4]

            return _create_match_room(
                fallback_tickets,
                ai_count=4 - len(fallback_tickets),
            )

    return None


def _start_room_matchmaking(room, anchor_user):
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


    _broadcast_room_update(room)

    for ticket in tickets:
        _broadcast_matchmaking_update(ticket.user_id, {
            'type': 'waiting',
            'ticket': _ticket_payload(ticket),
            'room': _room_payload(room, ticket.user),
        })

    # Matching is performed by the standalone management command:
    # python manage.py matchmaking_worker
    # Keep this view read/write only for ticket creation to avoid racing SQLite writes.

    user_ticket = next((ticket for ticket in tickets if ticket.user_id == anchor_user.id), None)
    return room, user_ticket or (tickets[0] if tickets else None)


def _auth_service():
    return AuthService()


def _service_error_response(error):
    return _error(error.message, status=error.status, code=error.code)


@csrf_exempt
@require_http_methods(['POST'])
def register(request):
    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    try:
        user = _auth_service().register(data)
    except ServiceError as error:
        return _service_error_response(error)

    return JsonResponse(
        {
            'user': _user_payload(user),
            'message': 'Registration successful. Please verify your email.',
        },
        status=201,
    )


@csrf_exempt
@require_http_methods(['POST'])
def verify_email(request):
    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    try:
        user = _auth_service().verify_email(data)
    except ServiceError as error:
        return _service_error_response(error)

    return JsonResponse({'user': _user_payload(user), 'message': 'Email verified.'})


@csrf_exempt
@require_http_methods(['POST'])
def resend_verification(request):
    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    try:
        _auth_service().resend_verification(data)
    except ServiceError as error:
        return _service_error_response(error)

    return JsonResponse({'message': 'Verification code sent.'})


@csrf_exempt
@require_http_methods(['POST'])
def request_password_reset(request):
    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    try:
        _auth_service().request_password_reset(data)
    except ServiceError as error:
        return _service_error_response(error)

    return JsonResponse({
        'message': 'If the email is registered, a password reset link has been sent.',
    })


@csrf_exempt
@require_http_methods(['POST'])
def reset_password(request):
    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    try:
        _auth_service().reset_password(data)
    except ServiceError as error:
        return _service_error_response(error)

    return JsonResponse({'message': 'Password reset successful. You can log in now.'})


@csrf_exempt
@require_http_methods(['POST'])
def login_view(request):
    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    try:
        user = _auth_service().login(request, data)
    except ServiceError as error:
        return _service_error_response(error)

    return JsonResponse({'user': _user_payload(user)})


@csrf_exempt
@require_http_methods(['POST'])
def logout_view(request):
    cleaned_rooms = _auth_service().logout(
        request,
        cleanup_callback=_cleanup_user_presence,
    )
    return JsonResponse({
        'message': 'Logged out.',
        'cleaned_rooms': cleaned_rooms,
    })


@csrf_exempt
@require_http_methods(['POST'])
def cleanup_presence(request):
    """Best-effort cleanup used by browser unload/pagehide.

    Unlike logout_view(), this keeps the user's session alive but removes the
    user from waiting rooms and cancels any active matchmaking state. This makes
    closing the lobby tab behave like leaving the room/cancelling matchmaking
    without forcing a logout.
    """
    cleaned_rooms = []
    if request.user.is_authenticated:
        cleaned_rooms = _cleanup_user_presence(request.user)
    return JsonResponse({
        'message': 'Presence cleaned.',
        'cleaned_rooms': cleaned_rooms,
    })


@require_http_methods(['GET'])
def me(request):
    if not request.user.is_authenticated:
        return _error('not authenticated.', status=401, code='not_authenticated')
    return JsonResponse({'user': _user_payload(request.user)})


@csrf_exempt
@require_http_methods(['POST'])
def create_room(request):
    login_error = _require_login(request)
    if login_error:
        return login_error
    blocked_error = _blocked_by_active_game(request.user)
    if blocked_error:
        return blocked_error

    with transaction.atomic():
        RoomMember.objects.filter(
            user=request.user,
            room__status__in=[Room.Status.WAITING, Room.Status.FULL],
        ).delete()
        room = Room.objects.create(
            code=_room_code(),
            host=request.user,
            status=Room.Status.WAITING,
        )
        RoomMember.objects.create(room=room, user=request.user, is_ready=False)

    _broadcast_room_update(room)
    return JsonResponse({'room': _room_payload(room, request.user)}, status=201)


@require_http_methods(['GET'])
def public_rooms(request):
    login_error = _require_login(request)
    if login_error:
        return login_error

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

    room_payloads = []
    for room in rooms:
        member_count = room.members.count()
        is_matchmaking = room.source_matchmaking_tickets.filter(
            status=MatchmakingTicket.Status.WAITING,
        ).exists()

        if member_count >= 4 or is_matchmaking:
            continue

        room_payloads.append(_room_payload(room, request.user))

    return JsonResponse({'rooms': room_payloads})


@csrf_exempt
@require_http_methods(['POST'])
def set_room_visibility(request, code):
    login_error = _require_login(request)
    if login_error:
        return login_error

    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    room, room_error = _get_room_or_error(code)
    if room_error:
        return room_error

    now = timezone.now()

    with transaction.atomic():
        room = Room.objects.select_for_update().get(pk=room.pk)

        if room.host_id != request.user.id:
            return _error('only host can change room visibility.', status=403, code='not_room_host')

        if room.status == Room.Status.PLAYING:
            return _error('cannot change visibility while playing.', status=400, code='room_playing')

        if room.last_visibility_changed_at:
            elapsed = (now - room.last_visibility_changed_at).total_seconds()
            if elapsed < ROOM_VISIBILITY_TOGGLE_COOLDOWN_SECONDS:
                wait_seconds = max(1, int(ROOM_VISIBILITY_TOGGLE_COOLDOWN_SECONDS - elapsed))
                return JsonResponse({
                    'error': {
                        'code': 'visibility_toggle_cooldown',
                        'message': f'please wait {wait_seconds} seconds before changing visibility again.',
                    },
                    'wait_seconds': wait_seconds,
                    'room': _room_payload(room, request.user),
                }, status=429)

        next_is_public = bool(data.get('is_public', not room.is_public))
        room.is_public = next_is_public
        room.last_visibility_changed_at = now
        room.save(update_fields=['is_public', 'last_visibility_changed_at'])

    _broadcast_room_update(room)
    return JsonResponse({
        'room': _room_payload(room, request.user),
        'visibility_toggle_cooldown_seconds': ROOM_VISIBILITY_TOGGLE_COOLDOWN_SECONDS,
    })


@csrf_exempt
@require_http_methods(['POST'])
def join_room(request):
    login_error = _require_login(request)
    if login_error:
        return login_error
    blocked_error = _blocked_by_active_game(request.user)
    if blocked_error:
        return blocked_error

    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    code = str(data.get('code', '')).strip()
    if len(code) != 6 or not code.isdigit():
        return _error('room code must be 6 digits.', code='invalid_room_code')

    room, room_error = _get_room_or_error(code)
    if room_error:
        return room_error
    if room.status == Room.Status.PLAYING:
        return _error('room is already playing.', code='room_playing')
    if room.source_matchmaking_tickets.filter(status=MatchmakingTicket.Status.WAITING).exists():
        return _error('room is matchmaking.', code='room_matchmaking')

    with transaction.atomic():
        room = Room.objects.select_for_update().get(pk=room.pk)
        member_count = room.members.count()
        if not room.members.filter(user=request.user).exists() and member_count >= 4:
            return _error('room is full.', code='room_full')

        RoomMember.objects.filter(
            user=request.user,
            room__status__in=[Room.Status.WAITING, Room.Status.FULL],
        ).exclude(room=room).delete()
        RoomMember.objects.get_or_create(room=room, user=request.user)
        _sync_room_status(room)

    _broadcast_room_update(room)
    return JsonResponse({'room': _room_payload(room, request.user)})


@require_http_methods(['GET'])
def current_room(request):
    login_error = _require_login(request)
    if login_error:
        return login_error

    membership = _active_membership(request.user)
    if membership is None:
        return JsonResponse({'room': None})

    room = membership.room
    _sync_room_status(room)
    return JsonResponse({'room': _room_payload(room, request.user)})


@csrf_exempt
@require_http_methods(['POST'])
def set_room_ready(request, code):
    login_error = _require_login(request)
    if login_error:
        return login_error

    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    room, room_error = _get_room_or_error(code)
    if room_error:
        return room_error

    membership = room.members.filter(user=request.user).first()
    if membership is None:
        return _error('you are not in this room.', status=403, code='not_room_member')

    if room.source_matchmaking_tickets.filter(status=MatchmakingTicket.Status.WAITING).exists():
        return _error('matchmaking is in progress; ready state cannot be changed.', status=409, code='room_matchmaking')

    membership.is_ready = bool(data.get('is_ready', not membership.is_ready))
    membership.save(update_fields=['is_ready'])
    _broadcast_room_update(room)
    return JsonResponse({'room': _room_payload(room, request.user)})


@csrf_exempt
@require_http_methods(['POST'])
def leave_room(request, code):
    login_error = _require_login(request)
    if login_error:
        return login_error

    room, room_error = _get_room_or_error(code)
    if room_error:
        return room_error

    membership = room.members.filter(user=request.user).first()
    if membership is None:
        return JsonResponse({'room': None})

    cancelled_room_tickets = []
    room_deleted = False

    with transaction.atomic():
        room = Room.objects.select_for_update().get(pk=room.pk)
        membership = RoomMember.objects.select_for_update().filter(room=room, user=request.user).first()
        if membership is None:
            return JsonResponse({'room': None})

        cancelled_room_tickets = _cancel_room_matchmaking(room)

        membership.delete()
        remaining = list(room.members.order_by('joined_at', 'id'))
        if not remaining:
            room.delete()
            room_deleted = True
        else:
            if room.host_id == request.user.id:
                next_host_member = next((member for member in remaining if member.user_id is not None), None)
                if next_host_member is None:
                    room.delete()
                    room_deleted = True
                else:
                    room.host = next_host_member.user
                    room.save(update_fields=['host'])
            if not room_deleted:
                _sync_room_status(room)

    if room_deleted:
        _broadcast_room_deleted(code)
        _broadcast_cancelled_matchmaking_tickets(cancelled_room_tickets)
        return JsonResponse({'room': None})

    refreshed_room = Room.objects.filter(code=code).first()
    if refreshed_room is not None:
        _broadcast_room_update(refreshed_room)
        _broadcast_cancelled_matchmaking_tickets(cancelled_room_tickets, refreshed_room)
    else:
        _broadcast_cancelled_matchmaking_tickets(cancelled_room_tickets)

    return JsonResponse({'room': None})


@csrf_exempt
@require_http_methods(['POST'])
def kick_room_member(request, code):
    login_error = _require_login(request)
    if login_error:
        return login_error

    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    room, room_error = _get_room_or_error(code)
    if room_error:
        return room_error
    if room.host_id != request.user.id:
        return _error('only the host can kick players.', status=403, code='host_required')

    user_id = data.get('user_id')
    if user_id == request.user.id:
        return _error('host cannot kick themselves.', code='cannot_kick_self')

    cancelled_room_tickets = []
    with transaction.atomic():
        room = Room.objects.select_for_update().get(pk=room.pk)
        cancelled_room_tickets = _cancel_room_matchmaking(room)
        deleted, _ = room.members.filter(user_id=user_id).delete()
        if not deleted:
            return _error('player is not in this room.', status=404, code='member_not_found')
        _sync_room_status(room)

    refreshed_room = Room.objects.filter(code=code).first()
    if refreshed_room is not None:
        _broadcast_room_update(refreshed_room)
        _broadcast_cancelled_matchmaking_tickets(cancelled_room_tickets, refreshed_room)
    else:
        _broadcast_cancelled_matchmaking_tickets(cancelled_room_tickets)
    return JsonResponse({'room': _room_payload(refreshed_room, request.user) if refreshed_room is not None else None})


@csrf_exempt
@require_http_methods(['POST'])
def transfer_room_host(request, code):
    login_error = _require_login(request)
    if login_error:
        return login_error

    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    room, room_error = _get_room_or_error(code)
    if room_error:
        return room_error
    if room.host_id != request.user.id:
        return _error('only the host can transfer host.', status=403, code='host_required')

    user_id = data.get('user_id')
    membership = room.members.select_related('user').filter(user_id=user_id, user__isnull=False).first()
    if membership is None:
        return _error('player is not in this room.', status=404, code='member_not_found')

    room.host = membership.user
    room.save(update_fields=['host'])
    _broadcast_room_update(room)
    return JsonResponse({'room': _room_payload(room, request.user)})


@csrf_exempt
@require_http_methods(['POST'])
def start_room(request, code):
    login_error = _require_login(request)
    if login_error:
        return login_error

    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    room, room_error = _get_room_or_error(code)
    if room_error:
        return room_error
    if room.host_id != request.user.id:
        return _error('only the host can start the game.', status=403, code='host_required')

    test_mode = bool(data.get('test_mode'))
    members = list(room.members.all())
    non_host_members = [member for member in members if member.user_id != room.host_id]
    if not all(member.is_ready for member in non_host_members) and not test_mode:
        return _error('all players must be ready before starting.', code='players_not_ready')

    if len(members) < 4 and not test_mode:
        matchmaking_room, ticket = _start_room_matchmaking(room, request.user)

        return JsonResponse({
            'room': _room_payload(matchmaking_room, request.user),
            'ticket': _ticket_payload(ticket),
            'message': 'Room matchmaking started.',
        })

    if len(members) != 4 and not test_mode:
        return _error('room needs 4 players before starting.', code='room_not_full')

    if test_mode:
        with transaction.atomic():
            room = Room.objects.select_for_update().get(pk=room.pk)
            _fill_room_with_ai(room, target_count=4)
            room.status = Room.Status.PLAYING
            room.save(update_fields=['status'])
        TEST_MODE_ROOM_CODES.add(room.code)
    else:
        room.status = Room.Status.PLAYING
        room.save(update_fields=['status'])
        TEST_MODE_ROOM_CODES.discard(room.code)
    payload = {'test_mode': test_mode} if test_mode else None
    _broadcast_room_update(room, payload)
    return JsonResponse({
        'room': _room_payload(room, request.user),
        'test_mode': test_mode,
        'message': 'Game started.',
    })


@csrf_exempt
@require_http_methods(['POST'])
def end_room(request, code):
    login_error = _require_login(request)
    if login_error:
        return login_error

    room, room_error = _get_room_or_error(code)
    if room_error:
        return room_error
    if not room.members.filter(user=request.user).exists():
        return _error('you are not in this room.', status=403, code='not_room_member')

    room.delete()
    _broadcast_room_deleted(code)
    return JsonResponse({'room': None, 'message': 'Game ended.'})


@csrf_exempt
@require_http_methods(['POST'])
def join_matchmaking(request):
    login_error = _require_login(request)
    if login_error:
        return login_error
    blocked_error = _blocked_by_active_game(request.user)
    if blocked_error:
        return blocked_error

    existing_room = _active_membership(request.user)
    if existing_room is not None and existing_room.room.status == Room.Status.PLAYING:
        return JsonResponse({'room': _room_payload(existing_room.room, request.user), 'ticket': None})

    profile = getattr(request.user, 'player_profile', None)
    score = profile.total_score if profile else 0
    with transaction.atomic():
        RoomMember.objects.filter(
            user=request.user,
            room__status__in=[Room.Status.WAITING, Room.Status.FULL],
        ).delete()
        MatchmakingTicket.objects.filter(user=request.user).delete()
        ticket = MatchmakingTicket.objects.create(
            user=request.user,
            score=score,
            status=MatchmakingTicket.Status.WAITING,
        )

    _broadcast_matchmaking_update(request.user.id, {
        'type': 'waiting',
        'ticket': _ticket_payload(ticket),
    })
    # Matching is handled asynchronously by matchmaking_worker.
    # Do not call _try_complete_matchmaking() here, otherwise this API can race
    # with the worker and trigger SQLite "database is locked" errors.
    return JsonResponse({'room': None, 'ticket': _ticket_payload(ticket)})


@csrf_exempt
@require_http_methods(['POST'])
def cancel_matchmaking(request):
    login_error = _require_login(request)
    if login_error:
        return login_error

    cancelled_tickets = []
    cancelled_room = None

    with transaction.atomic():
        ticket = (
            MatchmakingTicket.objects
            .select_for_update()
            .select_related('source_room', 'user')
            .filter(
                user=request.user,
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
            elif room.host_id != request.user.id:
                return _error('only the host can cancel room matchmaking.', status=403, code='host_required')
            else:
                cancelled_room = room
                cancelled_tickets = _cancel_room_matchmaking(room)
        else:
            solo_tickets = list(
                MatchmakingTicket.objects
                .select_for_update()
                .select_related('user')
                .filter(
                    user=request.user,
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
            _broadcast_room_update(cancelled_room)

    _broadcast_cancelled_matchmaking_tickets(cancelled_tickets, cancelled_room)

    if not cancelled_tickets:
        _broadcast_matchmaking_update(request.user.id, {
            'type': 'cancelled',
            'ticket': None,
        })

    return JsonResponse({
        'ticket': None,
        'room': _room_payload(cancelled_room, request.user) if cancelled_room is not None else None,
    })


@require_http_methods(['GET'])
def matchmaking_status(request):
    login_error = _require_login(request)
    if login_error:
        return login_error

    # Read-only status endpoint. Matching is handled by matchmaking_worker.
    membership = _active_membership(request.user)
    if membership is not None and membership.room.status == Room.Status.PLAYING:
        return JsonResponse({'room': _room_payload(membership.room, request.user), 'ticket': None})

    ticket = (
        MatchmakingTicket.objects
        .select_related('source_room')
        .filter(
            user=request.user,
            status=MatchmakingTicket.Status.WAITING,
        )
        .first()
    )

    if ticket and ticket.source_room_id:
        return JsonResponse({
            'room': _room_payload(ticket.source_room, request.user),
            'ticket': _ticket_payload(ticket),
        })

    return JsonResponse({
        'room': None,
        'ticket': _ticket_payload(ticket),
    })


# ============================================================================
# [測試功能] 遊戲測試頁面 - 僅用於開發測試
# ============================================================================
@require_http_methods(['GET'])
def game_test(request):
    """
    [測試功能] 遊戲測試介面
    提供簡易的 WebSocket 連接測試頁面，用於驗證遊戲引擎功能
    僅在開發環境使用，正式部署時應該移除或禁用此端點
    """
    context = {
        'is_authenticated': request.user.is_authenticated,
        'username': request.user.username if request.user.is_authenticated else None,
        'user_id': request.user.id if request.user.is_authenticated else None,
    }
    return render(request, 'game_test.html', context)
