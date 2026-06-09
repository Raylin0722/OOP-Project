import json
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.http import JsonResponse
from django.shortcuts import render  # [測試功能] 用於渲染 game_test.html
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import MatchParticipant, MatchmakingTicket, Room
from .services.auth_service import AuthService
from .services.exceptions import ServiceError
from .services.room_service import RoomService
from .services.matchmaking_service import MatchmakingService

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
    membership = _room_service().active_membership(user)
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



def _auth_service():
    return AuthService()


def _room_service():
    return RoomService(
        room_payload_builder=_room_payload,
        room_broadcast=_broadcast_room_update,
        room_deleted_broadcast=_broadcast_room_deleted,
        matchmaking_broadcast=_broadcast_matchmaking_update,
        test_mode_room_codes=TEST_MODE_ROOM_CODES,
    )


def _matchmaking_service():
    return MatchmakingService(
        room_payload_builder=_room_payload,
        room_broadcast=_broadcast_room_update,
        matchmaking_broadcast=_broadcast_matchmaking_update,
    )


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
        cleanup_callback=_room_service().cleanup_user_presence,
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
        cleaned_rooms = _room_service().cleanup_user_presence(request.user)
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

    try:
        room = _room_service().create_room(request.user)
    except ServiceError as error:
        return _service_error_response(error)

    return JsonResponse({'room': _room_payload(room, request.user)}, status=201)


@require_http_methods(['GET'])
def public_rooms(request):
    login_error = _require_login(request)
    if login_error:
        return login_error

    rooms = _room_service().public_rooms()
    room_payloads = [_room_payload(room, request.user) for room in rooms]

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

    try:
        room = _room_service().set_visibility(request.user, code, data)
    except ServiceError as error:
        if error.code == 'visibility_toggle_cooldown':
            return JsonResponse({
                'error': {
                    'code': error.code,
                    'message': error.message,
                },
                'wait_seconds': getattr(error, 'wait_seconds', 1),
                'room': _room_payload(getattr(error, 'room', _room_service().get_room(code)), request.user),
            }, status=error.status)
        return _service_error_response(error)

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

    try:
        room = _room_service().join_room(request.user, data)
    except ServiceError as error:
        return _service_error_response(error)

    return JsonResponse({'room': _room_payload(room, request.user)})


@require_http_methods(['GET'])
def current_room(request):
    login_error = _require_login(request)
    if login_error:
        return login_error

    room = _room_service().current_room(request.user)
    if room is None:
        return JsonResponse({'room': None})

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

    try:
        room = _room_service().set_ready(request.user, code, data)
    except ServiceError as error:
        return _service_error_response(error)

    return JsonResponse({'room': _room_payload(room, request.user)})


@csrf_exempt
@require_http_methods(['POST'])
def leave_room(request, code):
    login_error = _require_login(request)
    if login_error:
        return login_error

    try:
        result = _room_service().leave_room(request.user, code)
    except ServiceError as error:
        return _service_error_response(error)

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

    try:
        result = _room_service().kick_member(request.user, code, data)
    except ServiceError as error:
        return _service_error_response(error)

    refreshed_room = result['room']
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

    try:
        room = _room_service().transfer_host(request.user, code, data)
    except ServiceError as error:
        return _service_error_response(error)

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

    try:
        result = _room_service().start_room(
            request.user,
            code,
            data,
            matchmaking_service=_matchmaking_service(),
        )
    except ServiceError as error:
        return _service_error_response(error)

    room = result.get('room')
    ticket = result.get('ticket')
    response = {
        'room': _room_payload(room, request.user) if room is not None else None,
        'message': result.get('message'),
    }
    if ticket is not None:
        response['ticket'] = _matchmaking_service().ticket_payload(ticket)
    if result.get('test_mode'):
        response['test_mode'] = True

    return JsonResponse(response)


@csrf_exempt
@require_http_methods(['POST'])
def end_room(request, code):
    login_error = _require_login(request)
    if login_error:
        return login_error

    try:
        result = _room_service().end_room(request.user, code)
    except ServiceError as error:
        return _service_error_response(error)

    return JsonResponse(result)


@csrf_exempt
@require_http_methods(['POST'])
def join_matchmaking(request):
    login_error = _require_login(request)
    if login_error:
        return login_error
    blocked_error = _blocked_by_active_game(request.user)
    if blocked_error:
        return blocked_error

    try:
        result = _matchmaking_service().join_solo(request.user)
    except ServiceError as error:
        return _service_error_response(error)

    room = result.get('room')
    ticket = result.get('ticket')
    return JsonResponse({
        'room': _room_payload(room, request.user) if room is not None else None,
        'ticket': _matchmaking_service().ticket_payload(ticket),
    })


@csrf_exempt
@require_http_methods(['POST'])
def cancel_matchmaking(request):
    login_error = _require_login(request)
    if login_error:
        return login_error

    try:
        result = _matchmaking_service().cancel(request.user)
    except ServiceError as error:
        return _service_error_response(error)

    room = result.get('room')
    return JsonResponse({
        'ticket': None,
        'room': _room_payload(room, request.user) if room is not None else None,
    })


@require_http_methods(['GET'])
def matchmaking_status(request):
    login_error = _require_login(request)
    if login_error:
        return login_error

    result = _matchmaking_service().status(request.user)
    room = result.get('room')
    ticket = result.get('ticket')

    return JsonResponse({
        'room': _room_payload(room, request.user) if room is not None else None,
        'ticket': _matchmaking_service().ticket_payload(ticket),
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
