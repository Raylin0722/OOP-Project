<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import cardBackUrl from '../assets/source/card-back.png';
import gameRoomUrl from '../assets/pictures/game_room.png';
import roleFortuneTellerUrl from '../assets/pictures/c1_fortune_teller.png';
import roleWizardUrl from '../assets/pictures/c2_wizard.png';
import roleScoutUrl from '../assets/pictures/c3_scout.png';
import roleQueenUrl from '../assets/pictures/c4_queen.png';

const TURN_SECONDS = 30;
const API_BASE = `http://${window.location.hostname}:8000/api`;
const cardImages = import.meta.glob('../assets/pictures/[rbgyf]*.png', { eager: true, import: 'default' });
const gameRoomBackground = `url("${gameRoomUrl}")`;

const route = useRoute();
const roomId = ref(String(route.query.room || '449102'));
const roomTitle = ref('娛樂房・4人');
const isTestMode = computed(() => route.query.test === '1');
const selectedCardIndex = ref(null);
const remainingSeconds = ref(TURN_SECONDS);
const showSettingsModal = ref(false);
const boardScale = ref(1);
let timerId = null;

const topCardCount = ref(6);
const leftCardCount = ref(7);
const rightCardCount = ref(8);
const currentDiscardCard = ref('黃 7');
const currentColor = ref('黃');
const turnDirection = ref('順時針');
const playerCards = ref([
  '紅 1',
  '藍 3',
  '黃 5',
  '綠 7',
  '紅 9',
  '紅 跳過',
  '藍 2',
  '藍 反轉',
  '黃 8',
  '綠 4',
  '綠 +2',
  '紅 6',
  '萬用',
  '藍 9',
]);
const roleCards = {
  player: { name: '占卜師', image: roleFortuneTellerUrl },
  top: { name: '魔法師', image: roleWizardUrl },
  left: { name: '皇后', image: roleQueenUrl },
  right: { name: '偵查者', image: roleScoutUrl },
};

const selectedCard = computed(() => {
  if (selectedCardIndex.value === null) {
    return null;
  }

  return {
    index: selectedCardIndex.value,
    name: playerCards.value[selectedCardIndex.value],
  };
});

const currentColorStyle = computed(() => {
  const colorMap = {
    紅: '#dc2626',
    藍: '#2563eb',
    黃: '#facc15',
    綠: '#16a34a',
  };

  return {
    backgroundColor: colorMap[currentColor.value] || '#f8fafc',
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

function colorFromCard(cardName) {
  const color = String(cardName).trim().split(/\s+/)[0];
  return ['紅', '藍', '黃', '綠'].includes(color) ? color : currentColor.value;
}

function imageStyle(imageUrl) {
  return {
    '--image-url': `url("${imageUrl}")`,
  };
}

function cardAssetUrl(cardName) {
  const colorMap = {
    紅: 'r',
    藍: 'b',
    黃: 'y',
    綠: 'g',
  };
  const actionMap = {
    跳過: 'skip',
    反轉: 'reverse',
    '+2': '+2',
  };
  const normalized = String(cardName).trim();

  if (normalized === '萬用') {
    return cardImages['../assets/pictures/f_change_color.png'];
  }

  if (normalized === '抽四') {
    return cardImages['../assets/pictures/f_change_color+4.png'];
  }

  const parts = normalized.split(/\s+/);
  if (parts.length >= 2 && colorMap[parts[0]]) {
    const value = parts.slice(1).join('');
    const colorPrefix = colorMap[parts[0]];
    const filename = actionMap[value] ? `${colorPrefix}_${actionMap[value]}` : `${colorPrefix}${value}`;
    return cardImages[`../assets/pictures/${filename}.png`];
  }

  if (actionMap[normalized]) {
    return cardImages[`../assets/pictures/f_${actionMap[normalized]}.png`];
  }

  return null;
}

function cardImageStyle(cardName) {
  const imageUrl = cardAssetUrl(cardName);
  return imageUrl ? imageStyle(imageUrl) : {};
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
    currentColor.value = colorFromCard(payload.discard.top_card);
  }

  if (payload.turn?.direction) {
    turnDirection.value = payload.turn.direction;
  }

  if (payload.turn?.color || payload.turn?.current_color) {
    currentColor.value = payload.turn.color || payload.turn.current_color;
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
      hand: ['紅 2', '紅 +2', '藍 1', '藍 8', '黃 4', '黃 跳過', '綠 0', '綠 9', '黃 反轉', '萬用', '抽四', '紅 7'],
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
      color: '綠',
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
    <div class="game-board-stage">
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
      <div class="role-panel">
        <div class="role-card image-fill" :style="imageStyle(roleCards.top.image)" aria-label="角色"></div>
        <strong class="role-name">{{ roleCards.top.name }}</strong>
      </div>
      <div class="opponent-name">用戶A</div>
      <div class="opponent-card-summary">
        <div class="game-card card-back image-fill" :style="imageStyle(cardBackUrl)" aria-label="卡背"></div>
        <span class="card-count-badge">{{ topCardCount }}</span>
      </div>
    </section>

    <section class="opponent opponent-left" aria-label="用戶D">
      <div class="role-panel">
        <div class="role-card image-fill" :style="imageStyle(roleCards.left.image)" aria-label="角色"></div>
        <strong class="role-name">{{ roleCards.left.name }}</strong>
      </div>
      <div class="opponent-name">用戶D</div>
      <div class="opponent-card-summary">
        <div class="game-card side-summary-card side-card-horizontal image-fill" :style="imageStyle(cardBackUrl)" aria-label="卡背"></div>
        <span class="card-count-badge">{{ leftCardCount }}</span>
      </div>
    </section>

    <section class="opponent opponent-right" aria-label="用戶B">
      <div class="role-panel">
        <div class="role-card image-fill" :style="imageStyle(roleCards.right.image)" aria-label="角色"></div>
        <strong class="role-name">{{ roleCards.right.name }}</strong>
      </div>
      <div class="opponent-name">用戶B</div>
      <div class="opponent-card-summary">
        <div class="game-card side-summary-card side-card-horizontal image-fill" :style="imageStyle(cardBackUrl)" aria-label="卡背"></div>
        <span class="card-count-badge">{{ rightCardCount }}</span>
      </div>
    </section>

    <section class="table-center" aria-label="牌桌中央">
      <div class="deck-stack" aria-label="抽牌堆">
        <div class="game-card deck-card image-fill" :style="imageStyle(cardBackUrl)" aria-label="抽牌堆"></div>
      </div>

      <div class="discard-pile" aria-label="棄牌堆">
        <div
          class="game-card pile-card face-card"
          :class="{ 'image-fill': cardAssetUrl(currentDiscardCard) }"
          :style="cardImageStyle(currentDiscardCard)"
        >
          <span class="card-label">{{ displayCardLabel(currentDiscardCard) }}</span>
        </div>
      </div>

      <div class="turn-panel">
        <div class="turn-row">
          <span>剩餘時間</span>
          <strong>{{ remainingSeconds }}</strong>
        </div>
        <div class="turn-row">
          <span>當前顏色</span>
          <strong class="current-color">
            <span class="color-dot" :style="currentColorStyle"></span>
            {{ currentColor }}
          </strong>
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
        <div class="role-panel">
          <div class="role-card image-fill" :style="imageStyle(roleCards.player.image)" aria-label="角色"></div>
          <strong class="role-name">{{ roleCards.player.name }}</strong>
        </div>
        <div class="opponent-name">你（玩家）</div>
        <div class="card-count">{{ playerCards.length }}張</div>
      </div>
      <div class="player-hand">
        <button
          v-for="(card, index) in playerCards"
          :key="`${card}-${index}`"
          class="game-card player-card"
          :class="{ 'is-selected': selectedCardIndex === index, 'image-fill': cardAssetUrl(card) }"
          :aria-pressed="selectedCardIndex === index"
          :data-selected="selectedCardIndex === index ? 'true' : 'false'"
          :style="{ ...playerCardStyle(index), ...cardImageStyle(card) }"
          type="button"
          @click="handleCardClick(index)"
        >
          <span class="card-label">{{ displayCardLabel(card) }}</span>
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
    </div>

    <div v-if="showSettingsModal" class="settings-backdrop" @click.self="showSettingsModal = false">
      <section class="settings-modal" aria-label="設定">
        <header class="settings-header">
          <h2>設定</h2>
          <button class="settings-close" type="button" @click="showSettingsModal = false">×</button>
        </header>

        <label class="scale-field">
          <span>縮放比例</span>
          <input v-model.number="boardScale" type="number" min="0.5" max="1.4" step="0.05" />
        </label>

        <input v-model.number="boardScale" class="scale-slider" type="range" min="0.5" max="1.4" step="0.05" />
      </section>
    </div>
  </main>
</template>

<style scoped>
.game-board-page {
  --card-width: 64px;
  --card-height: 96px;
  position: relative;
  width: 100vw;
  height: 100vh;
  min-height: 100vh;
  overflow: hidden;
}

.game-board-stage {
  display: contents;
}

.game-board-page {
  --card-width: 84px;
  --card-height: calc(var(--card-width) * 7 / 5);
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  color: #f8fafc;
  background:
    linear-gradient(rgba(8, 3, 18, 0.12), rgba(8, 3, 18, 0.34)),
    v-bind(gameRoomBackground);
  background-position: center;
  background-size: cover;
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
  grid-template-columns: 132px auto;
  grid-template-rows: repeat(3, auto);
  column-gap: 18px;
  align-items: start;
}

.opponent-top .role-panel {
  grid-row: 1 / 4;
}

.opponent-left {
  top: 124px;
  left: 20px;
}

.opponent-right {
  top: 124px;
  right: 20px;
}

.role-panel {
  display: grid;
  justify-items: center;
  gap: 6px;
}

.role-card {
  width: 110px;
  height: calc(110px * 1771 / 1271);
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 0;
  background: transparent;
  font-size: 18px;
}

.image-fill {
  overflow: hidden;
  color: transparent;
  background-image: var(--image-url);
  background-position: center;
  background-size: cover;
  background-repeat: no-repeat;
  text-shadow: none;
}

.role-card.image-fill {
  background-size: contain;
  background-color: transparent;
}

.role-name {
  min-width: 76px;
  max-width: 116px;
  padding: 4px 8px;
  border: 1px solid rgba(248, 250, 252, 0.86);
  border-radius: 8px;
  color: #f8fafc;
  background: rgba(5, 2, 16, 0.78);
  font-size: 14px;
  line-height: 1.2;
  text-align: center;
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

.opponent-left .opponent-card-summary,
.opponent-right .opponent-card-summary {
  height: var(--card-height);
  display: grid;
  place-items: center;
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
  background-color: rgba(5, 2, 16, 0.72);
  font-size: 15px;
  text-align: center;
}

.side-summary-card {
  width: var(--card-width);
  height: var(--card-height);
}

.side-card-horizontal {
  width: var(--card-height);
  height: var(--card-width);
}

.side-card-horizontal + .card-count-badge {
  top: -12px;
  right: -14px;
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

.deck-card {
  position: relative;
  width: var(--card-width);
  height: var(--card-height);
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

.current-color {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
}

.player-area {
  left: 50%;
  width: 920px;
  height: 198px;
  transform: translateX(-50%);
  bottom: 88px;
  display: block;
}

.player-info {
  position: absolute;
  left: 0;
  bottom: -18px;
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

.face-card.image-fill,
.player-card.image-fill {
  align-items: stretch;
  justify-items: stretch;
  padding: 0;
}

.card-label {
  color: inherit;
}

.image-fill .card-label {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.player-card.is-selected {
  border-color: #fde68a;
  background-color: rgba(30, 64, 175, 0.95);
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
  background-color: rgba(38, 28, 66, 0.9);
}

.player-card.is-selected:hover {
  background-color: rgba(30, 64, 175, 0.95);
}

.settings-backdrop {
  position: fixed;
  inset: 0;
  z-index: 20;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.42);
}

.settings-modal {
  width: min(340px, calc(100vw - 32px));
  display: grid;
  gap: 18px;
  padding: 18px;
  border: 1px solid rgba(248, 250, 252, 0.8);
  border-radius: 8px;
  color: #f8fafc;
  background: rgba(8, 3, 18, 0.96);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
}

.settings-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.settings-header h2 {
  margin: 0;
  font-size: 20px;
}

.settings-close {
  width: 32px;
  height: 32px;
  border: 1px solid rgba(248, 250, 252, 0.7);
  border-radius: 8px;
  color: #f8fafc;
  background: transparent;
  cursor: pointer;
  font-size: 22px;
  line-height: 1;
}

.scale-field {
  display: grid;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
}

.scale-field input {
  height: 38px;
  padding: 0 10px;
  border: 1px solid rgba(248, 250, 252, 0.72);
  border-radius: 8px;
  color: #f8fafc;
  background: rgba(255, 255, 255, 0.08);
  font-size: 16px;
}

.scale-slider {
  width: 100%;
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
    grid-template-columns: 108px 1fr;
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
