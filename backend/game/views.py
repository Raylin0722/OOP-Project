import json
import random
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render  # [測試功能] 用於渲染 game_test.html
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import EmailVerificationCode, MatchParticipant, MatchmakingTicket, PasswordResetCode, PlayerProfile, Room, RoomMember

User = get_user_model()
MATCHMAKING_TIMEOUT_SECONDS = 30
MATCHMAKING_SCORE_WINDOWS = (
    (0, 100),
    (10, 200),
    (20, 300),
)
TEST_MODE_ROOM_CODES = set()


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
            _user_payload(member.user)
            if member.user_id
            else {
                'id': None,
                'username': member.ai_name,
                'email': '',
                'email_verified': True,
                'nickname': member.ai_name,
                'total_score': 0,
                'win_rate': 0.0,
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
    return {
        'id': room.room_id,
        'code': room.code,
        'host_id': room.host_id,
        'status': room.get_status_display(),
        'member_count': member_count,
        'max_members': 4,
        'can_start': can_start,
        'members': member_payloads,
        'game_status': _game_reconnect_status(room, user),
        'test_mode': room.code in TEST_MODE_ROOM_CODES,
    }


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
        'timeout_seconds': MATCHMAKING_TIMEOUT_SECONDS,
        'score_window': _matchmaking_score_window(waited_for),
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


def _try_complete_matchmaking(anchor_user=None):
    with transaction.atomic():
        tickets = list(
            MatchmakingTicket.objects
            .select_for_update()
            .select_related('user', 'user__player_profile')
            .filter(status=MatchmakingTicket.Status.WAITING)
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
            return _create_match_room(fallback_tickets, ai_count=4 - len(fallback_tickets))

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
        MatchmakingTicket.objects.filter(user__in=users).delete()
        tickets = []
        for user in users:
            profile = getattr(user, 'player_profile', None)
            tickets.append(MatchmakingTicket.objects.create(
                user=user,
                score=profile.total_score if profile else 0,
                status=MatchmakingTicket.Status.WAITING,
            ))

        code = room.code
        room.delete()

    _broadcast_room_deleted(code)

    for ticket in tickets:
        _broadcast_matchmaking_update(ticket.user_id, {
            'type': 'waiting',
            'ticket': _ticket_payload(ticket),
        })

    # Matching is performed by the standalone management command:
    # python manage.py matchmaking_worker
    # Keep this view read/write only for ticket creation to avoid racing SQLite writes.
    matched_room = None
    user_ticket = next((ticket for ticket in tickets if ticket.user_id == anchor_user.id), None)
    return matched_room, user_ticket or (tickets[0] if tickets else None)


def _create_verification_code(user):
    code = f'{random.SystemRandom().randint(0, 999999):06d}'
    verification = EmailVerificationCode.objects.create(
        user=user,
        email=user.email,
        code=code,
        expires_at=timezone.now() + timedelta(minutes=15),
    )
    send_mail(
        subject='Email verification code',
        message=f'Your verification code is {code}. It expires in 15 minutes.',
        from_email=None,
        recipient_list=[user.email],
        fail_silently=False,
    )
    return verification


def _generate_code():
    return f'{random.SystemRandom().randint(0, 999999):06d}'


def _create_password_reset_code(user):
    token = secrets.token_urlsafe(48)
    reset_link = f'{settings.FRONTEND_BASE_URL}/?{urlencode({"reset_email": user.email, "reset_token": token})}'
    send_mail(
        subject='Password reset link',
        message=(
            'Use this link to reset your password. '
            'It expires in 15 minutes and can only be used once.\n\n'
            f'{reset_link}'
        ),
        from_email=None,
        recipient_list=[user.email],
        fail_silently=False,
    )
    PasswordResetCode.objects.filter(
        user=user,
        used_at__isnull=True,
    ).delete()
    reset_code = PasswordResetCode.objects.create(
        user=user,
        email=user.email,
        token=token,
        expires_at=timezone.now() + timedelta(minutes=15),
    )
    return reset_code


@csrf_exempt
@require_http_methods(['POST'])
def register(request):
    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    username = str(data.get('username', '')).strip()
    password = str(data.get('password', ''))
    password_confirm = str(data.get('password_confirm', ''))
    email = str(data.get('email', '')).strip().lower()
    nickname = str(data.get('nickname', '')).strip() or username

    if not username or not password or not password_confirm or not email:
        return _error('username, password, password_confirm, and email are required.')
    if len(password) < 8:
        return _error('password must be at least 8 characters.')
    if password != password_confirm:
        return _error('passwords do not match.', code='password_mismatch')

    try:
        validate_email(email)
    except ValidationError:
        return _error('email format is invalid.')

    if User.objects.filter(username=username).exists():
        return _error('username already exists.', code='username_exists')
    if User.objects.filter(email__iexact=email).exists():
        return _error('email already exists.', code='email_exists')

    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            is_active=False,
        )
        PlayerProfile.objects.create(user=user, nickname=nickname)
        _create_verification_code(user)

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

    email = str(data.get('email', '')).strip().lower()
    code = str(data.get('code', '')).strip()
    if not email or not code:
        return _error('email and code are required.')

    verification = (
        EmailVerificationCode.objects
        .select_related('user')
        .filter(email__iexact=email, code=code, verified_at__isnull=True)
        .order_by('-created_at')
        .first()
    )
    if verification is None:
        return _error('verification code is invalid.', status=404, code='invalid_code')
    if verification.is_expired:
        return _error('verification code is expired.', code='expired_code')

    user = verification.user
    user.email = verification.email
    user.is_active = True
    verification.verified_at = timezone.now()

    with transaction.atomic():
        user.save(update_fields=['email', 'is_active'])
        verification.save(update_fields=['verified_at'])

    return JsonResponse({'user': _user_payload(user), 'message': 'Email verified.'})


@csrf_exempt
@require_http_methods(['POST'])
def resend_verification(request):
    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    email = str(data.get('email', '')).strip().lower()
    user = User.objects.filter(email__iexact=email, is_active=False).first()
    if user is None:
        return _error('pending user not found.', status=404, code='pending_user_not_found')

    _create_verification_code(user)
    return JsonResponse({'message': 'Verification code sent.'})


@csrf_exempt
@require_http_methods(['POST'])
def request_password_reset(request):
    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    email = str(data.get('email', '')).strip().lower()
    if not email:
        return _error('email is required.')

    try:
        validate_email(email)
    except ValidationError:
        return _error('email format is invalid.')

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is not None:
        _create_password_reset_code(user)

    return JsonResponse({
        'message': 'If the email is registered, a password reset link has been sent.',
    })


@csrf_exempt
@require_http_methods(['POST'])
def reset_password(request):
    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    email = str(data.get('email', '')).strip().lower()
    token = str(data.get('token', '')).strip()
    new_password = str(data.get('new_password', ''))
    new_password_confirm = str(data.get('new_password_confirm', ''))
    if not email or not token or not new_password or not new_password_confirm:
        return _error('email, token, new_password, and new_password_confirm are required.')
    if len(new_password) < 8:
        return _error('new_password must be at least 8 characters.')
    if new_password != new_password_confirm:
        return _error('passwords do not match.', code='password_mismatch')

    reset_code = (
        PasswordResetCode.objects
        .select_related('user')
        .filter(email__iexact=email, token=token, used_at__isnull=True)
        .order_by('-created_at')
        .first()
    )
    if reset_code is None:
        return _error('password reset link is invalid.', status=404, code='invalid_token')
    if reset_code.is_expired:
        return _error('password reset link is expired.', code='expired_token')

    user = reset_code.user
    user.set_password(new_password)
    reset_code.used_at = timezone.now()

    with transaction.atomic():
        user.save(update_fields=['password'])
        reset_code.delete()

    return JsonResponse({'message': 'Password reset successful. You can log in now.'})


@csrf_exempt
@require_http_methods(['POST'])
def login_view(request):
    data = _json_body(request)
    if data is None:
        return _error('Invalid JSON body.')

    identifier = str(data.get('username', data.get('email', ''))).strip()
    password = str(data.get('password', ''))
    if not identifier or not password:
        return _error('username/email and password are required.')

    user = User.objects.filter(email__iexact=identifier).first()
    if user is None:
        user = User.objects.filter(username=identifier).first()
    username = user.username if user else identifier
    user = authenticate(request, username=username, password=password)
    if user is None:
        return _error('login failed.', status=401, code='invalid_credentials')
    if not user.is_active:
        return _error('email is not verified.', status=403, code='email_not_verified')

    login(request, user)
    return JsonResponse({'user': _user_payload(user)})


@csrf_exempt
@require_http_methods(['POST'])
def logout_view(request):
    logout(request)
    return JsonResponse({'message': 'Logged out.'})


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

    with transaction.atomic():
        membership.delete()
        remaining = list(room.members.order_by('joined_at', 'id'))
        if not remaining:
            code = room.code
            room.delete()
            _broadcast_room_deleted(code)
            return JsonResponse({'room': None})
        if room.host_id == request.user.id:
            next_host_member = next((member for member in remaining if member.user_id is not None), None)
            if next_host_member is None:
                code = room.code
                room.delete()
                _broadcast_room_deleted(code)
                return JsonResponse({'room': None})
            room.host = next_host_member.user
            room.save(update_fields=['host'])
        _sync_room_status(room)

    _broadcast_room_update(room)
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

    deleted, _ = room.members.filter(user_id=user_id).delete()
    if not deleted:
        return _error('player is not in this room.', status=404, code='member_not_found')
    _sync_room_status(room)
    _broadcast_room_update(room)
    return JsonResponse({'room': _room_payload(room, request.user)})


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
        matched_room, ticket = _start_room_matchmaking(room, request.user)
        if matched_room is not None:
            return JsonResponse({
                'room': _room_payload(matched_room, request.user),
                'ticket': None,
                'message': 'Matched and game started.',
            })
        return JsonResponse({
            'room': None,
            'ticket': _ticket_payload(ticket),
            'message': 'Matchmaking started.',
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

    MatchmakingTicket.objects.filter(
        user=request.user,
        status=MatchmakingTicket.Status.WAITING,
    ).update(status=MatchmakingTicket.Status.CANCELLED)
    _broadcast_matchmaking_update(request.user.id, {
        'type': 'cancelled',
        'ticket': None,
    })
    return JsonResponse({'ticket': None})


@require_http_methods(['GET'])
def matchmaking_status(request):
    login_error = _require_login(request)
    if login_error:
        return login_error

    # Read-only status endpoint. Matching is handled by matchmaking_worker.
    membership = _active_membership(request.user)
    if membership is not None and membership.room.status == Room.Status.PLAYING:
        return JsonResponse({'room': _room_payload(membership.room, request.user), 'ticket': None})

    ticket = MatchmakingTicket.objects.filter(
        user=request.user,
        status=MatchmakingTicket.Status.WAITING,
    ).first()
    return JsonResponse({'room': None, 'ticket': _ticket_payload(ticket)})


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
