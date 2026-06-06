from django.urls import re_path

from . import consumers
from .game_consumer import GameConsumer  # [測試功能] 遊戲 WebSocket Consumer

websocket_urlpatterns = [
    re_path(r'^ws/rooms/(?P<code>\d{6})/$', consumers.RoomConsumer.as_asgi()),
    re_path(r'^ws/matchmaking/$', consumers.MatchmakingConsumer.as_asgi()),
    # [測試功能] 遊戲測試 WebSocket 路由
    re_path(r'^ws/game/(?P<code>\d{6})/$', GameConsumer.as_asgi()),
]
