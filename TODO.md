# Game Backend Integration TODO

這份文件整理目前遊戲畫面已經預留的後端串接位置，以及建議後端需要提供的回傳格式。

## 目前狀態

- 遊戲畫面檔案：`frontend/src/views/GameBoardPage.vue`
- 目前手牌存在前端 Vue state：`playerCards`
- 目前牌組資料是 mock，不會存進資料庫
- 目前只有呼叫房間資料 API：`GET /api/rooms/current/`
- 出牌、抽牌、技能按鈕已經整理好 payload，但還沒有送到後端
- 後端目前主要有 auth、rooms、matchmaking，還沒有正式的 game state/card action endpoint

## 前端已保留的串接位置

### 1. 載入遊戲狀態

檔案位置：

```text
frontend/src/views/GameBoardPage.vue
```

目前函式：

```js
async function setupGameServerConnection() {
  try {
    const data = await request('/rooms/current/');
    if (data.room) {
      applyGameStatePayload({ room: data.room });
    }
  } catch (err) {
    console.error('Failed to load current room:', err);
  }

  // TODO: Connect the real game-state channel here when backend game flow is ready.
}
```

之後可以在這裡接：

- HTTP：`GET /api/rooms/<room_code>/game-state/`
- 或 WebSocket：`ws://localhost:8000/ws/games/<room_code>/`

### 2. 套用後端遊戲狀態

目前函式：

```js
function applyGameStatePayload(payload) {
  if (payload.player?.hand) {
    playerCards.value = [...payload.player.hand];
    selectedCardIndex.value = null;
  }
}
```

後端只要回傳 `player.hand`，前端就可以更新玩家手牌。

### 3. 送出玩家操作

目前函式：

```js
function submitGameAction(action, card = null) {
  const payload = {
    action,
    room_id: roomId.value,
    card_index: card?.index ?? null,
    card_name: card?.name ?? null,
  };

  // TODO: Send this payload to backend through WebSocket or an HTTP endpoint.
}
```

會由這三個操作呼叫：

- `play_card`
- `draw_card`
- `use_skill`

## 建議後端回傳格式

建議後端統一回傳完整 game state，前端可以直接丟給 `applyGameStatePayload(payload)`。

```json
{
  "type": "game_state",
  "room": {
    "code": "449102",
    "status": "Playing",
    "member_count": 4,
    "max_members": 4
  },
  "player": {
    "id": 1,
    "name": "Player 1",
    "hand": ["紅 2", "紅 +2", "藍 1", "藍 8"]
  },
  "opponents": {
    "top": {
      "id": 2,
      "name": "Player 2",
      "card_count": 5
    },
    "left": {
      "id": 3,
      "name": "Player 3",
      "card_count": 9
    },
    "right": {
      "id": 4,
      "name": "Player 4",
      "card_count": 10
    }
  },
  "discard": {
    "top_card": "綠 9"
  },
  "turn": {
    "current_player_id": 1,
    "current_player_name": "Player 1",
    "direction": "逆時針",
    "remaining_seconds": 30
  }
}
```

## 建議玩家操作 Payload

### 出牌

```json
{
  "action": "play_card",
  "room_id": "449102",
  "card_index": 2,
  "card_name": "藍 1"
}
```

### 抽牌

```json
{
  "action": "draw_card",
  "room_id": "449102",
  "card_index": null,
  "card_name": null
}
```

### 使用技能

```json
{
  "action": "use_skill",
  "room_id": "449102",
  "card_index": null,
  "card_name": null
}
```

## 建議 API 設計

### HTTP 版本

```text
GET  /api/rooms/<room_code>/game-state/
POST /api/rooms/<room_code>/actions/
```

`GET /game-state/` 回傳完整 game state。

`POST /actions/` 接收玩家操作，後端處理後回傳新的 game state。

### WebSocket 版本

```text
ws://localhost:8000/ws/games/<room_code>/
```

前端送出：

```json
{
  "action": "play_card",
  "room_id": "449102",
  "card_index": 2,
  "card_name": "藍 1"
}
```

後端廣播：

```json
{
  "type": "game_state",
  "room": {},
  "player": {},
  "opponents": {},
  "discard": {},
  "turn": {}
}
```

## 後端需要補的資料

建議後端至少要能保存：

- 房間目前狀態
- 玩家座位順序
- 每位玩家手牌
- 抽牌堆
- 棄牌堆
- 當前玩家
- 回合方向
- 當前顏色
- 遊戲是否結束

## 前端接上時要改的地方

1. 在 `setupGameServerConnection()` 裡取得真實 game state。
2. 把後端回傳資料傳進 `applyGameStatePayload(data)`。
3. 在 `submitGameAction()` 裡把 payload 送到後端。
4. 後端回傳或廣播新的 game state 後，再次呼叫 `applyGameStatePayload(data)`。
5. 移除或只保留測試用的 `simulateBackendDeckPayload()`。

