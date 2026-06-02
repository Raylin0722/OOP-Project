<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import PlayerInfoCard from '../components/PlayerInfoCard.vue';
import PlayerStatsPanel from '../components/PlayerStatsPanel.vue';
import LobbyActionButtons from '../components/LobbyActionButtons.vue';

const API_BASE = `http://${window.location.hostname}:8000/api`;
const WS_BASE = `ws://${window.location.hostname}:8000/ws`;
const router = useRouter();
const route = useRoute();

const currentUser = ref(null);
const currentRoom = ref(null);
const joinCode = ref('');
const loading = ref(false);
const roomBusy = ref(false);
const errorMessage = ref('');
const showStatsPanel = ref(false);
let roomSocket = null;

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
      currentRoom.value = data.room;
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

  if (data.room?.status === 'Playing' && route.query.left !== '1') {
    router.push({ path: '/game-ui', query: { room: data.room.code } });
  }
}

async function submitLogout() {
  loading.value = true;
  try {
    await request('/auth/logout/', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    closeRoomSocket();
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
      body: JSON.stringify({}),
    });
    setRoom(data.room);
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
    setRoom(data.room);
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
    setRoom(data.room);
    router.push({ path: '/game-ui', query: { room: data.room.code } });
  } catch (err) {
    errorMessage.value = err.message;
  } finally {
    roomBusy.value = false;
  }
}

function startTestGame() {
  if (!currentRoom.value) {
    return;
  }

  router.push({
    path: '/game-ui',
    query: {
      room: currentRoom.value.code,
      test: '1',
    },
  });
}

function toggleStatsPanel() {
  showStatsPanel.value = !showStatsPanel.value;
}

onMounted(async () => {
  try {
    const data = await request('/auth/me/');
    currentUser.value = data.user;
    await loadCurrentRoom();
  } catch (err) {
    console.error('Failed to load lobby:', err);
    router.push('/auth');
  }
});

onBeforeUnmount(() => {
  closeRoomSocket();
});
</script>

<template>
  <main class="lobby-page">
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
            @toggle-ready="toggleReady"
            @start-game="startGame"
            @test-start="startTestGame"
            @leave-room="leaveRoom"
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

          <LobbyActionButtons
            :busy="roomBusy"
            @create-room="createRoom"
            @join-room="joinRoom"
          />
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.lobby-page {
  min-height: 100vh;
  background: #eef2f7;
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

@media (max-width: 760px) {
  .lobby-container {
    padding: 18px;
  }

  .seat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
