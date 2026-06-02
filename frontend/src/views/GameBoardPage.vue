<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';

const TURN_SECONDS = 30;
const API_BASE = `http://${window.location.hostname}:8000/api`;

const route = useRoute();
const roomId = ref(String(route.query.room || '449102'));
const roomTitle = ref('娛樂房・4人');
const isTestMode = computed(() => route.query.test === '1');
const selectedCardIndex = ref(null);
const remainingSeconds = ref(TURN_SECONDS);
let timerId = null;

const topCardCount = ref(6);
const leftCardCount = ref(7);
const rightCardCount = ref(8);
const currentDiscardCard = ref('黃 7');
const turnDirection = ref('順時針');
const playerCards = ref([
  '紅 1',
  '藍 3',
  '黃 5',
  '綠 7',
  '紅 9',
  '跳過',
  '藍 2',
  '反轉',
  '黃 8',
  '綠 4',
  '+2',
  '紅 6',
  '萬用',
  '藍 9',
]);

const selectedCard = computed(() => {
  if (selectedCardIndex.value === null) {
    return null;
  }

  return {
    index: selectedCardIndex.value,
    name: playerCards.value[selectedCardIndex.value],
  };
});

function displayCardLabel(cardName) {
  const colorMap = {
    紅: 'R',
    藍: 'B',
    黃: 'Y',
    綠: 'G',
  };
  const parts = String(cardName).trim().split(/\s+/);

  if (parts.length >= 2 && colorMap[parts[0]]) {
    return `${colorMap[parts[0]]}${parts.slice(1).join('')}`;
  }

  const specialMap = {
    跳過: 'SKIP',
    反轉: 'REV',
    萬用: 'WILD',
    抽四: '+4',
  };

  return specialMap[cardName] || cardName;
}


async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.error?.message || 'Request failed.');
  }

  return data;
}

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

function applyGameStatePayload(payload) {
  if (payload.room) {
    roomId.value = payload.room.code || roomId.value;
    const prefix = isTestMode.value ? '測試模式' : payload.room.status || '房間';
    const memberCount = payload.room.member_count ?? 1;
    const maxMembers = payload.room.max_members ?? 4;
    roomTitle.value = `${prefix}・${memberCount}/${maxMembers}人`;
  }

  if (payload.player?.hand) {
    playerCards.value = [...payload.player.hand];
    selectedCardIndex.value = null;
  }

  if (payload.opponents?.top?.card_count !== undefined) {
    topCardCount.value = payload.opponents.top.card_count;
  }

  if (payload.opponents?.left?.card_count !== undefined) {
    leftCardCount.value = payload.opponents.left.card_count;
  }

  if (payload.opponents?.right?.card_count !== undefined) {
    rightCardCount.value = payload.opponents.right.card_count;
  }

  if (payload.discard?.top_card) {
    currentDiscardCard.value = payload.discard.top_card;
  }

  if (payload.turn?.direction) {
    turnDirection.value = payload.turn.direction;
  }
}

function simulateBackendDeckPayload() {
  applyGameStatePayload({
    type: 'game_state',
    room: {
      code: roomId.value,
      status: 'Testing',
      member_count: 1,
      max_members: 4,
    },
    player: {
      hand: ['紅 2', '紅 +2', '藍 1', '藍 8', '黃 4', '黃 跳過', '綠 0', '綠 9', '反轉', '萬用', '抽四', '紅 7'],
    },
    opponents: {
      top: { card_count: 5 },
      left: { card_count: 9 },
      right: { card_count: 10 },
    },
    discard: {
      top_card: '綠 9',
    },
    turn: {
      direction: '逆時針',
    },
  });
}

function submitGameAction(action, card = null) {
  const payload = {
    action,
    room_id: roomId.value,
    card_index: card?.index ?? null,
    card_name: card?.name ?? null,
  };

  // TODO: Send this payload to backend through WebSocket or an HTTP endpoint.
  console.log('Prepared game action payload:', payload);

  selectedCardIndex.value = null;
  resetTurnTimer();
}

async function leaveRoom() {
  console.log('Prepared leave room payload:', {
    action: 'leave_room',
    room_id: roomId.value,
  });

  if (roomId.value) {
    await request(`/rooms/${roomId.value}/leave/`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
  }
}

async function handleExitRoom() {
  try {
    await Promise.race([
      leaveRoom(),
      new Promise((resolve) => {
        window.setTimeout(resolve, 1500);
      }),
    ]);
  } catch (err) {
    console.error('Failed to leave room:', err);
  } finally {
    window.location.assign('/lobby?left=1');
  }
}

function handleCardClick(index) {
  selectedCardIndex.value = index;
  console.log('Selected card:', {
    index,
    name: playerCards.value[index],
  });
}

function handlePlayButton() {
  if (!selectedCard.value) {
    return;
  }

  submitGameAction('play_card', selectedCard.value);
}

function handleDrawCard() {
  submitGameAction('draw_card');
}

function handleUseSkill() {
  submitGameAction('use_skill');
}

function resetTurnTimer() {
  remainingSeconds.value = TURN_SECONDS;
}

function startTurnTimer() {
  stopTurnTimer();
  timerId = window.setInterval(() => {
    remainingSeconds.value -= 1;

    if (remainingSeconds.value <= 0) {
      submitGameAction('draw_card');
    }
  }, 1000);
}

function stopTurnTimer() {
  if (timerId) {
    window.clearInterval(timerId);
    timerId = null;
  }
}

function playerCardStyle(index) {
  const count = Math.max(playerCards.value.length, 1);
  const center = (count - 1) / 2;
  const visibleCornerGap = 18;
  const maxRotation = Math.max(46, 84 - Math.max(0, count - 8) * 3);
  const minReadableStep = Math.max(4.8, 13 - Math.max(0, count - 8) * 0.7);
  const fullFanStep = count <= 1 ? 0 : (maxRotation * 2) / (count - 1);
  const step = count <= 1 ? 0 : Math.max(minReadableStep, Math.min(16, fullFanStep));
  const angle = (index - center) * step;
  const offset = (index - center) * visibleCornerGap;
  const edgeRatio = Math.abs(index - center) / Math.max(center, 1);
  const sideDrop = edgeRatio * 28;

  return {
    bottom: `${-sideDrop}px`,
    zIndex: index + 1,
    '--rotation': `${angle}deg`,
    '--fan-offset': `${offset}px`,
  };
}

onMounted(() => {
  setupGameServerConnection();
  startTurnTimer();
});

onBeforeUnmount(() => {
  stopTurnTimer();
});
</script>

<template>
  <main class="game-board-page">
    <div class="room-panel" aria-label="房間資訊">
      <div class="room-row">
        <span>房間ID：{{ roomId }}</span>
        <span class="signal-icon">)))</span>
      </div>
      <div class="room-row">{{ roomTitle }}</div>
    </div>

    <div class="top-tools" aria-label="遊戲工具">
      <button v-if="isTestMode" class="tool-btn mock-btn" type="button" @click="simulateBackendDeckPayload">
        <span class="tool-icon">▣</span>
        <span>模擬牌組</span>
      </button>
      <button class="tool-btn" type="button">
        <span class="tool-icon">⚙</span>
        <span>設定</span>
      </button>
      <button class="tool-btn" type="button" @click.stop="handleExitRoom">
        <span class="tool-icon">↪</span>
        <span>退出</span>
      </button>
    </div>

    <section class="opponent opponent-top" aria-label="用戶A">
      <div class="role-card">角色</div>
      <div class="opponent-name">用戶A</div>
      <div class="opponent-card-summary">
        <div class="game-card card-back">卡片</div>
        <span class="card-count-badge">{{ topCardCount }}</span>
      </div>
    </section>

    <section class="opponent opponent-left" aria-label="用戶D">
      <div class="role-card">角色</div>
      <div class="opponent-name">用戶D</div>
      <div class="opponent-card-summary">
        <div class="game-card side-summary-card">卡片</div>
        <span class="card-count-badge">{{ leftCardCount }}</span>
      </div>
    </section>

    <section class="opponent opponent-right" aria-label="用戶B">
      <div class="role-card">角色</div>
      <div class="opponent-name">用戶B</div>
      <div class="opponent-card-summary">
        <div class="game-card side-summary-card">卡片</div>
        <span class="card-count-badge">{{ rightCardCount }}</span>
      </div>
    </section>

    <section class="table-center" aria-label="牌桌中央">
      <div class="deck-stack" aria-label="抽牌堆">
        <div class="game-card deck-card">卡片</div>
      </div>

      <div class="discard-pile" aria-label="棄牌堆">
        <div class="game-card pile-card face-card">{{ displayCardLabel(currentDiscardCard) }}</div>
      </div>

      <div class="turn-panel">
        <div class="turn-row">
          <span>剩餘時間</span>
          <strong>{{ remainingSeconds }}</strong>
        </div>
        <div class="turn-row">
          <span>當前顏色</span>
          <span class="color-dot"></span>
        </div>
        <div class="turn-row">
          <span>當前玩家</span>
          <strong>你</strong>
        </div>
        <div class="turn-row">
          <span>方向</span>
          <strong>{{ turnDirection }}</strong>
        </div>
      </div>
    </section>

    <section class="player-area" aria-label="玩家手牌">
      <div class="player-info">
        <div class="role-card">角色</div>
        <div class="opponent-name">你（玩家）</div>
        <div class="card-count">{{ playerCards.length }}張</div>
      </div>
      <div class="player-hand">
        <button
          v-for="(card, index) in playerCards"
          :key="`${card}-${index}`"
          class="game-card player-card"
          :class="{ 'is-selected': selectedCardIndex === index }"
          :aria-pressed="selectedCardIndex === index"
          :data-selected="selectedCardIndex === index ? 'true' : 'false'"
          :style="playerCardStyle(index)"
          type="button"
          @click="handleCardClick(index)"
        >
          {{ displayCardLabel(card) }}
        </button>
      </div>
    </section>

    <aside class="action-panel" aria-label="玩家操作">
      <button class="action-btn" type="button" :disabled="!selectedCard" @click="handlePlayButton">
        出牌
      </button>
      <button class="action-btn" type="button" @click="handleDrawCard">抽牌</button>
      <button class="action-btn" type="button" @click="handleUseSkill">技能</button>
    </aside>
  </main>
</template>

<style scoped>
.game-board-page {
  --card-width: 64px;
  --card-height: 96px;
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  color: #f8fafc;
  background:
    radial-gradient(circle at 10% 20%, rgba(255, 255, 255, 0.75) 0 1px, transparent 2px),
    radial-gradient(circle at 28% 62%, rgba(255, 255, 255, 0.55) 0 1px, transparent 2px),
    radial-gradient(circle at 72% 24%, rgba(255, 255, 255, 0.7) 0 1px, transparent 2px),
    radial-gradient(circle at 91% 76%, rgba(255, 255, 255, 0.55) 0 1px, transparent 2px),
    #080312;
  background-size: 90px 90px, 130px 130px, 110px 110px, 150px 150px, auto;
  font-family: "Microsoft JhengHei", "PingFang TC", system-ui, sans-serif;
}

.room-panel,
.top-tools,
.opponent,
.table-center,
.player-area,
.action-panel {
  position: absolute;
  z-index: 1;
}

.room-panel {
  top: 18px;
  left: 18px;
  width: 202px;
  display: grid;
  gap: 8px;
}

.room-row {
  min-height: 38px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
  border: 1px solid rgba(248, 250, 252, 0.88);
  border-radius: 8px;
  background: rgba(5, 2, 16, 0.72);
  font-size: 15px;
}

.signal-icon {
  font-weight: 700;
  transform: rotate(-18deg);
}

.top-tools {
  top: 20px;
  right: 24px;
  display: flex;
  gap: 12px;
}

.tool-btn,
.action-btn,
.player-card {
  cursor: pointer;
}

.tool-btn {
  width: 66px;
  height: 70px;
  display: grid;
  place-items: center;
  gap: 2px;
  border: 1px solid rgba(248, 250, 252, 0.9);
  border-radius: 8px;
  color: inherit;
  background: rgba(5, 2, 16, 0.68);
  font-size: 13px;
}

.mock-btn {
  width: 78px;
}

.tool-icon {
  font-size: 24px;
  line-height: 1;
}

.opponent {
  display: grid;
  justify-items: center;
  gap: 5px;
}

.opponent-top {
  top: 30px;
  left: 50%;
  transform: translateX(-50%);
  grid-template-columns: 80px auto;
  grid-template-rows: repeat(3, auto);
  column-gap: 26px;
  align-items: start;
}

.opponent-top .role-card {
  grid-row: 1 / 4;
}

.opponent-left {
  top: 136px;
  left: 20px;
}

.opponent-right {
  top: 136px;
  right: 20px;
}

.role-card {
  width: 68px;
  height: 68px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(248, 250, 252, 0.94);
  border-radius: 8px;
  background: rgba(5, 2, 16, 0.72);
  font-size: 18px;
}

.opponent-name,
.card-count {
  font-size: 15px;
  line-height: 1.2;
}

.opponent-card-summary {
  position: relative;
  width: max-content;
}

.card-count-badge {
  position: absolute;
  top: -10px;
  right: -12px;
  min-width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  padding: 0 6px;
  border: 1px solid rgba(248, 250, 252, 0.95);
  border-radius: 999px;
  color: #080312;
  background: #f8fafc;
  font-size: 15px;
  font-weight: 800;
}

.game-card {
  width: var(--card-width);
  height: var(--card-height);
  display: grid;
  place-items: center;
  border: 1px solid rgba(248, 250, 252, 0.92);
  border-radius: 7px;
  color: #f8fafc;
  background: rgba(5, 2, 16, 0.72);
  font-size: 15px;
  text-align: center;
}

.side-summary-card {
  width: var(--card-width);
  height: var(--card-height);
}

.table-center {
  top: 28%;
  left: 50%;
  width: 360px;
  height: 320px;
  transform: translateX(-50%);
}

.deck-stack {
  position: absolute;
  top: 2px;
  left: calc(50% - 112px);
}

.deck-card::before,
.deck-card::after {
  content: "";
  position: absolute;
  width: var(--card-width);
  height: var(--card-height);
  border: 1px solid rgba(248, 250, 252, 0.72);
  border-radius: 7px;
  background: rgba(5, 2, 16, 0.72);
}

.deck-card {
  position: relative;
  width: var(--card-width);
  height: var(--card-height);
}

.deck-card::before {
  left: -4px;
  top: 4px;
}

.deck-card::after {
  left: -7px;
  top: 8px;
}

.discard-pile {
  position: absolute;
  top: 8px;
  left: calc(50% + 48px);
  width: 86px;
  height: 108px;
}

.pile-card {
  width: var(--card-width);
  height: var(--card-height);
  font-weight: 800;
}

.turn-panel {
  position: absolute;
  left: 50%;
  bottom: 6px;
  width: 210px;
  transform: translateX(-50%);
  padding: 12px 14px;
  border: 1px solid rgba(248, 250, 252, 0.92);
  border-radius: 8px;
  background: rgba(5, 2, 16, 0.74);
}

.turn-row {
  min-height: 30px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(248, 250, 252, 0.35);
  font-size: 16px;
}

.turn-row:last-child {
  border-bottom: 0;
}

.turn-row strong {
  font-size: 20px;
}

.color-dot {
  width: 20px;
  height: 20px;
  border: 1px solid rgba(248, 250, 252, 0.92);
  border-radius: 50%;
}

.player-area {
  left: 50%;
  width: min(920px, calc(100vw - 300px));
  height: 178px;
  transform: translateX(-50%);
  bottom: 98px;
  display: block;
}

.player-info {
  position: absolute;
  left: 0;
  bottom: 0;
  display: grid;
  justify-items: center;
  gap: 6px;
}

.player-hand {
  position: relative;
  height: 168px;
}

.player-card {
  position: absolute;
  left: 50%;
  bottom: 0;
  width: var(--card-width);
  min-width: var(--card-width);
  padding: 0 4px;
  transform: translateX(calc(-50% + var(--fan-offset))) rotate(var(--rotation));
  transform-origin: center 140%;
  transition: background 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.face-card,
.player-card {
  align-items: start;
  justify-items: start;
  padding: 8px 0 0 8px;
  font-size: 16px;
  font-weight: 800;
  line-height: 1;
}

.player-card.is-selected {
  border-color: #fde68a;
  background: rgba(30, 64, 175, 0.95);
  box-shadow: 0 0 0 3px rgba(253, 230, 138, 0.95), 0 14px 26px rgba(0, 0, 0, 0.42);
  transform: translateX(calc(-50% + var(--fan-offset))) rotate(var(--rotation)) translateY(-30px) scale(1.04);
}

.action-panel {
  right: 20px;
  bottom: 60px;
  width: 160px;
  display: grid;
  gap: 14px;
}

.action-btn {
  height: 52px;
  border: 1px solid rgba(248, 250, 252, 0.92);
  border-radius: 8px;
  color: #f8fafc;
  background: rgba(5, 2, 16, 0.72);
  font-size: 18px;
}

.action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.tool-btn:hover,
.action-btn:hover:not(:disabled),
.player-card:hover {
  background: rgba(38, 28, 66, 0.9);
}

.player-card.is-selected:hover {
  background: rgba(30, 64, 175, 0.95);
}

@media (max-width: 900px) {
  .game-board-page {
    min-height: 760px;
  }

  .room-panel {
    width: 180px;
  }

  .opponent-top {
    top: 112px;
  }

  .opponent-left,
  .opponent-right {
    display: none;
  }

  .table-center {
    top: 280px;
  }

  .player-area {
    width: calc(100vw - 28px);
    grid-template-columns: 72px 1fr;
    bottom: 110px;
  }

  .action-panel {
    left: 14px;
    right: 14px;
    bottom: 24px;
    width: auto;
    grid-template-columns: repeat(3, 1fr);
  }
}
</style>
