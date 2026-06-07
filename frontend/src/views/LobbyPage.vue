<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import PlayerInfoCard from '../components/PlayerInfoCard.vue';
import PlayerStatsPanel from '../components/PlayerStatsPanel.vue';
import LobbyActionButtons from '../components/LobbyActionButtons.vue';
import hallImage from '../assets/pictures/hall.png';

const API_BASE = '/api';
const WS_PROTOCOL = window.location.protocol === 'https:' ? 'wss' : 'ws';
const WS_BASE = `${WS_PROTOCOL}://${window.location.host}/ws`;
const router = useRouter();
const route = useRoute();

const currentUser = ref(null);
const currentRoom = ref(null);
const joinCode = ref('');
const createRoomIsPublic = ref(false);
const publicRooms = ref([]);
const publicRoomsLoading = ref(false);
const publicRoomsError = ref('');
const loading = ref(false);
const roomBusy = ref(false);
const errorMessage = ref('');
const showStatsPanel = ref(false);
const matchmakingTicket = ref(null);
const matchmakingTick = ref(0);
let roomSocket = null;
let matchmakingSocket = null;
let lobbyPollId = null;
let publicRoomsPollId = null;
let matchmakingTimerId = null;
let matchmakingStatusPollId = null;
let matchmakingReconnectTimerId = null;

const currentMember = computed(() => {
  if (!currentUser.value || !currentRoom.value) {
    return null;
  }

  return currentRoom.value.members.find((member) => member.user.id === currentUser.value.id) || null;
});

const seats = computed(() => {
  const members = currentRoom.value?.members || [];
  const emptySeats = Array.from({ length: Math.max(0, 4 - members.length) }, (_, index) => ({
    empty: true,
    id: `empty-${index}`,
  }));

  return [...members, ...emptySeats];
});

const isMatchmaking = computed(() => Boolean(matchmakingTicket.value));
const matchmakingStatusText = computed(() => {
  if (!matchmakingTicket.value) {
    return '';
  }

  const waitedFor = getMatchmakingWaitedSeconds();
  const timeout = matchmakingTicket.value.timeout_seconds ?? 30;
  const scoreWindow = matchmakingTicket.value.score_window ?? 0;
  return `配對中：已等待 ${waitedFor}/${timeout} 秒，分數範圍 ±${scoreWindow}`;
});

const roomStartLabel = computed(() => {
  if (currentRoom.value?.is_matchmaking) {
    return '配對中';
  }

  return (currentRoom.value?.member_count ?? 0) >= 4
    ? '開始遊戲'
    : '開始配對';
});

function handleUnauthorized() {
  currentUser.value = null;
  currentRoom.value = null;
  localStorage.removeItem('authToken');
  stopLobbyPolling();
  stopPublicRoomsPolling();
  stopMatchmakingTimer();
  stopMatchmakingStatusPolling();
  closeRoomSocket();
  closeMatchmakingSocket();

  router.push({
    path: '/auth',
    query: { reason: 'login_required' },
  });
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

  if (response.status === 401) {
    handleUnauthorized();
    throw new Error(data.error?.message || '請先登入。');
  }

  if (!response.ok) {
    throw new Error(data.error?.message || 'Request failed.');
  }

  return data;
}

function setRoom(room) {
  currentRoom.value = room;

  if (room?.code) {
    connectRoomSocket(room.code);
  } else {
    closeRoomSocket();
  }
}

function closeRoomSocket() {
  if (roomSocket) {
    roomSocket.close();
    roomSocket = null;
  }
}

function closeMatchmakingSocket() {
  if (matchmakingReconnectTimerId) {
    window.clearTimeout(matchmakingReconnectTimerId);
    matchmakingReconnectTimerId = null;
  }

  if (matchmakingSocket) {
    matchmakingSocket.close();
    matchmakingSocket = null;
  }
}

function setMatchmakingTicket(ticket) {
  if (!ticket) {
    matchmakingTicket.value = null;
    stopMatchmakingTimer();
    stopMatchmakingStatusPolling();
    return;
  }

  matchmakingTicket.value = {
    ...ticket,
  };

  startMatchmakingTimer();
  startMatchmakingStatusPolling();
}

function getMatchmakingWaitedSeconds() {
  matchmakingTick.value;

  const ticket = matchmakingTicket.value;
  if (!ticket) {
    return 0;
  }

  if (ticket.started_at) {
    const startedAt = new Date(ticket.started_at).getTime();

    if (!Number.isNaN(startedAt)) {
      return Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    }
  }

  return Math.max(0, Number(ticket.waited_for ?? 0));
}
function startMatchmakingTimer() {
  if (matchmakingTimerId) {
    return;
  }

  matchmakingTimerId = window.setInterval(() => {
    matchmakingTick.value = Date.now();
    console.log('[matchmaking timer]', matchmakingTick.value);
  }, 1000);
}

function stopMatchmakingTimer() {
  if (matchmakingTimerId) {
    window.clearInterval(matchmakingTimerId);
    matchmakingTimerId = null;
  }
}

function startMatchmakingStatusPolling() {
  if (matchmakingStatusPollId) {
    return;
  }

  // WebSocket 是主要通知方式；這個 polling 只做保險同步，避免漏掉 matched 事件時卡在等待畫面。
  matchmakingStatusPollId = window.setInterval(async () => {
    if (!matchmakingTicket.value) {
      stopMatchmakingStatusPolling();
      return;
    }

    try {
      await loadMatchmakingStatus();
    } catch (err) {
      console.error('[matchmaking] failed to sync status:', err);
    }
  }, 2000);
}

function stopMatchmakingStatusPolling() {
  if (matchmakingStatusPollId) {
    window.clearInterval(matchmakingStatusPollId);
    matchmakingStatusPollId = null;
  }
}

function normalizeMatchmakingMessage(rawData) {
  if (!rawData || typeof rawData !== 'object') {
    return {};
  }

  // 後端可能送：
  // 1. { type: 'matched', room: {...} }
  // 2. { type: 'matchmaking_updated', payload: { type: 'matched', room: {...} } }
  // 3. { type: 'matchmaking.update', payload: { type: 'matched', room: {...} } }
  // 這裡統一攤平成前端好處理的格式。
  const payload = rawData.payload && typeof rawData.payload === 'object'
    ? rawData.payload
    : null;

  if (payload) {
    return {
      ...payload,
      ws_type: rawData.type,
    };
  }

  return rawData;
}

function handleMatchmakingMessage(rawData) {
  const data = normalizeMatchmakingMessage(rawData);
  console.log('[matchmaking-ws] message:', data);

  if (data.type === 'matched' && data.room) {
    setMatchmakingTicket(null);
    setRoom(data.room);
    loadPublicRooms();
    handlePlayingRoomNavigation(data.room, Boolean(data.room.test_mode), {
      forceEnter: true,
    });
    return;
  }

  if (data.type === 'waiting' || data.ticket) {
    if (data.ticket) {
      setMatchmakingTicket(data.ticket);
    }

    if (data.room) {
      setRoom(data.room);
    }

    return;
  }

  if (data.room) {
    setRoom(data.room);

    if (data.room.status === 'Playing') {
      setMatchmakingTicket(null);
      handlePlayingRoomNavigation(data.room, Boolean(data.room.test_mode), {
        forceEnter: true,
      });
    }

    return;
  }

  if (data.type === 'cancelled' || data.type === 'idle') {
    setMatchmakingTicket(null);
  }
}

function connectMatchmakingSocket() {
  if (
    matchmakingSocket
    && [WebSocket.OPEN, WebSocket.CONNECTING].includes(matchmakingSocket.readyState)
  ) {
    return;
  }

  if (matchmakingReconnectTimerId) {
    window.clearTimeout(matchmakingReconnectTimerId);
    matchmakingReconnectTimerId = null;
  }

  matchmakingSocket = new WebSocket(`${WS_BASE}/matchmaking/`);

  matchmakingSocket.onopen = () => {
    console.log('[matchmaking-ws] connected');
  };

  matchmakingSocket.onmessage = (event) => {
    try {
      handleMatchmakingMessage(JSON.parse(event.data));
    } catch (err) {
      console.error('[matchmaking-ws] invalid message:', event.data, err);
    }
  };

  matchmakingSocket.onerror = (error) => {
    console.error('[matchmaking-ws] error:', error);
  };

  matchmakingSocket.onclose = () => {
    console.log('[matchmaking-ws] closed');
    matchmakingSocket = null;

    // 配對中如果 socket 意外斷線，自動重連，避免錯過後端 matched 事件。
    if (matchmakingTicket.value && !matchmakingReconnectTimerId) {
      matchmakingReconnectTimerId = window.setTimeout(() => {
        matchmakingReconnectTimerId = null;
        connectMatchmakingSocket();
      }, 1000);
    }
  };
}

function goToGameRoom(room, testMode = false) {
  if (!room?.code) {
    return;
  }

  router.push({
    path: '/game-ui',
    query: {
      room: room.code,
      ...(testMode ? { test: '1' } : {}),
    },
  });
}

function shouldStayInLobbyAfterLeavingGame() {
  return route.query.left === '1';
}

function clearLeaveGameQuery() {
  if (route.query.left !== '1') {
    return;
  }

  const { left, ...nextQuery } = route.query;
  router.replace({
    path: route.path,
    query: nextQuery,
  });
}

function handlePlayingRoomNavigation(room, testMode = false, options = {}) {
  if (room?.status !== 'Playing') {
    return;
  }

  if (room.game_status?.reconnect_blocked) {
    errorMessage.value = room.game_status.reason || '此局已由 AI 代打，需等本局結束才能開始新遊戲。';
    return;
  }

  if (shouldStayInLobbyAfterLeavingGame()) {
    return;
  }

  const shouldAutoEnter = options.forceEnter || !shouldStayInLobbyAfterLeavingGame();
  if (shouldAutoEnter && room.game_status?.auto_enter !== false) {
    goToGameRoom(room, testMode || Boolean(room.test_mode));
  }
}

function connectRoomSocket(code) {
  if (roomSocket?.roomCode === code) {
    return;
  }

  closeRoomSocket();
  roomSocket = new WebSocket(`${WS_BASE}/rooms/${code}/`);
  roomSocket.roomCode = code;

  roomSocket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'room_update') {
      const wasPlaying = currentRoom.value?.status === 'Playing';
      currentRoom.value = data.room;
      console.log('Room update:', data);

      handlePlayingRoomNavigation(data.room, Boolean(data.test_mode || data.room?.test_mode), {
        forceEnter: !wasPlaying,
      });
    }
    if (data.type === 'room_left' || data.type === 'room_deleted') {
      setRoom(null);
    }
  };

  roomSocket.onclose = () => {
    if (roomSocket?.roomCode === code) {
      roomSocket = null;
    }
  };
}

async function loadCurrentRoom() {
  const data = await request('/rooms/current/');
  setRoom(data.room);

  handlePlayingRoomNavigation(data.room, Boolean(data.room?.test_mode));
  clearLeaveGameQuery();
}

function startLobbyPolling() {
  stopLobbyPolling();
  lobbyPollId = window.setInterval(async () => {
    if (!currentRoom.value) {
      return;
    }

    if (roomSocket?.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      const wasPlaying = currentRoom.value?.status === 'Playing';
      const data = await request('/rooms/current/');
      console.log('Lobby poll:', data);
      setRoom(data.room);
      handlePlayingRoomNavigation(data.room, Boolean(data.room?.test_mode), {
        forceEnter: !wasPlaying,
      });
    } catch (err) {
      console.error('Failed to poll current room:', err);
    }
  }, 5000);
}

function stopLobbyPolling() {
  if (lobbyPollId) {
    window.clearInterval(lobbyPollId);
    lobbyPollId = null;
  }
}

async function loadPublicRooms() {
  publicRoomsLoading.value = true;
  publicRoomsError.value = '';

  try {
    const data = await request('/rooms/public/');
    publicRooms.value = data.rooms || [];
  } catch (err) {
    publicRoomsError.value = err.message || '無法取得公開房間列表。';
  } finally {
    publicRoomsLoading.value = false;
  }
}

function startPublicRoomsPolling() {
  if (publicRoomsPollId) {
    return;
  }

  publicRoomsPollId = window.setInterval(() => {
    loadPublicRooms();
  }, 5000);
}

function stopPublicRoomsPolling() {
  if (publicRoomsPollId) {
    window.clearInterval(publicRoomsPollId);
    publicRoomsPollId = null;
  }
}

async function joinPublicRoom(room) {
  if (!room?.code) {
    return;
  }

  joinCode.value = room.code;
  await joinRoom();
}

async function submitLogout() {
  loading.value = true;
  stopLobbyPolling();
  stopPublicRoomsPolling();
  closeRoomSocket();
  closeMatchmakingSocket();
  setMatchmakingTicket(null);
  try {
    await request('/auth/logout/', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    currentUser.value = null;
    localStorage.removeItem('authToken');
    router.push('/auth');
  } catch (err) {
    errorMessage.value = err.message;
  } finally {
    loading.value = false;
  }
}

async function createRoom() {
  roomBusy.value = true;
  errorMessage.value = '';
  try {
    const data = await request('/rooms/create/', {
      method: 'POST',
      body: JSON.stringify({
        is_public: createRoomIsPublic.value,
      }),
    });
    setMatchmakingTicket(null);
    setRoom(data.room);
    await loadPublicRooms();
  } catch (err) {
    errorMessage.value = err.message;
  } finally {
    roomBusy.value = false;
  }
}

async function joinRoom() {
  const code = joinCode.value.trim();
  if (!code) {
    errorMessage.value = '請輸入房間代碼。';
    return;
  }

  roomBusy.value = true;
  errorMessage.value = '';
  try {
    const data = await request('/rooms/join/', {
      method: 'POST',
      body: JSON.stringify({ code }),
    });
    setMatchmakingTicket(null);
    setRoom(data.room);
    await loadPublicRooms();
  } catch (err) {
    errorMessage.value = err.message;
  } finally {
    roomBusy.value = false;
  }
}

async function toggleReady() {
  if (!currentRoom.value || !currentMember.value) {
    return;
  }

  roomBusy.value = true;
  errorMessage.value = '';
  try {
    const data = await request(`/rooms/${currentRoom.value.code}/ready/`, {
      method: 'POST',
      body: JSON.stringify({ is_ready: !currentMember.value.is_ready }),
    });
    setRoom(data.room);
  } catch (err) {
    errorMessage.value = err.message;
  } finally {
    roomBusy.value = false;
  }
}

async function leaveRoom() {
  if (!currentRoom.value) {
    return;
  }

  roomBusy.value = true;
  errorMessage.value = '';
  try {
    await request(`/rooms/${currentRoom.value.code}/leave/`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
    setRoom(null);
    await loadPublicRooms();
  } catch (err) {
    errorMessage.value = err.message;
  } finally {
    roomBusy.value = false;
  }
}

async function startGame() {
  if (!currentRoom.value) {
    return;
  }

  roomBusy.value = true;
  errorMessage.value = '';
  try {
    const data = await request(`/rooms/${currentRoom.value.code}/start/`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
    if (data.ticket) {
      setMatchmakingTicket(data.ticket);

      if (data.room) {
        setRoom(data.room);
      } else {
        setRoom(null);
      }

      connectMatchmakingSocket();
      return;
    }

    setMatchmakingTicket(null);
    setRoom(data.room);
    handlePlayingRoomNavigation(data.room, Boolean(data.room?.test_mode), {
      forceEnter: true,
    });
  } catch (err) {
    errorMessage.value = err.message;
  } finally {
    roomBusy.value = false;
  }
}

async function startTestGame() {
  if (!currentRoom.value) {
    return;
  }

  roomBusy.value = true;
  errorMessage.value = '';
  try {
    const data = await request(`/rooms/${currentRoom.value.code}/start/`, {
      method: 'POST',
      body: JSON.stringify({ test_mode: true }),
    });
    setRoom(data.room);
    router.push({
      path: '/game-ui',
      query: {
        room: data.room.code,
        test: '1',
      },
    });
  } catch (err) {
    errorMessage.value = err.message;
  } finally {
    roomBusy.value = false;
  }
}

async function joinMatchmaking() {
  roomBusy.value = true;
  errorMessage.value = '';
  try {
    connectMatchmakingSocket();
    const data = await request('/matchmaking/join/', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    handleMatchmakingMessage({
      type: data.ticket ? 'waiting' : (data.room ? 'matched' : 'idle'),
      ...data,
    });
  } catch (err) {
    errorMessage.value = err.message;
  } finally {
    roomBusy.value = false;
  }
}

async function cancelMatchmaking() {
  roomBusy.value = true;
  errorMessage.value = '';
  try {
    const data = await request('/matchmaking/cancel/', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    handleMatchmakingMessage({ type: 'cancelled', ...data });
  } catch (err) {
    errorMessage.value = err.message;
  } finally {
    roomBusy.value = false;
  }
}

async function loadMatchmakingStatus() {
  const data = await request('/matchmaking/status/');
  handleMatchmakingMessage({
    type: data.ticket ? 'waiting' : (data.room ? 'matched' : 'idle'),
    ...data,
  });
}

function returnToGame() {
  if (currentRoom.value?.game_status?.reconnect_blocked) {
    errorMessage.value = currentRoom.value.game_status.reason || '此局已由 AI 代打，無法重新加入。';
    return;
  }
  goToGameRoom(currentRoom.value);
}

function toggleStatsPanel() {
  showStatsPanel.value = !showStatsPanel.value;
}

onMounted(async () => {
  try {
    const data = await request('/auth/me/');
    currentUser.value = data.user;
    connectMatchmakingSocket();
    await loadCurrentRoom();
    await loadMatchmakingStatus();
    await loadPublicRooms();
    startLobbyPolling();
    startPublicRoomsPolling();
  } catch (err) {
    console.error('Failed to load lobby:', err);
    router.push('/auth');
  }
});

onBeforeUnmount(() => {
  stopLobbyPolling();
  stopPublicRoomsPolling();
  stopMatchmakingTimer();
  stopMatchmakingStatusPolling();
  closeRoomSocket();
  closeMatchmakingSocket();
});
</script>

<template>
  <main class="lobby-page" :style="{ '--lobby-bg-image': `url(${hallImage})` }">
    <header class="lobby-header">
      <div class="header-content">
        <h1>Game Lobby</h1>
        <button class="logout-btn" :disabled="loading" @click="submitLogout">
          {{ loading ? 'Logging out...' : 'Logout' }}
        </button>
      </div>
    </header>

    <div class="lobby-container">
      <PlayerInfoCard
        v-if="currentUser"
        :user="currentUser"
        @click="toggleStatsPanel"
      />

      <PlayerStatsPanel
        v-if="showStatsPanel && currentUser"
        :user="currentUser"
        @close="toggleStatsPanel"
      />

      <section class="room-panel">
        <div class="room-header">
          <div>
            <p class="section-label">房間狀態</p>
            <h2 v-if="currentRoom">房間 {{ currentRoom.code }}</h2>
            <h2 v-else>尚未進入房間</h2>
          </div>
          <span v-if="currentRoom" class="room-status">{{ currentRoom.status }}</span>
        </div>

        <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
        <p v-if="matchmakingStatusText" class="matchmaking-message">{{ matchmakingStatusText }}</p>

        <div v-if="currentRoom" class="room-content">
          <div class="seat-grid">
            <div
              v-for="(seat, index) in seats"
              :key="seat.empty ? seat.id : seat.user.id || seat.user.username"
              class="seat-card"
              :class="{ empty: seat.empty, ready: seat.is_ready, host: seat.is_host }"
            >
              <span class="seat-index">P{{ index + 1 }}</span>
              <strong>{{ seat.empty ? '等待玩家' : seat.user.nickname || seat.user.username }}</strong>
              <small v-if="!seat.empty">
                {{ seat.is_host ? '房主' : seat.is_ready ? '已準備' : '未準備' }}
              </small>
            </div>
          </div>

          <LobbyActionButtons
            :busy="roomBusy"
            :in-room="true"
            :is-ready="!!currentMember?.is_ready"
            :can-start="!!currentRoom.can_start"
            :is-playing="currentRoom.status === 'Playing'"
            :is-host="!!currentMember?.is_host"
            :start-label="roomStartLabel"
            @toggle-ready="toggleReady"
            @start-game="startGame"
            @test-start="startTestGame"
            @leave-room="leaveRoom"
            @return-game="returnToGame"
          />
        </div>

        <div v-else class="room-content">
          <label class="join-field">
            <span>房間代碼</span>
            <input
              v-model="joinCode"
              maxlength="6"
              inputmode="numeric"
              placeholder="輸入 6 位數代碼"
              @keyup.enter="joinRoom"
            />
          </label>

          <label class="room-public-option">
            <input
              v-model="createRoomIsPublic"
              type="checkbox"
            />
            <span>建立為公開房間</span>
          </label>

          <LobbyActionButtons
            :busy="roomBusy"
            :is-matchmaking="isMatchmaking"
            @create-room="createRoom"
            @join-room="joinRoom"
            @join-matchmaking="joinMatchmaking"
            @cancel-matchmaking="cancelMatchmaking"
          />

          <section class="public-room-section">
            <div class="public-room-header">
              <h3>公開房間</h3>
              <button
                type="button"
                class="refresh-public-room-btn"
                :disabled="publicRoomsLoading"
                @click="loadPublicRooms"
              >
                重新整理
              </button>
            </div>

            <p v-if="publicRoomsError" class="public-room-error">
              {{ publicRoomsError }}
            </p>

            <p v-else-if="!publicRoomsLoading && publicRooms.length === 0" class="public-room-empty">
              目前沒有可加入的公開房間
            </p>

            <div
              v-for="room in publicRooms"
              :key="room.code"
              class="public-room-card"
            >
              <div>
                <strong>房間 {{ room.code }}</strong>
                <div>人數：{{ room.member_count }}/{{ room.max_members }}</div>
                <div>狀態：{{ room.status }}</div>
              </div>

              <button
                type="button"
                class="join-public-room-btn"
                :disabled="roomBusy || room.member_count >= room.max_members || room.is_matchmaking"
                @click="joinPublicRoom(room)"
              >
                加入
              </button>
            </div>
          </section>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.lobby-page {
  min-height: 100vh;
  background:
    linear-gradient(rgba(15, 23, 42, 0.42), rgba(15, 23, 42, 0.5)),
    var(--lobby-bg-image) center / contain no-repeat fixed;
  background-color: #0f172a;
  display: flex;
  flex-direction: column;
}

.lobby-header {
  background: #ffffff;
  border-bottom: 1px solid #d8dee8;
  padding: 16px 32px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
}

.lobby-header h1 {
  margin: 0;
  font-size: 28px;
  color: #1f2937;
}

.logout-btn {
  background: #ef4444;
  color: #ffffff;
  border: 1px solid #dc2626;
  border-radius: 6px;
  padding: 8px 16px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.2s;
}

.logout-btn:hover {
  background: #dc2626;
}

.logout-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.lobby-container {
  flex: 1;
  padding: 32px;
  position: relative;
}

.room-panel {
  max-width: 760px;
  margin: 28px auto 0;
  padding: 22px;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
}

.room-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 18px;
}

.section-label {
  margin: 0 0 4px;
  color: #64748b;
  font-size: 13px;
  font-weight: 700;
}

.room-header h2 {
  margin: 0;
  color: #111827;
  font-size: 24px;
}

.room-status {
  padding: 6px 10px;
  border-radius: 999px;
  background: #e0f2fe;
  color: #0369a1;
  font-size: 13px;
  font-weight: 700;
}

.error-message {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fee2e2;
  color: #991b1b;
  font-size: 14px;
}

.matchmaking-message {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #dcfce7;
  color: #166534;
  font-size: 14px;
  font-weight: 700;
}

.room-content {
  display: grid;
  gap: 18px;
}

.seat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.seat-card {
  min-height: 108px;
  display: grid;
  align-content: center;
  gap: 6px;
  padding: 14px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #f8fafc;
  color: #0f172a;
}

.seat-card.ready {
  border-color: #22c55e;
  background: #f0fdf4;
}

.seat-card.host {
  border-color: #2563eb;
}

.seat-card.empty {
  color: #94a3b8;
  border-style: dashed;
}

.seat-index {
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
}

.seat-card strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.seat-card small {
  color: #475569;
}

.join-field {
  display: grid;
  gap: 8px;
  color: #334155;
  font-size: 14px;
  font-weight: 700;
}

.join-field input {
  width: min(280px, 100%);
  height: 42px;
  padding: 0 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 16px;
}

.room-public-option {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #334155;
  font-size: 14px;
  font-weight: 700;
}

.room-public-option input {
  width: 16px;
  height: 16px;
}

.public-room-section {
  display: grid;
  gap: 10px;
  margin-top: 8px;
  padding-top: 18px;
  border-top: 1px solid #e2e8f0;
}

.public-room-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.public-room-header h3 {
  margin: 0;
  color: #111827;
  font-size: 18px;
}

.refresh-public-room-btn,
.join-public-room-btn {
  min-height: 36px;
  padding: 8px 12px;
  border: 1px solid #1d4ed8;
  border-radius: 8px;
  background: #2563eb;
  color: #ffffff;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.refresh-public-room-btn:disabled,
.join-public-room-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.public-room-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #f8fafc;
  color: #0f172a;
}

.public-room-card strong {
  display: block;
  margin-bottom: 4px;
}

.public-room-empty {
  margin: 0;
  color: #64748b;
  font-size: 14px;
}

.public-room-error {
  margin: 0;
  color: #991b1b;
  font-size: 14px;
  font-weight: 700;
}

@media (max-width: 760px) {
  .lobby-container {
    padding: 18px;
  }

  .seat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
