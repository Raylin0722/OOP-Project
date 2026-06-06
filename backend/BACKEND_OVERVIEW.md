# Backend Overview

這份文件整理目前 `backend/` 底下每個檔案的用途、主要函式/類別、參數、回傳資料，以及前端/遊戲引擎串接時會用到的 API。

## 整體架構

- HTTP API：`core/urls.py` 將 `/api/` 交給 `game/urls.py`，實作集中在 `game/views.py`。
- WebSocket：`core/asgi.py` 透過 Channels 掛載 `game/routing.py`。
- 房間與配對 WebSocket：`game/consumers.py`。
- 遊戲主 WebSocket：`game/game_consumer.py`，負責建立 `GameEngine`、處理玩家動作、AI 測試玩家、重連、倒數。
- 遊戲規則核心：`game/engine/`。
- AI 模型串接：`game/ai_adapter.py` 與 `game/ai_player.py`。
- 資料庫模型：`game/models.py`。

## 啟動/設定檔

### `backend/manage.py`

用途：Django CLI 入口。

| 函式 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `main()` | 無 | 無 | 設定 `DJANGO_SETTINGS_MODULE=core.settings`，呼叫 `execute_from_command_line(sys.argv)` 執行 Django 指令。 |

### `backend/Dockerfile`

用途：建立後端 Docker image。

- 使用 `python:3.12-slim`。
- 安裝 `requirements.txt`。
- 複製後端檔案到 `/app`。
- 入口為 `/app/entrypoint.sh`。
- 預設執行 `python manage.py runserver 0.0.0.0:8000`。

### `backend/entrypoint.sh`

用途：容器啟動腳本。

- `set -e`：任何命令失敗就中止。
- `exec "$@"`：執行 Docker CMD 傳入的命令。

### `backend/requirements.txt`

用途：後端 Python 依賴。

主要套件：

- `Django`
- `channels[daphne]`
- `channels-redis`
- `django-cors-headers`
- `python-dotenv`
- `certifi`
- `numpy`
- `torch`
- `termcolor`

## Django Core

### `backend/core/__init__.py`

用途：Django project package marker，無函式。

### `backend/core/settings.py`

用途：Django/Channels 設定。

重要設定：

- `.env` 載入位置：專案根目錄 `.env`。
- `SECRET_KEY` 來自 `DJANGO_SECRET_KEY`，沒有會直接 raise。
- `INSTALLED_APPS` 包含 `daphne`、`channels`、`corsheaders`、`game`。
- `CORS_ALLOW_ALL_ORIGINS=True`，`CORS_ALLOW_CREDENTIALS=True`。
- DB 使用 SQLite：`backend/db.sqlite3`。
- `ASGI_APPLICATION='core.asgi.application'`。
- Email 預設：若沒有 Gmail 設定則使用 console backend。
- Channel layer：
  - `CHANNEL_LAYER_BACKEND=inmemory` 時使用 `InMemoryChannelLayer`。
  - 否則使用 Redis：`channels_redis.core.RedisChannelLayer`。

### `backend/core/urls.py`

用途：HTTP URL 根路由。

| 路由 | 轉發/功能 |
| --- | --- |
| `/admin/` | Django admin |
| `/api/` | include `game.urls` |

### `backend/core/asgi.py`

用途：ASGI 入口，支援 HTTP 與 WebSocket。

重要物件：

- `django_asgi_app`：Django HTTP ASGI app。
- `application`：`ProtocolTypeRouter`。

WebSocket 使用：

- `AuthMiddlewareStack`
- `URLRouter(game.routing.websocket_urlpatterns)`

## Game App 基本檔

### `backend/game/__init__.py`

用途：Django app package marker，無函式。

### `backend/game/apps.py`

用途：Django app config。

| 類別 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `GameConfig(AppConfig)` | Django 自動建立 | AppConfig | 設定 app 名稱與預設 primary key 型別。 |

### `backend/game/admin.py`

用途：Django admin 註冊。

| 類別 | 管理模型 | 功能 |
| --- | --- | --- |
| `PlayerProfileAdmin` | `PlayerProfile` | 顯示 user、nickname、total_score、win_rate；支援搜尋。 |
| `RoomAdmin` | `Room` | 顯示 room_id、host、status；可用 status 篩選。 |
| `MatchRecordAdmin` | `MatchRecord` | 顯示 match_id、start_time、end_time。 |
| `MatchParticipantAdmin` | `MatchParticipant` | 顯示 match、user、player_rank、score_change。 |
| `EmailVerificationCodeAdmin` | `EmailVerificationCode` | 顯示 email、user、code、expires_at、verified_at。 |
| `PasswordResetCodeAdmin` | `PasswordResetCode` | 顯示 email、user、expires_at、used_at。 |

## 資料庫模型

### `backend/game/models.py`

#### `PlayerProfile`

用途：玩家公開資料/積分。

欄位：

- `user`：OneToOne 到 Django User，primary key。
- `nickname`
- `total_score`
- `win_rate`

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `__str__(self)` | 無 | `str` | 回傳 nickname。 |

#### `Room`

用途：房間資料。

欄位：

- `room_id`
- `code`：6 位房號。
- `host`
- `status`：`WAITING=0`、`PLAYING=1`、`FULL=2`。
- `room_password`
- `created_at`

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `__str__(self)` | 無 | `str` | 回傳 `Room <code>`。 |

#### `RoomMember`

用途：房間成員資料，可代表真人或 AI。

欄位：

- `room`
- `user`：真人玩家；AI 時可為 null。
- `is_ai`
- `ai_name`
- `is_ready`
- `joined_at`

限制：

- `unique_room_member`：同一房間同一 user 只能有一筆。

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `__str__(self)` | 無 | `str` | 回傳 user/ai_name 與 room。 |

#### `MatchmakingTicket`

用途：配對佇列。

欄位：

- `user`
- `score`
- `status`：`WAITING=0`、`MATCHED=1`、`CANCELLED=2`。
- `matched_room`
- `created_at`
- `updated_at`

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `__str__(self)` | 無 | `str` | 回傳 user 與目前配對狀態。 |

#### `MatchRecord`

用途：遊戲紀錄。

欄位：

- `match_id`
- `start_time`
- `end_time`

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `__str__(self)` | 無 | `str` | 回傳 `Match <match_id>`。 |

#### `MatchParticipant`

用途：紀錄單場遊戲中每位玩家排名與分數變化。

欄位：

- `match`
- `user`
- `player_rank`
- `score_change`

限制：

- 同一 match/user 不可重複。
- 同一 match/player_rank 不可重複。

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `__str__(self)` | 無 | `str` | 回傳 user 與 match。 |

#### `EmailVerificationCode`

用途：Email 驗證碼。

欄位：

- `user`
- `email`
- `code`
- `created_at`
- `expires_at`
- `verified_at`

| 方法/屬性 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `is_verified` | 無 | `bool` | `verified_at is not None`。 |
| `is_expired` | 無 | `bool` | 現在時間是否超過 `expires_at`。 |
| `__str__(self)` | 無 | `str` | 回傳 email/code。 |

#### `PasswordResetCode`

用途：密碼重設 token。

欄位：

- `user`
- `email`
- `token`
- `created_at`
- `expires_at`
- `used_at`

| 方法/屬性 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `is_used` | 無 | `bool` | `used_at is not None`。 |
| `is_expired` | 無 | `bool` | 現在時間是否超過 `expires_at`。 |
| `__str__(self)` | 無 | `str` | 回傳 email。 |

## HTTP API 路由

### `backend/game/urls.py`

所有路由都掛在 `/api/` 底下。

| Method | Path | View | 功能 |
| --- | --- | --- | --- |
| POST | `/api/auth/register/` | `register` | 註冊帳號並寄驗證碼。 |
| POST | `/api/auth/verify-email/` | `verify_email` | 驗證 email。 |
| POST | `/api/auth/resend-verification/` | `resend_verification` | 重寄驗證碼。 |
| POST | `/api/auth/request-password-reset/` | `request_password_reset` | 寄密碼重設連結。 |
| POST | `/api/auth/reset-password/` | `reset_password` | 重設密碼。 |
| POST | `/api/auth/login/` | `login_view` | session 登入。 |
| POST | `/api/auth/logout/` | `logout_view` | 登出。 |
| GET | `/api/auth/me/` | `me` | 取得目前登入 user。 |
| POST | `/api/rooms/create/` | `create_room` | 建立房間。 |
| POST | `/api/rooms/join/` | `join_room` | 加入房間。 |
| GET | `/api/rooms/current/` | `current_room` | 取得目前所在房間。 |
| POST | `/api/rooms/<code>/ready/` | `set_room_ready` | 設定 ready。 |
| POST | `/api/rooms/<code>/leave/` | `leave_room` | 離開房間。 |
| POST | `/api/rooms/<code>/kick/` | `kick_room_member` | 房主踢人。 |
| POST | `/api/rooms/<code>/transfer-host/` | `transfer_room_host` | 房主轉讓。 |
| POST | `/api/rooms/<code>/start/` | `start_room` | 開始房間遊戲。 |
| POST | `/api/rooms/<code>/end/` | `end_room` | 結束/刪除房間。 |
| POST | `/api/matchmaking/join/` | `join_matchmaking` | 加入配對。 |
| POST | `/api/matchmaking/cancel/` | `cancel_matchmaking` | 取消配對。 |
| GET | `/api/matchmaking/status/` | `matchmaking_status` | 查詢配對狀態。 |
| GET | `/api/test/` | `game_test` | 舊測試 HTML 頁。 |

## HTTP View 實作

### `backend/game/views.py`

#### 共用 helper

| 函式 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `_json_body(request)` | Django request | `dict` 或 `None` | 解析 JSON body；格式錯誤回傳 `None`。 |
| `_error(message, status=400, code='bad_request')` | 錯誤訊息、HTTP status、錯誤 code | `JsonResponse` | 統一錯誤格式：`{'error': {'code', 'message'}}`。 |
| `_user_payload(user)` | Django user | `dict` | 前端使用的 user 物件，含 profile、分數、驗證狀態。 |
| `_require_login(request)` | Django request | `JsonResponse` 或 `None` | 未登入回 401；已登入回 `None`。 |
| `_room_code()` | 無 | `str` | 產生唯一 6 位房號；最多嘗試 20 次。 |
| `_active_membership(user)` | user | `RoomMember` 或 `None` | 找使用者目前在等待/滿房/遊戲中的最新房間。 |
| `_sync_room_status(room)` | `Room` | 無 | 非遊戲中房間依人數同步成 `WAITING` 或 `FULL`。 |
| `_game_reconnect_status(room, user)` | `Room`, user | `dict` | 回傳遊戲中重連狀態：`can_return`、`reconnect_blocked`、`auto_enter`、`reason`。 |
| `_blocked_by_active_game(user)` | user | `JsonResponse` 或 `None` | 若玩家被 AI 取代並處罰，阻止建立/加入新局。 |
| `_room_payload(room, user=None)` | `Room`, optional user | `dict` | 房間完整 payload，含 members、can_start、game_status、test_mode。 |
| `_get_room_or_error(code)` | 房號 | `(Room, None)` 或 `(None, JsonResponse)` | 查房間，不存在回 404 error。 |
| `_broadcast_room_update(room, payload=None)` | `Room`, optional payload | 無 | 送 Channels group `room_<code>` 的 `room.updated`。 |
| `_broadcast_room_deleted(code)` | 房號 | 無 | 送 Channels group `room_<code>` 的 `room.deleted`。 |
| `_broadcast_matchmaking_update(user_id, payload)` | user id、payload | 無 | 送 Channels group `user_<id>` 的 `matchmaking.updated`。 |
| `_ticket_payload(ticket)` | `MatchmakingTicket` 或 `None` | `dict` 或 `None` | 配對 ticket 給前端的格式。 |
| `_create_match_room(tickets, ai_count=0)` | tickets list、AI 數量 | `Room` 或 `None` | 建立配對房、加入玩家/AI、更新 ticket、廣播 matched。 |
| `_waiting_tickets()` | 無 | `list[MatchmakingTicket]` | 取得等待中的配對 ticket。 |
| `_matchmaking_score_window(waited_seconds)` | 等待秒數 | `int` | 依等待時間放寬配對分數差。 |
| `_try_complete_matchmaking(anchor_user=None)` | optional user | `Room` 或 `None` | 嘗試配對 4 人；逾時不足人數時補 AI。 |
| `_create_verification_code(user)` | user | `EmailVerificationCode` | 建立 6 位 email 驗證碼並寄信。 |
| `_generate_code()` | 無 | `str` | 產生 6 位數字字串。 |
| `_create_password_reset_code(user)` | user | `PasswordResetCode` | 建立 token、寄重設連結、刪除舊未用 token。 |

#### Auth API

| 函式 | Method/Path | Body/參數 | 回傳 | 功能 |
| --- | --- | --- | --- | --- |
| `register(request)` | POST `/api/auth/register/` | `username`, `password`, `password_confirm`, `email`, optional `nickname` | 201 `{'user', 'message'}` | 建立 inactive user、profile、email 驗證碼。 |
| `verify_email(request)` | POST `/api/auth/verify-email/` | `email`, `code` | `{'user', 'message'}` | 驗證 code，啟用 user。 |
| `resend_verification(request)` | POST `/api/auth/resend-verification/` | `email` | `{'message'}` | 對尚未啟用 user 重寄驗證碼。 |
| `request_password_reset(request)` | POST `/api/auth/request-password-reset/` | `email` | `{'message'}` | 若 email 存在，寄重設連結。 |
| `reset_password(request)` | POST `/api/auth/reset-password/` | `email`, `token`, `new_password`, `new_password_confirm` | `{'message'}` | 驗證 token 後重設密碼。 |
| `login_view(request)` | POST `/api/auth/login/` | `username` 或 `email`, `password` | `{'user'}` | Django session 登入。 |
| `logout_view(request)` | POST `/api/auth/logout/` | 無 | `{'message'}` | 登出。 |
| `me(request)` | GET `/api/auth/me/` | session cookie | `{'user'}` | 回傳目前登入者；未登入 401。 |

#### Room API

| 函式 | Method/Path | Body/參數 | 回傳 | 功能 |
| --- | --- | --- | --- | --- |
| `create_room(request)` | POST `/api/rooms/create/` | 無 | 201 `{'room'}` | 建立新房，使用者成為 host。若有等待房會先離開。 |
| `join_room(request)` | POST `/api/rooms/join/` | `code` | `{'room'}` | 加入 6 位房號房間；滿房或 Playing 會拒絕。 |
| `current_room(request)` | GET `/api/rooms/current/` | 無 | `{'room': room or None}` | 找目前所在房間並同步狀態。 |
| `set_room_ready(request, code)` | POST `/api/rooms/<code>/ready/` | optional `is_ready` | `{'room'}` | 切換/設定 ready。 |
| `leave_room(request, code)` | POST `/api/rooms/<code>/leave/` | 無 | `{'room': None}` | 離開房間；若沒人則刪房；host 離開會轉讓。 |
| `kick_room_member(request, code)` | POST `/api/rooms/<code>/kick/` | `user_id` | `{'room'}` | 房主踢指定玩家。 |
| `transfer_room_host(request, code)` | POST `/api/rooms/<code>/transfer-host/` | `user_id` | `{'room'}` | 房主轉讓 host。 |
| `start_room(request, code)` | POST `/api/rooms/<code>/start/` | optional `test_mode` | `{'room', 'test_mode', 'message'}` | 房主開始遊戲；非測試需 4 人且全 ready。 |
| `end_room(request, code)` | POST `/api/rooms/<code>/end/` | 無 | `{'room': None, 'message'}` | 房內玩家可刪除房間。 |

#### Matchmaking API

| 函式 | Method/Path | Body/參數 | 回傳 | 功能 |
| --- | --- | --- | --- | --- |
| `join_matchmaking(request)` | POST `/api/matchmaking/join/` | 無 | `{'room', 'ticket'}` | 加入配對，依分數/等待時間嘗試成局。 |
| `cancel_matchmaking(request)` | POST `/api/matchmaking/cancel/` | 無 | `{'ticket': None}` | 取消等待中 ticket。 |
| `matchmaking_status(request)` | GET `/api/matchmaking/status/` | 無 | `{'room', 'ticket'}` | 查詢配對；也會順便嘗試完成配對。 |

#### Test Page

| 函式 | Method/Path | Body/參數 | 回傳 | 功能 |
| --- | --- | --- | --- | --- |
| `game_test(request)` | GET `/api/test/` | 無 | HTML render | 渲染 `game_test.html`，提供舊版 WebSocket 測試頁。 |

## WebSocket 路由

### `backend/game/routing.py`

| Path | Consumer | 功能 |
| --- | --- | --- |
| `/ws/rooms/<code>/` | `RoomConsumer` | 房間狀態推播。 |
| `/ws/matchmaking/` | `MatchmakingConsumer` | 配對狀態推播。 |
| `/ws/game/<code>/` | `GameConsumer` | 遊戲狀態與遊戲動作。 |

## 房間/配對 WebSocket

### `backend/game/consumers.py`

#### `RoomConsumer`

用途：房間大廳即時更新。

| 方法 | 參數 | 回傳/送出 | 功能 |
| --- | --- | --- | --- |
| `connect(self)` | 無 | accept 或 close 4401/4403 | 檢查登入與房間成員，加入 `room_<code>` group，送第一次 `room_update`。 |
| `disconnect(self, close_code)` | close code | 無 | 離開 group。 |
| `room_updated(self, event)` | Channels event | 送 `room_update` 或 `room_left` | 收到房間更新時重送最新 room payload。 |
| `room_deleted(self, event)` | Channels event | 送 `room_deleted` 並關閉 | 房間被刪除時通知前端。 |
| `_send_room_update(self, extra_payload=None)` | optional dict | WebSocket message | 送 `{type:'room_update', room, ...extra}`。 |
| `_is_room_member(self)` | 無 | `bool` | DB 查詢目前 user 是否在 room。 |
| `_room_payload(self)` | 無 | `dict` 或 `None` | 取得 `_room_payload(room, user)`。 |

Room WebSocket message：

- `room_update`：`{type, room, ...extra_payload}`
- `room_left`
- `room_deleted`

#### `MatchmakingConsumer`

用途：配對狀態即時更新。

| 方法 | 參數 | 回傳/送出 | 功能 |
| --- | --- | --- | --- |
| `connect(self)` | 無 | accept 或 close 4401 | 檢查登入，加入 `user_<id>` group，送目前狀態。 |
| `disconnect(self, close_code)` | close code | 無 | 離開 group。 |
| `matchmaking_updated(self, event)` | Channels event | WebSocket message | 直接送出 event payload。 |
| `_send_current_status(self)` | 無 | WebSocket message | 送 `_status_payload()`。 |
| `_status_payload(self)` | 無 | `dict` | 嘗試配對後回傳 `waiting` 或 `idle`。 |

Matchmaking WebSocket message：

- `waiting`：`{type:'waiting', ticket}`
- `matched`：由 `views._create_match_room` 廣播，`{type:'matched', room}`
- `cancelled`：`{type:'cancelled', ticket:null}`
- `idle`：`{type:'idle', ticket:null}`

## 遊戲 WebSocket

### `backend/game/game_consumer.py`

用途：目前真正管理整場遊戲的 WebSocket consumer。它不是純遊戲規則，純規則在 `game/engine/game_engine.py`；此檔負責把房間、WebSocket、engine、AI、倒數、重連串起來。

重要 class-level state：

- `game_engines: Dict[str, GameEngine]`：room code -> engine。
- `disconnected_players`：room code -> player id -> 斷線資訊。
- `room_monitor_tasks`：room code -> asyncio task，負責倒數與斷線監控。
- `game_events`：room code -> debug event list。

#### 前端可送入的 action

| action | 需要欄位 | 說明 |
| --- | --- | --- |
| `start_game` | optional `test_mode` | 房主建立 `GameEngine` 並開始遊戲。測試模式會補 AI 到 4 人。 |
| `play_card` | `card_index`；特殊牌另需 `chosen_color`、`target_player_index`、`return_card_index` | 出牌。 |
| `draw_card` | 無 | 抽牌；若有累加懲罰就抽懲罰張數。 |
| `use_skill` | `params` | 使用角色技能。 |
| `get_state` | 無 | 取得目前 `game_state`。 |
| `debug_state` | 無 | 取得 debug 狀態，包含所有玩家手牌。 |

#### 後端會送出的 message

| type | 內容 | 說明 |
| --- | --- | --- |
| `game_state` | `{state, hand}` | 全局狀態 + 此連線玩家自己的手牌。 |
| `debug_state` | `{state, current_player, players, events}` | Debug 用，包含所有手牌。 |
| `game_started` | `success`, `phase`, `current_player`, `first_card` | 遊戲開始。 |
| `card_played` | engine result | 有玩家出牌。 |
| `card_drawn` | player/count/next_player/reason | 有玩家抽牌。 |
| `skill_used` | skill result | 有玩家使用技能。 |
| `game_ended` | winner/final_rankings/reason | 遊戲結束。 |
| `error` | `message` | 錯誤訊息。 |

#### Close code

| code | 意義 |
| --- | --- |
| `4401` | 未登入。 |
| `4403` | 不是房間成員。 |
| `4408` | 已被 AI replacement/處罰，禁止重回該局。 |

#### 方法清單

| 方法 | 參數 | 回傳/送出 | 功能 |
| --- | --- | --- | --- |
| `connect(self)` | 無 | accept/close + `game_state` | 驗證登入、房間成員、debug flag、重連限制，加入 `game_<code>` group。 |
| `disconnect(self, close_code)` | close code | 無 | 非 debug 連線會標記玩家斷線，離開 group。 |
| `receive(self, text_data)` | JSON string | 依 action dispatch | 解析前端 action 並呼叫對應 handler。 |
| `handle_start_game(self, data=None)` | optional dict | `game_started` + `game_state` | 房主建立 players、隨機技能、測試模式補 AI、建立 `GameEngine`。 |
| `handle_play_card(self, data)` | dict | `card_played` 或 `error` | 驗證回合/卡片/特殊牌參數，建立 `PlayCardCommand`，呼叫 `engine.play_turn()`。 |
| `handle_draw_card(self)` | 無 | `card_drawn` 或 `error` | 當前玩家抽牌，清除 draw penalty，換下一位。 |
| `handle_use_skill(self, data)` | dict | `skill_used` 或 `error` | 驗證可用技能，呼叫 `current_player.use_skill(engine, **params)`。 |
| `_run_test_ai_turns(self, engine)` | `GameEngine` | group messages | 測試模式中若輪到 AI，延遲後自動出牌/抽牌；直到輪到真人或遊戲結束。 |
| `_play_test_ai_turn(self, engine, current_player)` | engine、AI player | `dict` | 先嘗試模型 AI，失敗 fallback 第一張可出牌。 |
| `_play_model_ai_turn(self, engine, current_player)` | engine、AI player | `dict` 或 `None` | 呼叫 DQN checkpoint，將 RLCard action 轉成 engine command。 |
| `_play_first_playable_ai_turn(self, engine, current_player)` | engine、AI player | `dict` | 找第一張可出的牌，沒有就抽牌。 |
| `_find_ai_payload_card(self, current_player, payload)` | player、AI payload | card 或 `None` | 依 `card_name` 在 AI 手牌中找牌。 |
| `_build_test_ai_command(self, engine, current_player, card)` | engine、player、card | `PlayCardCommand` | 為 AI 特殊牌補顏色/目標/return index。 |
| `_choose_test_ai_color(self, current_player, fallback_color)` | player、fallback color | `CardColor` | AI 選手牌中最多的顏色。 |
| `_first_other_player_index(self, engine)` | engine | `int` | 回傳第一個不是當前玩家的 index。 |
| `_is_test_ai_player(player)` | player | `bool` | player_id 是否以 `ai_` 開頭。 |
| `_handle_player_disconnected(self)` | 無 | `game_state` | 將真人玩家標成斷線並啟動 monitor。 |
| `_handle_player_reconnected(self)` | 無 | `game_state` | 若玩家回來，取消斷線；若尚未超時替換，可恢復身份。 |
| `_ensure_room_monitor(self)` | 無 | 無 | 確保該 room 有一個 monitor task。 |
| `_monitor_disconnected_players(self, room_code, group_name)` | room code、group | group messages | 每秒送 state、處理 30 秒超時抽牌、180 秒 AI replacement。 |
| `_replace_disconnected_player_with_ai(self, engine, player_id, info)` | engine、player id、info | `bool` | 將斷線玩家改成 AI，標記 `settlement_penalty=True`。 |
| `_find_player_by_original_id(self, engine, player_id)` | engine、player id | player 或 `None` | 找真人原始 id 對應的玩家。 |
| `_is_rejoin_blocked(self)` | 無 | `bool` | 玩家是否已被 AI replacement/處罰。 |
| `_draw_for_player(self, engine, player, reason)` | engine、player、reason | `dict` | 統一抽牌並換人，用於 timeout/AI/manual。 |
| `_broadcast_game_state(self)` | 無 | group event | 廣播 `game_state_updated`。 |
| `game_started(self, event)` | Channels event | WS `game_started` + state | group handler。 |
| `card_played(self, event)` | Channels event | WS `card_played` + state | group handler。 |
| `card_drawn(self, event)` | Channels event | WS `card_drawn` + state | group handler。 |
| `skill_used(self, event)` | Channels event | WS `skill_used` + state | group handler。 |
| `game_ended(self, event)` | Channels event | WS `game_ended` + state | group handler。 |
| `game_state_updated(self, event)` | Channels event | WS `game_state` | group handler。 |
| `_send_game_state(self)` | 無 | WS `game_state` | 建立 `GameState` 與此 user 的 `PlayerHandState`。 |
| `_send_debug_state(self)` | 無 | WS `debug_state` | 送所有玩家完整手牌、可出牌 indexes、事件紀錄。 |
| `_record_game_event(self, event_type, payload)` | event type、payload | 無 | 存最近 100 筆 debug event。 |
| `send_error(self, message)` | message | WS `error` | 統一錯誤送出。 |
| `_is_room_member(self)` | 無 | `bool` | DB 查使用者是否是房間成員。 |
| `_is_host(self)` | 無 | `bool` | DB 查使用者是否是 host。 |
| `_get_room_members(self)` | 無 | `list[dict]` | 取得房間成員 id/nickname。 |
| `_assign_random_skill(self)` | 無 | `str` | 回傳 `seer/painter/scout/queen` 之一。 |
| `_set_room_playing(self)` | 無 | 無 | DB 將房間改成 Playing。 |
| `_mark_room_playing(self, test_mode=False)` | bool | room group update | 標記 Playing 並通知 room websocket。 |

## AI 串接

### `backend/game/ai_adapter.py`

用途：把本地 `GameEngine` 狀態轉成 custom RLCard UNO DQN 模型可讀的 state，也把模型 action 轉回遊戲 payload。

重要常數：

- `ACTION_SPACE`：RLCard action string -> action id。
- `ACTION_LIST`：action id -> RLCard action string。
- 顏色映射：engine `red/green/blue/yellow/black` 對應 RLCard `r/g/b/y`。

| 函式 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `build_action_space()` | 無 | `OrderedDict[str, int]` | 建立所有模型 action id。 |
| `card_to_rlcard(card, fallback_color='red')` | engine card 或字串 | `str` 或 `None` | 將卡牌轉成 `r-1`、`g-reverse` 等格式。 |
| `cards_to_rlcard(cards, fallback_color='red')` | cards iterable | `list[str]` | 批次轉換手牌。 |
| `action_to_engine_payload(action)` | RLCard action string | `dict` | 轉成 GameConsumer payload，例如 `draw_card`、`play_card`、`use_skill`。 |
| `build_rlcard_raw_state(engine, player_index=None)` | engine、玩家 index | `dict` | 建立模型 raw state：hand、target、num_cards、direction、pending draw、skills 等。 |
| `build_model_state(engine, player_index=None)` | engine、玩家 index | `dict` | 建立 agent `eval_step(state)` 需要的 state，含 `obs`、`legal_actions`。 |
| `build_legal_actions(engine, player_index)` | engine、玩家 index | `list[str]` | 由 engine 可出牌判斷產生模型 legal actions；沒有可出則 `['draw']`。 |
| `encode_observation(raw_state)` | raw state | `list[list[list[float]]]` | 編碼成 12 x 4 x 19 observation。 |
| `_card_legal_actions(card, engine, player_index)` | card、engine、玩家 index | `list[str]` | 單張牌對應的模型 action。 |
| `_encode_hand(obs, hand)` | obs、hand | 無 | 把手牌寫入 observation。 |
| `_encode_target(plane, target)` | plane、target | 無 | 把目標牌/棄牌頂寫入 observation。 |
| `_split_rlcard(card)` | RLCard card string | `(color_index, trait_index)` | 拆 `r-1` 格式。 |
| `_zeros(depth, rows, cols)` | int, int, int | 3D list | 建立零矩陣。 |
| `_skill_to_rlcard(skill)` | skill object | `str` 或 `None` | `SeerSkill` 等轉成 `skill_1` 等。 |
| `_skill_cooldown(player)` | player | `int` | 粗略計算技能 cooldown。 |
| `_skill_remaining(player, skill_number)` | player、技能編號 | `int` | 回傳 Scout/Queen 剩餘次數。 |

### `backend/game/ai_player.py`

用途：Lazy load OOP-AI 裡的 custom RLCard DQN checkpoint，提供 AI 決策。

| 類別/函式 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `AIDecision` | `action_id`, `rlcard_action`, `payload`, `info` | dataclass | 模型決策結果。 |
| `DQNCheckpointPlayer.__init__(checkpoint_path=None, ai_project_root=None, device='cpu')` | checkpoint、AI project root、device | instance | 設定 checkpoint 與 `/oop-ai/vendor/rlcard` 路徑。 |
| `DQNCheckpointPlayer.decide(engine, player_index=None)` | engine、玩家 index | `AIDecision` | 建 state，呼叫 `agent.eval_step`，轉成 engine payload。 |
| `DQNCheckpointPlayer._load_agent()` | 無 | RLCard `DQNAgent` | Lazy import torch/rlcard，載入 checkpoint。 |
| `DQNCheckpointPlayer._ensure_ai_path()` | 無 | 無 | 將 OOP-AI vendored rlcard 加入 `sys.path`。 |
| `get_default_ai_player()` | 無 | `DQNCheckpointPlayer` | Singleton 預設 AI player。 |

環境變數：

- `AI_CHECKPOINT_PATH`：預設 `/oop-ai/experiments/200k-rand-v1/checkpoint_dqn.pt`。
- `AI_PROJECT_ROOT`：預設 `/oop-ai`。
- `AI_DEVICE`：預設 `cpu`。

## 遊戲引擎

### `backend/game/engine/__init__.py`

用途：集中 re-export engine API，讓其他檔案可以 `from .engine import GameEngine, Player, CardColor...`。

主要 exports：

- 卡牌：`CardType`, `CardColor`, `PlayCardCommand`, `AbstractCard`, 各卡牌 class, `DeckFactory`。
- 技能：`SkillBehavior`, `SeerSkill`, `PainterSkill`, `ScoutSkill`, `QueenSkill`, `SkillFactory`。
- 玩家：`HandManager`, `Player`。
- 引擎：`GamePhase`, `GameEngine`。
- 狀態：`PlayerState`, `GameState`, `PlayerHandState`, `GameAction`, `GameHistory`。

### `backend/game/engine/cards.py`

用途：定義卡牌種類、顏色、出牌命令、每種牌的效果、牌組工廠。

#### Enums

| 類別 | 值 | 功能 |
| --- | --- | --- |
| `CardType` | `NUMBER`, `SKIP`, `REVERSE`, `DRAW2`, `WILD`, `WILD_DRAW4`, `SWAP_HAND`, `STEAL_CARD`, `NEIGHBOR_SWAP`, `TARGET_DRAW2` | 卡牌類型。 |
| `CardColor` | `RED`, `BLUE`, `GREEN`, `YELLOW`, `BLACK` | 卡牌顏色，黑色為 wild/特殊黑牌。 |

#### `GameContext(Protocol)`

用途：卡牌效果需要呼叫的 engine 方法介面。

方法：

- `skip_next_player() -> None`
- `reverse_order() -> None`
- `add_draw_penalty(count: int) -> None`
- `change_color(color: CardColor) -> None`
- `swap_hands_with_target(target_index: int) -> None`
- `steal_and_return_card(target_index: int, return_card_index: Optional[int]) -> None`
- `neighbor_swap() -> None`
- `target_draw_cards(target_index: int, count: int) -> None`

#### `PlayCardCommand`

用途：出牌指令物件。

欄位：

- `card: AbstractCard`
- `player_id: str`
- `chosen_color: Optional[CardColor]`
- `target_player_index: Optional[int]`
- `return_card_index: Optional[int]`

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `execute(context)` | `GameContext` | 無 | 呼叫 `card.execute_effect(context, self)`。 |
| `validate()` | 無 | `bool` | 驗證 wild 需要 chosen_color；target 類牌需要 target index。 |

#### `AbstractCard`

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `__init__(color, value, card_type)` | 顏色、值、類型 | instance | 建立卡牌基底資料。 |
| `color` | property | `CardColor` | 卡牌顏色。 |
| `value` | property | `str` | 卡牌值。 |
| `card_type` | property | `CardType` | 卡牌類型。 |
| `can_play_on(field_color, field_value)` | 當前顏色、當前值 | `bool` | 黑牌可出；否則顏色或 value 相同可出。 |
| `execute_effect(context, command)` | context、command | 無 | 抽象方法，由子類實作。 |
| `to_dict()` | 無 | `dict` | `{color, value, type}`。 |
| `__str__()` | 無 | `str` | `<color> <value>`。 |

#### 卡牌類別

| 類別 | 初始化參數 | execute_effect 功能 |
| --- | --- | --- |
| `NumberCard` | `color`, `number` | 無效果。 |
| `SkipCard` | `color` | `context.skip_next_player()`。 |
| `ReverseCard` | `color` | `context.reverse_order()`。 |
| `Draw2Card` | `color` | `context.add_draw_penalty(2)`。 |
| `WildCard` | 無 | 依 `chosen_color` 改色。 |
| `WildDraw4Card` | 無 | `add_draw_penalty(4)` 並改色。 |
| `SwapHandCard` | 無 | 與目標玩家交換手牌。 |
| `StealCardCard` | `color` | 從目標玩家偷一張，再還一張。 |
| `NeighborSwapCard` | 無 | 每位玩家與鄰近玩家交換/傳遞一張牌。 |
| `TargetDraw2Card` | 無 | 指定玩家抽 2 張。 |

#### `DeckFactory`

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `create_standard_deck()` | 無 | `list[AbstractCard]` | 建立 117 張客製 UNO 牌組。 |
| `create_shuffled_deck()` | 無 | `list[AbstractCard]` | 建立並 shuffle 牌組。 |
| `validate_deck(deck)` | 牌組 | `bool` | 檢查牌組總數與各類牌數是否符合設計。 |

模組函式：

| 函式 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `create_standard_deck()` | 無 | `list[AbstractCard]` | 呼叫 `DeckFactory.create_standard_deck()`。 |

### `backend/game/engine/player.py`

用途：玩家與手牌管理。

#### `HandManager`

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `__init__(max_hand_size=50)` | 最大手牌數 | instance | 初始化手牌。 |
| `cards` | property | `list[AbstractCard]` | 回傳手牌 copy。 |
| `add_card(card)` | card | `bool` | 手牌未滿則加入。 |
| `remove_card(card)` | card | `bool` | 移除指定 card。 |
| `remove_card_at(index)` | index | card 或 `None` | 依 index 移除。 |
| `get_card(index)` | index | card 或 `None` | 依 index 取得。 |
| `get_card_at(index)` | index | card 或 `None` | `get_card` alias。 |
| `get_cards()` | 無 | `list[AbstractCard]` | 回傳手牌 copy。 |
| `get_playable_cards(current_color, current_number, draw_penalty=0)` | 顏色、數字、累加抽牌 | `list[AbstractCard]` | 回傳可出的牌；有 penalty 時只允許 Draw2/WildDraw4。 |
| `get_size()` | 無 | `int` | 手牌數。 |
| `is_empty()` | 無 | `bool` | 是否無牌。 |
| `has_card(card)` | card | `bool` | 是否持有該牌。 |
| `can_play(card, field_color, field_value)` | card、場色、場值 | `bool` | 是否持有且可壓場牌。 |
| `find_playable_cards(field_color, field_value)` | 場色、場值 | `list` | 依 `card.can_play_on` 找可出牌。 |
| `sort_by_color()` | 無 | 無 | 按顏色排序。 |
| `sort_by_value()` | 無 | 無 | 按 value 排序。 |
| `sort_by_type()` | 無 | 無 | 按 type 排序。 |
| `clear()` | 無 | 無 | 清空手牌。 |
| `swap_with(other)` | 另一個 `HandManager` | 無 | 交換手牌 list。 |
| `to_dict(hide_cards=False)` | 是否隱藏牌 | `dict` | 隱藏時只回 `card_count`，否則回 cards + count。 |

#### `Player`

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `__init__(player_id, name, skill=None, is_ai=False)` | id、名稱、技能、AI flag | instance | 建立玩家。 |
| `play_card(card)` | card | card 或 `None` | 從手牌移除指定牌。 |
| `play_card_at(index)` | index | card 或 `None` | 依 index 出牌。 |
| `draw_card(card)` | card | `bool` | 加入一張牌。 |
| `draw_cards(cards)` | card list | `int` | 加入多張牌，回成功張數。 |
| `get_hand_size()` | 無 | `int` | 手牌數。 |
| `has_cards()` | 無 | `bool` | 是否仍有手牌。 |
| `has_won()` | 無 | `bool` | 手牌是否為 0。 |
| `get_hand()` | 無 | `HandManager` | 取得手牌管理器。 |
| `can_use_skill(**kwargs)` | 技能條件 | `bool` | 轉呼叫 skill.can_use。 |
| `use_skill(engine, **kwargs)` | engine、技能參數 | `dict` | 執行技能並增加使用次數。 |
| `start_turn()` | 無 | 無 | turn_count + 1。 |
| `increment_turn()` | 無 | 無 | turn_count + 1。 |
| `reset_turn_count()` | 無 | 無 | turn_count 歸零。 |
| `reset_skill()` | 無 | 無 | skill_used_count 歸零，並呼叫 skill.reset。 |
| `swap_hands_with(other)` | 另一玩家 | 無 | 與另一玩家交換手牌。 |
| `to_dict(hide_hand=False)` | 是否隱藏手牌 | `dict` | 玩家資料、手牌、技能、AI flag。 |

### `backend/game/engine/game_engine.py`

用途：核心遊戲流程與規則。

#### `GamePhase`

值：

- `WAITING`
- `STARTING`
- `PLAYING`
- `FINISHED`

#### `GameEngine`

初始化：

- `__init__(players: List[Player])`
- 玩家數必須 2 到 4 人。
- 狀態包含玩家、牌堆、棄牌堆、目前顏色/數字、方向、draw penalty、15 分鐘局限時、30 秒回合限時。

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `start_game()` | 無 | `dict` | 洗牌、每人發 5 張、翻第一張數字牌、進入 Playing。 |
| `_draw_initial_discard_card()` | 無 | `AbstractCard` 或 `None` | 從牌堆找第一張 number card 作為開場棄牌，避免開局特殊牌未解析。 |
| `play_turn(command)` | `PlayCardCommand` | `dict` | 驗證階段/玩家/手牌/能否出牌，更新棄牌、執行效果、檢查勝利、換人。 |
| `draw_cards_for_player(player, count)` | player、張數 | `list[AbstractCard]` | 讓指定玩家抽 N 張；牌堆空時重洗棄牌堆。 |
| `reshuffle_discard_pile()` | 無 | 無 | 保留頂牌，其餘棄牌洗回抽牌堆。 |
| `next_player()` | 無 | 無 | 依方向切到下一位，重設回合倒數，呼叫玩家 `start_turn()`。 |
| `get_current_player()` | 無 | `Player` | 回傳目前玩家。 |
| `check_winner()` | 無 | `Player` 或 `None` | 找第一個手牌為 0 的玩家。 |
| `get_rankings()` | 無 | `list[(Player, hand_size)]` | 依手牌數少到多排序。 |
| `skip_next_player()` | 無 | 無 | 將 index 先移到下一位；之後 `play_turn` 的 `next_player()` 會再移一次，達成跳過。 |
| `reverse_order()` | 無 | 無 | 切換順/逆時針。 |
| `add_draw_penalty(count)` | 張數 | 無 | 累加 draw penalty。 |
| `change_color(color)` | `CardColor` | 無 | 改目前顏色並清 current_number。 |
| `swap_hands(player1_index, player2_index)` | 兩位玩家 index | 無 | 交換兩位玩家手牌。 |
| `steal_card(from_player_index, to_player_index, card_index, return_card_index)` | 來源/目標/index | 無 | 從來源偷指定 index，再回送一張。 |
| `neighbor_swap()` | 無 | 無 | 每位玩家隨機抽出一張，傳給鄰近玩家。 |
| `target_draw_penalty(target_player_index, count)` | 目標 index、張數 | 無 | 指定玩家抽牌。 |
| `swap_hands_with_target(target_index)` | target index | 無 | 目前玩家與 target 交換手牌。 |
| `steal_and_return_card(target_index, return_card_index)` | target、return index | 無 | 目前玩家從 target 隨機偷一張，再還一張。 |
| `target_draw_cards(target_index, count)` | target、張數 | 無 | 呼叫 `target_draw_penalty`。 |
| `peek_top_cards(count)` | 張數 | `list[AbstractCard]` | 查看抽牌堆頂 N 張。 |
| `reorder_top_cards(new_order)` | index 排列 | 無 | 重新排列抽牌堆頂部。 |
| `get_current_color()` | 無 | `CardColor` | 回傳目前顏色。 |
| `find_top_function_card()` | 無 | card 或 `None` | 從抽牌堆頂往下找第一張非 number card。 |
| `add_to_discard_pile(card)` | card | 無 | 加入棄牌堆。 |
| `remove_from_deck(card)` | card | 無 | 從抽牌堆移除指定 card。 |
| `get_draw_penalty()` | 無 | `int` | 回傳累加抽牌張數。 |
| `check_timeout()` | 無 | `bool` | 檢查整局是否超過 15 分鐘。 |
| `get_remaining_time()` | 無 | `timedelta` 或 `None` | 回傳整局剩餘時間。 |
| `get_turn_remaining_time()` | 無 | `timedelta` 或 `None` | 回傳目前回合 30 秒剩餘時間。 |
| `force_end_game()` | 無 | `dict` | 15 分鐘 timeout 時強制結束並回 final rankings。 |
| `_can_play_card(card)` | card | `bool` | 核心可出牌判斷，包含 draw penalty 疊加規則。 |
| `_update_current_state(card, command)` | card、command | 無 | 出牌後更新 current_color/current_number。 |
| `_handle_player_won(winner)` | winner | `dict` | 記錄名次，若遊戲結束回 final rankings。 |

`play_turn()` 成功回傳常見欄位：

- `success`
- `card_played`
- `current_color`
- `current_number`
- `next_player`
- `draw_penalty`
- 若結束：`game_over`, `winner`, `winner_name`, `final_rankings`, `phase`

### `backend/game/engine/game_state.py`

用途：把 engine 轉成前端/紀錄使用的資料形狀。

#### `PlayerState`

欄位：

- `player_id`
- `name`
- `hand_size`
- `skill_code`
- `skill_name`
- `skill_used_count`
- `turn_count`
- `is_disconnected`
- `is_ai_replacement`
- `settlement_penalty`

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `to_dict()` | 無 | `dict` | dataclass 轉 dict。 |
| `from_player(player)` | player | `PlayerState` | 從 Player 建立公開狀態。 |

#### `GameState`

欄位包含：

- phase、turn_count、timestamp
- current_player_index、current_color、current_number、is_clockwise、draw_penalty
- deck/discard pile size/top
- players
- winners
- game_start_time、time_limit_seconds、remaining_seconds

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `to_dict()` | 無 | `dict` | dataclass 轉 dict。 |
| `from_engine(engine)` | `GameEngine` | `GameState` | 從 engine 建立前端全局狀態。 |

#### `PlayerHandState`

欄位：

- `player_id`
- `cards: list[str]`
- `playable_cards: list[int]`

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `to_dict()` | 無 | `dict` | dataclass 轉 dict。 |
| `from_player(player, current_color, current_number, draw_penalty=0)` | player、場色、場數字、penalty | `PlayerHandState` | 建立「該玩家自己的手牌與可出 index」。 |

#### `GameAction`

用途：遊戲動作紀錄資料。

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `to_dict()` | 無 | `dict` | dataclass 轉 dict。 |
| `create_play_card(action_id, player_id, card, **kwargs)` | id、玩家、牌、額外資訊 | `GameAction` | 建立出牌紀錄。 |
| `create_draw_card(action_id, player_id, count)` | id、玩家、張數 | `GameAction` | 建立抽牌紀錄。 |
| `create_use_skill(action_id, player_id, skill_name, **kwargs)` | id、玩家、技能名、額外資訊 | `GameAction` | 建立技能紀錄。 |
| `create_skip_turn(action_id, player_id, reason)` | id、玩家、原因 | `GameAction` | 建立跳過紀錄。 |

#### `GameHistory`

用途：保留動作與狀態歷史。目前不是主流程必要資料，偏預留。

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `__init__()` | 無 | instance | 初始化 actions/states/counter。 |
| `record_action(action)` | `GameAction` | 無 | 加入動作。 |
| `record_state(state)` | `GameState` | 無 | 加入狀態。 |
| `get_next_action_id()` | 無 | `int` | action counter +1。 |
| `to_dict()` | 無 | `dict` | 回傳 actions/states。 |
| `get_summary()` | 無 | `dict` | 回傳總動作、總回合、開始/結束時間、最終 phase。 |

### `backend/game/engine/skills.py`

用途：角色技能系統。

#### `SkillContext(Protocol)`

技能需要 engine 提供的方法：

- `peek_top_cards(count)`
- `reorder_top_cards(new_order)`
- `get_current_color()`
- `change_color(color)`
- `find_top_function_card()`
- `get_current_player()`
- `add_to_discard_pile(card)`
- `remove_from_deck(card)`
- `get_draw_penalty()`
- `next_player()`

#### `SkillBehavior`

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `__init__(name, description)` | 名稱、描述 | instance | 技能基底。 |
| `name` | property | `str` | 技能名稱。 |
| `description` | property | `str` | 技能描述。 |
| `can_use(turn_count, **kwargs)` | 回合數、條件 | `bool` | 抽象：判斷能否使用。 |
| `execute_skill(context, **kwargs)` | engine context、技能參數 | `dict` | 抽象：執行技能。 |
| `to_dict()` | 無 | `dict` | `{name, description}`。 |

#### 技能類別

| 類別 | can_use 條件 | execute_skill 參數 | 回傳/效果 |
| --- | --- | --- | --- |
| `SeerSkill` | `turn_count >= 2` 且每 2 回合一次 | `new_order` | 查看抽牌堆頂 4 張並依 `new_order` 重排；回 `cards_viewed`。 |
| `PainterSkill` | `turn_count >= 2` 且每 2 回合一次 | `new_color` | 改目前顏色；不能改成 black。 |
| `ScoutSkill` | 單局最多 3 次 | `discard_card` | 棄一張手牌，從抽牌堆找頂部功能牌加入手牌。 |
| `QueenSkill` | 單局最多 2 次，且目前有 draw penalty | 無 | 將抽牌懲罰交給下一位，呼叫 `context.next_player()`。 |

#### `SkillFactory`

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `create_skill(skill_type)` | `seer/painter/scout/queen` | `SkillBehavior` 或 `None` | 建立技能 instance。 |
| `get_all_skill_types()` | 無 | `list[str]` | 回傳所有 skill code。 |
| `get_skill_description(skill_type)` | skill code | `str` 或 `None` | 建立技能後取描述。 |
| `validate_skill_type(skill_type)` | skill code | `bool` | 是否為合法技能。 |

## Management Commands

### `backend/game/management/__init__.py`

用途：Django management package marker。

### `backend/game/management/commands/__init__.py`

用途：Django management commands package marker。

### `backend/game/management/commands/matchmaking_worker.py`

用途：背景掃描配對佇列。

執行：

```bash
python manage.py matchmaking_worker
python manage.py matchmaking_worker --once
python manage.py matchmaking_worker --interval 0.5
```

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `Command.add_arguments(parser)` | argparse parser | 無 | 加 `--interval`、`--once`。 |
| `Command.handle(*args, **options)` | Django options | 無 | 迴圈呼叫 `process_once()`，除非 `--once`。 |
| `Command.process_once()` | 無 | `int` | 找最舊等待 ticket，呼叫 `_try_complete_matchmaking(ticket.user)`；有處理回 1，沒有回 0。 |

### `backend/game/management/commands/seed_matchmaking_players.py`

用途：建立配對測試帳號。

執行：

```bash
python manage.py seed_matchmaking_players
python manage.py seed_matchmaking_players --password TestPass123!
```

| 方法 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `Command.add_arguments(parser)` | argparse parser | 無 | 加 `--password`。 |
| `Command.handle(*args, **options)` | Django options | 無 | 建立/更新 `mm_...` 測試帳號與 `PlayerProfile.total_score`。 |

## Templates

### `backend/game/templates/game_test.html`

用途：舊版後端 HTML 測試頁，透過 Django `game_test` view render。現在主要前端遊戲頁在 Vue，這個檔案比較像 WebSocket 手動測試工具。

## Migrations

### `backend/game/migrations/__init__.py`

用途：migration package marker。

### `0001_initial.py`

用途：建立初始資料表，例如 player profile、room/match 相關初始結構。

主要內容：

- `Migration` class：Django migration 定義。

### `0002_emailverificationcode.py`

用途：新增 email 驗證碼模型。

主要內容：

- `Migration` class。

### `0003_passwordresetcode.py`

用途：新增密碼重設碼模型。

主要內容：

- `Migration` class。

### `0004_alter_passwordresetcode_code.py`

用途：調整 password reset code 欄位。

主要內容：

- `Migration` class。

### `0005_rename_password_reset_code_token.py`

用途：將 password reset code 欄位改名為 token。

主要內容：

- `Migration` class。

### `0006_room_code_room_created_at_roommember.py`

用途：新增/調整 room code、created_at、RoomMember。

| 函式 | 參數 | 回傳 | 功能 |
| --- | --- | --- | --- |
| `populate_room_codes(apps, schema_editor)` | migration apps、schema editor | 無 | 為既有 room 補唯一 6 位 code。 |

主要內容：

- `Migration` class。

### `0007_rename_password_re_email_token_idx_password_re_email_c29bfe_idx.py`

用途：調整 password reset 相關 index 名稱。

主要內容：

- `Migration` class。

### `0008_matchmakingticket_roommember_ai.py`

用途：新增 matchmaking ticket 與 RoomMember AI 相關欄位。

主要內容：

- `Migration` class。

### `0009_rename_matchmaking_status_6f9e7d_idx_matchmaking_status_863774_idx.py`

用途：調整 matchmaking status index 名稱。

主要內容：

- `Migration` class。

## 後端串前端/引擎的重點

### 建議串接順序

1. 前端先用 HTTP API 登入，依靠 Django session cookie。
2. 建立/加入房間：`/api/rooms/create/` 或 `/api/rooms/join/`。
3. 大廳頁連 `/ws/rooms/<code>/` 等待 `room_update`。
4. 房主呼叫 `/api/rooms/<code>/start/`，必要時 `{"test_mode": true}`。
5. 前端進遊戲頁後連 `/ws/game/<code>/`。
6. 房主或遊戲頁送 `{ "action": "start_game", "test_mode": true/false }` 建立 `GameEngine`。
7. 遊戲中前端主要聽 `game_state`，並送 `play_card/draw_card/use_skill`。

### 出牌 payload

普通牌：

```json
{
  "action": "play_card",
  "card_index": 0
}
```

Wild / Wild Draw 4：

```json
{
  "action": "play_card",
  "card_index": 0,
  "chosen_color": "red"
}
```

Swap Hand / Target Draw 2：

```json
{
  "action": "play_card",
  "card_index": 0,
  "target_player_index": 2
}
```

Steal Card：

```json
{
  "action": "play_card",
  "card_index": 0,
  "target_player_index": 2,
  "return_card_index": 0
}
```

抽牌：

```json
{
  "action": "draw_card"
}
```

技能：

```json
{
  "action": "use_skill",
  "params": {
    "new_color": "blue"
  }
}
```

### `game_state` 結構重點

`state`：

- `phase`
- `current_player_index`
- `current_color`
- `current_number`
- `is_clockwise`
- `draw_penalty`
- `deck_size`
- `discard_pile_size`
- `discard_pile_top`
- `players`
- `winners`
- `remaining_seconds`

`hand`：

- `player_id`
- `cards`
- `playable_cards`
- `is_my_turn`

### Debug 頁需要的資料

前端 debug 頁可連：

```text
/ws/game/<room_code>/?debug=1
```

送：

```json
{"action": "debug_state"}
```

可取得：

- 全部玩家手牌
- 全部玩家可出牌 indexes
- 目前玩家
- 斷線/AI replacement/penalty flag
- 最近 100 筆事件

