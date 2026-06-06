<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';

const route = useRoute();
const WS_BASE = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`;
const roomId = ref(String(route.query.room || ''));
const connected = ref(false);
const debugState = ref(null);
const players = ref([]);
const events = ref([]);
const errorMessage = ref('');
let socket = null;
let pollId = null;

const discardPileCards = computed(() => debugState.value?.discard_pile || []);

const gameEndSummary = computed(() => {
  const result = debugState.value?.last_game_result;
  if (!result) {
    return '';
  }

  const reasonText = result.end_reason_text || result.end_reason || '未知原因';
  const winnerName = result.winner_name || (result.winner ? resolvePlayerName(result.winner) : '未知玩家');
  return `${winnerName}：${reasonText}`;
});

const currentSummary = computed(() => {
  const state = debugState.value;
  if (!state) {
    return '尚未取得遊戲狀態';
  }

  const current = players.value.find((player) => player.is_current);
  return `${current?.name || '未知玩家'} / ${state.current_color} / ${state.discard_pile_top || '無棄牌'}`;
});

function connectDebugSocket() {
  if (!roomId.value || socket) {
    return;
  }

  socket = new WebSocket(`${WS_BASE}/game/${roomId.value}/?debug=1`);

  socket.onopen = () => {
    connected.value = true;
    requestDebugState();
    pollId = window.setInterval(requestDebugState, 1000);
  };

  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'debug_state') {
      debugState.value = data.state;
      players.value = data.players || [];
      events.value = data.events || [];
      return;
    }

    if (data.type === 'error') {
      errorMessage.value = data.message;
    }
  };

  socket.onclose = (event) => {
    connected.value = false;
    socket = null;
    stopPolling();
    if (event.code === 4408) {
      errorMessage.value = '此帳號已超過重連時間，無法進入該局。';
    }
  };
}

function requestDebugState() {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    return;
  }
  socket.send(JSON.stringify({ action: 'debug_state' }));
}

function stopPolling() {
  if (pollId) {
    window.clearInterval(pollId);
    pollId = null;
  }
}

function closeSocket() {
  stopPolling();
  if (socket) {
    socket.close();
    socket = null;
  }
}

function formatPayload(payload) {
  return JSON.stringify(payload || {}, null, 2);
}

function resolvePlayerName(playerId) {
  if (playerId === null || playerId === undefined || playerId === '') {
    return '';
  }

  const player = players.value.find((candidate) => String(candidate.player_id) === String(playerId));
  return player?.name || `玩家 ${playerId}`;
}

function formatEventSummary(event) {
  const payload = event?.payload || {};
  const actorName = payload.player_name || resolvePlayerName(payload.player_id) || '未知玩家';
  const nextPlayerName = payload.next_player ? resolvePlayerName(payload.next_player) : '';

  if (event.type === 'card_played') {
    const cardName = payload.card_played || payload.card_name || '未知卡片';
    return nextPlayerName
      ? `${actorName} 出了 ${cardName}，下一位是 ${nextPlayerName}`
      : `${actorName} 出了 ${cardName}`;
  }

  if (event.type === 'card_drawn') {
    const count = payload.count ?? 1;
    return nextPlayerName
      ? `${actorName} 抽了 ${count} 張，下一位是 ${nextPlayerName}`
      : `${actorName} 抽了 ${count} 張`;
  }

  if (event.type === 'skill_used') {
    return nextPlayerName
      ? `${actorName} 使用技能，下一位是 ${nextPlayerName}`
      : `${actorName} 使用技能`;
  }

  if (event.type === 'game_ended') {
    const reasonText = payload.end_reason_text || payload.end_reason || '遊戲結束';
    const winnerName = payload.winner_name || resolvePlayerName(payload.winner) || '未知玩家';
    return `${winnerName} · ${reasonText}`;
  }

  return `${event.type || 'event'} 事件`;
}

onMounted(connectDebugSocket);
onBeforeUnmount(closeSocket);
</script>

<template>
  <main class="debug-page">
    <header class="debug-header">
      <div>
        <h1>Game Debug</h1>
        <p>Room {{ roomId || '未指定' }} · {{ connected ? 'connected' : 'disconnected' }}</p>
      </div>
      <strong>{{ gameEndSummary || currentSummary }}</strong>
    </header>

    <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>

      <section v-if="discardPileCards.length" class="panel discard-strip-panel">
        <div class="discard-strip-header">
          <h2>棄牌區</h2>
          <span>{{ discardPileCards.length }} 張</span>
        </div>
        <div class="discard-strip" aria-label="廢排區卡片歷史">
          <span
            v-for="(card, index) in discardPileCards"
            :key="`${card}-${index}`"
            class="discard-card-chip"
          >
            {{ card }}
          </span>
        </div>
      </section>

    <section class="state-grid">
      <article class="panel">
        <h2>State</h2>
        <dl v-if="debugState" class="state-list">
          <div><dt>Phase</dt><dd>{{ debugState.phase }}</dd></div>
          <div><dt>Turn</dt><dd>{{ debugState.turn_count }}</dd></div>
          <div><dt>Timer</dt><dd>{{ debugState.remaining_seconds }}s</dd></div>
          <div><dt>Color</dt><dd>{{ debugState.current_color }}</dd></div>
          <div><dt>Discard</dt><dd>{{ debugState.discard_pile_top }}</dd></div>
          <div><dt>Draw Penalty</dt><dd>{{ debugState.draw_penalty }}</dd></div>
          <div><dt>Direction</dt><dd>{{ debugState.is_clockwise ? 'clockwise' : 'counter' }}</dd></div>
        </dl>
      </article>

      <article v-for="player in players" :key="`${player.index}-${player.player_id}`" class="panel player-panel" :class="{ current: player.is_current }">
        <header class="player-header">
          <div>
            <h2>P{{ player.index + 1 }} {{ player.name }}</h2>
            <p>{{ player.player_id }} · {{ player.skill_name }}</p>
          </div>
          <span v-if="player.is_current" class="badge">CURRENT</span>
        </header>
        <p class="flags">
          <span v-if="player.is_ai">AI</span>
          <span v-if="player.is_ai_replacement">AI代打</span>
          <span v-if="player.is_disconnected">離線</span>
          <span v-if="player.settlement_penalty">結算處罰</span>
        </p>
        <div class="hand-list">
          <span
            v-for="(card, index) in player.hand"
            :key="`${card}-${index}`"
            class="card-chip"
            :class="{ playable: player.playable_cards.includes(index) }"
          >
            {{ index }}: {{ card }}
          </span>
        </div>
      </article>
    </section>

    <section class="panel event-panel">
      <h2>Events</h2>
      <div v-for="event in [...events].reverse()" :key="`${event.time}-${event.type}-${JSON.stringify(event.payload)}`" class="event-row">
        <strong>{{ event.time }} · {{ formatEventSummary(event) }}</strong>
        <pre>{{ formatPayload(event.payload) }}</pre>
      </div>
    </section>
  </main>
</template>

<style scoped>
.debug-page {
  min-height: 100vh;
  padding: 20px;
  color: #e5e7eb;
  background: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.debug-header,
.player-header {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 16px;
}

h1,
h2,
p {
  margin: 0;
}

.debug-header {
  margin-bottom: 16px;
}

.state-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 14px;
}

.discard-strip-panel {
  margin-bottom: 14px;
}

.discard-strip-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.discard-strip {
  display: flex;
  flex-direction: row-reverse;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.discard-card-chip {
  flex: 0 0 auto;
  padding: 8px 10px;
  border: 1px solid #475569;
  border-radius: 999px;
  background: #020617;
  color: #bfdbfe;
  font-size: 13px;
  white-space: nowrap;
}

.panel {
  padding: 14px;
  border: 1px solid #334155;
  border-radius: 8px;
  background: #111827;
}

.player-panel.current {
  border-color: #facc15;
  box-shadow: 0 0 0 2px rgba(250, 204, 21, 0.22);
}

.state-list {
  display: grid;
  gap: 8px;
}

.state-list div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.badge,
.flags span {
  display: inline-flex;
  padding: 3px 7px;
  border: 1px solid #64748b;
  border-radius: 999px;
  color: #f8fafc;
  font-size: 12px;
}

.flags {
  min-height: 24px;
  display: flex;
  gap: 6px;
  margin: 10px 0;
}

.hand-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.card-chip {
  padding: 6px 8px;
  border: 1px solid #475569;
  border-radius: 6px;
  background: #020617;
  font-size: 13px;
}

.card-chip.playable {
  border-color: #86efac;
  color: #bbf7d0;
}

.event-panel {
  margin-top: 14px;
}

.event-row {
  padding: 10px 0;
  border-top: 1px solid #334155;
}

pre {
  overflow: auto;
  margin: 8px 0 0;
  color: #bfdbfe;
  white-space: pre-wrap;
}

.error-message {
  margin-bottom: 12px;
  color: #fecaca;
}
</style>
