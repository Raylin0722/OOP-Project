<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import PlayerStatsPanel from '../components/PlayerStatsPanel.vue';
import LobbyActionButtons from '../components/LobbyActionButtons.vue';
import hallImage from '../assets/pictures/hall.jpg';
import lobbyButtonImage from '../assets/pictures/lobbybutton.png';
import refreshPlaceholderIcon from '../assets/pictures/lobby-refresh-placeholder.svg';

const API_BASE = '/api';
const WS_PROTOCOL = window.location.protocol === 'https:' ? 'wss' : 'ws';
const WS_BASE = `${WS_PROTOCOL}://${window.location.host}/ws`;
const router = useRouter();
const route = useRoute();

const currentUser = ref(null);
const currentRoom = ref(null);
const joinCode = ref('');
const showJoinRoomModal = ref(false);
const roomVisibilityLocalCooldownUntil = ref(0);
const uiTick = ref(Date.now());
const publicRooms = ref([]);
const publicRoomsLoading = ref(false);
const publicRoomsError = ref('');
const publicRoomsLoaded = ref(false);
const loading = ref(false);
const roomBusy = ref(false);
const errorMessage = ref('');
const showStatsPanel = ref(false);
const showVisibilityCooldownNotice = ref(false);
const matchmakingTicket = ref(null);
const matchmakingTick = ref(0);
let roomSocket = null;
let matchmakingSocket = null;
let lobbyPollId = null;
let publicRoomsPollId = null;
let uiTickId = null;
let matchmakingTimerId = null;
let matchmakingStatusPollId = null;
let matchmakingReconnectTimerId = null;
let visibilityCooldownNoticeTimerId = null;
let suppressBeforeUnloadWarning = false;

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

const isCurrentUserHost = computed(() => Boolean(currentMember.value?.is_host));
const canManageRoomMembers = computed(() => (
  Boolean(currentRoom.value)
  && isCurrentUserHost.value
  && currentRoom.value.status !== 'Playing'
));

const visiblePublicRooms = computed(() => publicRooms.value.slice(0, 6));

const roomVisibilityCooldownRemaining = computed(() => {
  uiTick.value;

  if (!currentRoom.value) {
    return 0;
  }

  const cooldownSeconds = Number(currentRoom.value.visibility_toggle_cooldown_seconds ?? 10);
  const cooldownMs = cooldownSeconds * 1000;
  const changedAt = currentRoom.value.last_visibility_changed_at
    ? new Date(currentRoom.value.last_visibility_changed_at).getTime()
    : 0;
  const backendCooldownUntil = Number.isNaN(changedAt) ? 0 : changedAt + cooldownMs;
  const cooldownUntil = Math.max(backendCooldownUntil, roomVisibilityLocalCooldownUntil.value);

  return Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
});

const canToggleRoomVisibility = computed(() => (
  Boolean(currentRoom.value)
  && isCurrentUserHost.value
  && currentRoom.value.status !== 'Playing'
  && !roomBusy.value
  && roomVisibilityCooldownRemaining.value === 0
));

const roomVisibilityButtonText = computed(() => {
  if (!currentRoom.value) {
    return '切換公開';
  }

  const remaining = roomVisibilityCooldownRemaining.value;
  if (remaining > 0) {
    return `${remaining} 秒後可切換`;
  }

  return currentRoom.value.is_public ? '設為私密' : '設為公開';
});

function showVisibilityCooldownToast() {
  showVisibilityCooldownNotice.value = false;

  if (visibilityCooldownNoticeTimerId) {
    window.clearTimeout(visibilityCooldownNoticeTimerId);
    visibilityCooldownNoticeTimerId = null;
  }

  window.requestAnimationFrame(() => {
    showVisibilityCooldownNotice.value = true;
    visibilityCooldownNoticeTimerId = window.setTimeout(() => {
      showVisibilityCooldownNotice.value = false;
      visibilityCooldownNoticeTimerId = null;
    }, 1800);
  });
}

function handleUnauthorized() {
  currentUser.value = null;
  currentRoom.value = null;
  localStorage.removeItem('authToken');
  stopLobbyPolling();
  stopPublicRoomsPolling();
  stopUiTicker();
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
  const shouldShowLoading = !publicRoomsLoaded.value;
  if (shouldShowLoading) {
    publicRoomsLoading.value = true;
  }

  try {
    const data = await request('/rooms/public/');
    const nextRooms = data.rooms || [];
    const currentSnapshot = JSON.stringify(publicRooms.value);
    const nextSnapshot = JSON.stringify(nextRooms);

    if (currentSnapshot !== nextSnapshot) {
      publicRooms.value = nextRooms;
    }

    if (publicRoomsError.value) {
      publicRoomsError.value = '';
    }

    publicRoomsLoaded.value = true;
  } catch (err) {
    const nextError = err.message || '無法取得公開房間列表。';
    if (publicRoomsError.value !== nextError) {
      publicRoomsError.value = nextError;
    }
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

function startUiTicker() {
  if (uiTickId) {
    return;
  }

  uiTickId = window.setInterval(() => {
    uiTick.value = Date.now();
  }, 1000);
}

function stopUiTicker() {
  if (uiTickId) {
    window.clearInterval(uiTickId);
    uiTickId = null;
  }
}

function openJoinRoomModal() {
  joinCode.value = '';
  showJoinRoomModal.value = true;
}

function closeJoinRoomModal() {
  showJoinRoomModal.value = false;
}

function shouldWarnBeforeLeavingLobby() {
  return !suppressBeforeUnloadWarning && Boolean(currentRoom.value || matchmakingTicket.value);
}

function handleLobbyBeforeUnload(event) {
  if (!shouldWarnBeforeLeavingLobby()) {
    return;
  }

  event.preventDefault();
  event.returnValue = '你目前仍在房間或配對中，直接關閉視窗可能會造成中離。';
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
  suppressBeforeUnloadWarning = true;
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
    suppressBeforeUnloadWarning = false;
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
    closeJoinRoomModal();
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

async function toggleRoomVisibility() {
  if (!currentRoom.value || !isCurrentUserHost.value) {
    return;
  }

  roomBusy.value = true;
  errorMessage.value = '';
  try {
    const nextIsPublic = !currentRoom.value.is_public;
    const data = await request(`/rooms/${currentRoom.value.code}/visibility/`, {
      method: 'POST',
      body: JSON.stringify({ is_public: nextIsPublic }),
    });
    const cooldownSeconds = Number(data.visibility_toggle_cooldown_seconds ?? data.room?.visibility_toggle_cooldown_seconds ?? 10);
    roomVisibilityLocalCooldownUntil.value = Date.now() + cooldownSeconds * 1000;
    setRoom(data.room);
    await loadPublicRooms();
  } catch (err) {
    errorMessage.value = err.message;
  } finally {
    roomBusy.value = false;
  }
}

function handleVisibilityBadgeClick() {
  if (!currentRoom.value || !isCurrentUserHost.value || roomBusy.value) {
    return;
  }

  if (roomVisibilityCooldownRemaining.value > 0) {
    showVisibilityCooldownToast();
    return;
  }

  toggleRoomVisibility();
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

async function kickMember(userId) {
  if (!currentRoom.value || !userId) {
    return;
  }

  roomBusy.value = true;
  errorMessage.value = '';
  try {
    const data = await request(`/rooms/${currentRoom.value.code}/kick/`, {
      method: 'POST',
      body: JSON.stringify({ user_id: userId }),
    });
    setRoom(data.room);
    await loadPublicRooms();
  } catch (err) {
    errorMessage.value = err.message;
  } finally {
    roomBusy.value = false;
  }
}

async function transferHost(userId) {
  if (!currentRoom.value || !userId) {
    return;
  }

  roomBusy.value = true;
  errorMessage.value = '';
  try {
    const data = await request(`/rooms/${currentRoom.value.code}/transfer-host/`, {
      method: 'POST',
      body: JSON.stringify({ user_id: userId }),
    });
    setRoom(data.room);
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
  window.addEventListener('beforeunload', handleLobbyBeforeUnload);
  startUiTicker();
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
  window.removeEventListener('beforeunload', handleLobbyBeforeUnload);
  if (visibilityCooldownNoticeTimerId) {
    window.clearTimeout(visibilityCooldownNoticeTimerId);
    visibilityCooldownNoticeTimerId = null;
  }
  stopLobbyPolling();
  stopPublicRoomsPolling();
  stopUiTicker();
  stopMatchmakingTimer();
  stopMatchmakingStatusPolling();
  closeRoomSocket();
  closeMatchmakingSocket();
});
</script>

<template>
  <main class="lobby-page">
    <section class="hall-board" :style="{ '--hall-bg-image': `url(${hallImage})`, '--lobby-button-image': `url(${lobbyButtonImage})` }">
      <button class="top-logout-btn" :disabled="loading" @click="submitLogout">
        {{ loading ? '登出中...' : '登出' }}
      </button>

      <h1 class="hall-title">Game Lobby</h1>

      <section class="lobby-content-shell">
        <p v-if="errorMessage" class="board-message error-message">{{ errorMessage }}</p>
        <p v-if="matchmakingStatusText" class="board-message matchmaking-message">{{ matchmakingStatusText }}</p>
        <transition name="cooldown-notice">
          <p v-if="showVisibilityCooldownNotice" class="visibility-cooldown-notice">
            {{ roomVisibilityCooldownRemaining }} 秒後才能再次切換
          </p>
        </transition>

        <PlayerStatsPanel
          v-if="showStatsPanel && currentUser"
          :user="currentUser"
          @close="toggleStatsPanel"
        />

        <template v-if="currentRoom">
          <section class="room-board-panel room-content-shell">
            <div class="room-board-header">
              <div>
                <p class="small-label">目前房間</p>
                <h2>房間 {{ currentRoom.code }}</h2>
              </div>
              <div class="room-badges">
                <span>{{ currentRoom.status }}</span>
                <span
                  :class="{ 'room-badge-clickable': isCurrentUserHost }"
                  @click="handleVisibilityBadgeClick"
                >
                  {{ currentRoom.is_public ? '公開' : '私密' }}
                </span>
              </div>
            </div>

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
                <div
                  v-if="canManageRoomMembers && !seat.empty && !seat.is_host && seat.user.id"
                  class="seat-card-actions"
                >
                  <button
                    type="button"
                    class="seat-card-action seat-card-host-action"
                    :disabled="roomBusy"
                    @click="transferHost(seat.user.id)"
                  >
                    設為房主
                  </button>
                  <button
                    type="button"
                    class="seat-card-action seat-card-kick-action"
                    :disabled="roomBusy"
                    @click="kickMember(seat.user.id)"
                  >
                    踢出
                  </button>
                </div>
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
          </section>
        </template>

        <template v-else>
          <section class="public-lobby-panel public-content-shell">
            <div class="public-panel-header">
              <button
                type="button"
                class="refresh-room-btn"
                :disabled="publicRoomsLoading"
                @click="loadPublicRooms"
              >
                <img :src="refreshPlaceholderIcon" alt="重新整理公開房間" class="refresh-room-icon">
              </button>
            </div>

            <div class="public-room-stage">
              <div class="public-room-scroll">
                <section
                  v-if="publicRooms.length > 0"
                  class="public-room-grid"
                  aria-label="公開房間列表"
                >
                  <button
                    v-for="room in publicRooms"
                    :key="room.code"
                    type="button"
                    class="public-room-slot"
                    :disabled="roomBusy || room.member_count >= room.max_members || room.is_matchmaking"
                    @click="joinPublicRoom(room)"
                  >
                    <strong>房間 {{ room.code }}</strong>
                    <span>{{ room.member_count }}/{{ room.max_members }} 人</span>
                    <small>{{ room.status }}</small>
                  </button>
                </section>

                <div v-else class="public-room-state">
                  <p v-if="publicRoomsError" class="public-room-error">{{ publicRoomsError }}</p>
                  <p v-else class="public-room-empty">
                    目前沒有可加入的公開房間
                  </p>
                </div>
              </div>
            </div>

            <div class="public-action-row">
              <button type="button" class="lobby-action-skin lobby-action-btn utility-blue-btn" @click="toggleStatsPanel">
                看戰績
              </button>

              <button type="button" class="lobby-action-skin lobby-action-btn utility-blue-btn" @click="openJoinRoomModal">
                搜尋房間
              </button>

              <button type="button" class="lobby-action-skin lobby-action-btn accent-purple-btn" :disabled="roomBusy" @click="createRoom">
                創建房間
              </button>

              <button
                v-if="!isMatchmaking"
                type="button"
                class="lobby-action-skin lobby-action-btn success-green-btn"
                :disabled="roomBusy"
                @click="joinMatchmaking"
              >
                開始配對
              </button>
              <button
                v-else
                type="button"
                class="lobby-action-skin lobby-action-btn warning-orange-btn"
                :disabled="roomBusy"
                @click="cancelMatchmaking"
              >
                取消配對
              </button>
            </div>
          </section>
        </template>
      </section>
    </section>

    <div v-if="showJoinRoomModal" class="modal-overlay" @click="closeJoinRoomModal">
      <section class="join-room-modal" @click.stop>
        <h2>搜尋房間</h2>
        <p>輸入 6 位數房間碼加入房間。</p>
        <input
          v-model="joinCode"
          maxlength="6"
          inputmode="numeric"
          placeholder="輸入房間碼"
          @keyup.enter="joinRoom"
        />
        <div class="modal-actions">
          <button type="button" class="wood-btn small-wood-btn" :disabled="roomBusy" @click="joinRoom">
            加入
          </button>
          <button type="button" class="wood-btn small-wood-btn secondary" @click="closeJoinRoomModal">
            取消
          </button>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.lobby-page {
  min-height: 100vh;
  position: relative;
  overflow: hidden;
  background:
    radial-gradient(circle at 50% 20%, rgba(70, 103, 138, 0.28), transparent 34%),
    linear-gradient(180deg, #06101d 0%, #0b1626 52%, #060d18 100%);
  display: grid;
  place-items: center;
  padding: 3vh 3vw;
}

.top-logout-btn {
  --logout-top: 12%;
  --logout-right: 12%;
  --logout-width: 7%;
  position: absolute;
  top: var(--logout-top);
  right: var(--logout-right);
  z-index: 20;
  width: var(--logout-width);
  padding: 0.7vh 1vw;
}

.hall-title {
  position: absolute;
  left: 27.6%;
  top: 8.9%;
  width: 45%;
  height: 13.5%;
  margin: 0;
  display: grid;
  place-items: center;
  background: transparent;
  color: #3c2714;
  font-family: Georgia, 'Times New Roman', serif;
  font-size: clamp(1.7rem, 3.2vw, 4.8rem);
  letter-spacing: 0.18em;
  font-weight: 500;
  text-shadow: 0 0.15vw 0.4vw rgba(255, 248, 237, 0.55);
}

.lobby-content-shell {
  --content-safe-left: 11%;
  --content-safe-right: 11%;
  --content-safe-top: 24.6%;
  --content-safe-bottom: 12%;
  --room-safe-left: 0%;
  --room-safe-right: 0%;
  --room-safe-top: 0%;
  --room-safe-bottom: 3%;
  --public-safe-left: 0%;
  --public-safe-right: 0%;
  --public-safe-top: 0%;
  --public-safe-bottom: 0%;
  --public-room-columns: 2;
  --public-room-visible-rows: 3;
  --public-room-row-gap: 2.2vh;
  --public-room-column-gap: 3%;
  --public-room-slot-height: 10.8vh;
  position: absolute;
  left: var(--content-safe-left);
  right: var(--content-safe-right);
  top: var(--content-safe-top);
  bottom: var(--content-safe-bottom);
}

.public-content-shell {
  margin-left: var(--public-safe-left);
  margin-right: var(--public-safe-right);
  margin-top: var(--public-safe-top);
  margin-bottom: var(--public-safe-bottom);
}

.board-message {
  position: absolute;
  left: 12%;
  right: 12%;
  top: 0;
  z-index: 5;
  margin: 0;
  padding: 0.8vh 1vw;
  border-radius: 0.55vw;
  text-align: center;
  font-size: clamp(0.8rem, 0.95vw, 1.35rem);
  font-weight: 700;
}

.error-message {
  background: rgba(254, 226, 226, 0.96);
  color: #991b1b;
}

.matchmaking-message {
  background: rgba(220, 252, 231, 0.96);
  color: #166534;
}

.visibility-cooldown-notice {
  position: absolute;
  top: 8%;
  left: 50%;
  z-index: 12;
  margin: 0;
  padding: 0.85vh 1vw;
  border-radius: 999vw;
  background: rgba(31, 41, 55, 0.9);
  color: #ffffff;
  font-size: clamp(0.78rem, 0.9vw, 1.2rem);
  font-weight: 700;
  transform: translateX(-50%);
  box-shadow: 0 0.55vw 1.1vw rgba(15, 23, 42, 0.18);
}

.cooldown-notice-enter-active,
.cooldown-notice-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}

.cooldown-notice-enter-from,
.cooldown-notice-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-0.8vh);
}

.public-room-grid {
  width: 100%;
  min-height: 0;
  display: grid;
  grid-template-columns: repeat(var(--public-room-columns), minmax(0, 1fr));
  grid-auto-rows: var(--public-room-slot-height);
  row-gap: var(--public-room-row-gap);
  column-gap: var(--public-room-column-gap);
}

.public-room-stage {
  min-height: 0;
  display: grid;
  align-items: start;
}

.public-room-scroll {
  height: calc(
    (var(--public-room-slot-height) * var(--public-room-visible-rows))
    + (var(--public-room-row-gap) * (var(--public-room-visible-rows) - 1))
  );
  min-height: calc(
    (var(--public-room-slot-height) * var(--public-room-visible-rows))
    + (var(--public-room-row-gap) * (var(--public-room-visible-rows) - 1))
  );
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: 0.8%;
  scrollbar-width: thin;
}

.public-room-scroll::-webkit-scrollbar {
  width: 0.55vw;
}

.public-room-scroll::-webkit-scrollbar-thumb {
  border-radius: 999vw;
  background: rgba(73, 50, 26, 0.45);
}

.public-room-slot {
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 0.25vh;
  border: 0.08vw solid rgba(43, 31, 22, 0.58);
  border-radius: 0.55vw;
  background: rgba(255, 255, 255, 0.94);
  color: #21170f;
  cursor: pointer;
  font-size: clamp(0.9rem, 1.12vw, 1.7rem);
  transition: transform 0.16s ease, box-shadow 0.16s ease;
  min-height: var(--public-room-slot-height);
}

.public-room-slot:hover:not(:disabled) {
  transform: translateY(-0.25vh);
  box-shadow: 0 0.5vw 1vw rgba(0, 0, 0, 0.23);
}

.public-room-slot:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.public-room-slot strong {
  font-size: clamp(1.05rem, 1.42vw, 2.2rem);
  font-weight: 700;
}

.public-room-slot small {
  opacity: 0.72;
}

.public-room-state {
  width: 100%;
  height: 100%;
  min-height: inherit;
  display: grid;
  place-items: center;
}

.public-room-empty,
.public-room-error {
  margin: 0;
  text-align: center;
  font-size: clamp(0.85rem, 1vw, 1.45rem);
  font-weight: 700;
}

.public-room-empty {
  color: rgba(35, 23, 13, 0.78);
}

.public-room-error {
  color: #991b1b;
}

.wood-btn,
.lobby-action-skin,
.top-logout-btn {
  --lobby-button-aspect-ratio: 668 / 330;
  --lobby-button-text-offset-y: 1%;
  border: 0;
  border-radius: 0;
  color: #3c2714;
  cursor: pointer;
  display: inline-grid;
  place-items: center;
  font-size: clamp(0.92rem, 1vw, 1.5rem);
  font-weight: 700;
  line-height: 1;
  aspect-ratio: var(--lobby-button-aspect-ratio);
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
  transition: transform 0.16s ease, box-shadow 0.16s ease, opacity 0.16s ease;
  box-shadow: none;
  text-shadow: 0 0.05vw 0.08vw rgba(255, 245, 220, 0.55);
  text-align: center;
  text-indent: 0;
  padding-block-start: var(--lobby-button-text-offset-y);
}

.wood-btn:hover:not(:disabled),
.lobby-action-skin:hover:not(:disabled),
.top-logout-btn:hover:not(:disabled) {
  transform: translateY(-0.25vh);
  filter: brightness(1.06);
}

.wood-btn:disabled,
.lobby-action-skin:disabled,
.top-logout-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.wood-btn {
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
}

.utility-blue-btn {
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
}

.success-green-btn {
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
}

.accent-purple-btn {
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
}

.danger-red-btn,
.top-logout-btn {
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
}

.warning-orange-btn {
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
}

.hall-board {
  position: relative;
  width: min(88vw, 160vh);
  aspect-ratio: 1.72 / 1;
  background: var(--hall-bg-image) center / 100% 100% no-repeat;
  filter: drop-shadow(0 1.2vw 1.6vw rgba(0, 0, 0, 0.45));
}

.public-lobby-panel {
  position: relative;
  height: 100%;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 3.4%;
}

.public-panel-header {
  display: flex;
  justify-content: flex-start;
  align-items: center;
  min-height: 5.6vh;
}

.refresh-room-btn {
  --refresh-button-width: 4.8%;
  --refresh-button-min-width: 2.8rem;
  display: grid;
  place-items: center;
  width: var(--refresh-button-width);
  min-width: var(--refresh-button-min-width);
  aspect-ratio: 1;
  padding: 0.5%;
  border: 0.08vw solid rgba(34, 24, 16, 0.48);
  border-radius: 0.45vw;
  background: rgba(255, 255, 255, 0.86);
  cursor: pointer;
}

.refresh-room-icon {
  width: 72%;
  height: 72%;
  object-fit: contain;
}

.public-action-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1.2%;
  align-items: stretch;
}

.lobby-action-btn {
  width: 100%;
  min-height: 0;
  padding: 0.7vh 1vw;
  --lobby-button-text-offset-y: 8%;
  padding-block-start: var(--lobby-button-text-offset-y);
  
}

.visibility-toggle-btn {
  min-width: 14%;
  min-height: 0;
  padding: 0.7vh 1vw;
  padding-block-start: var(--lobby-button-text-offset-y);
  font-size: clamp(0.78rem, 0.9vw, 1.35rem);
}

.room-board-panel {
  --room-panel-padding-y: 1.4%;
  --room-panel-padding-x: 2%;
  --room-panel-radius: 1.2%;
  --room-panel-gap: 2.2%;
  --room-panel-bg: rgba(255, 255, 255, 0.82);
  width: calc(100% - var(--room-safe-left) - var(--room-safe-right));
  height: calc(100% - var(--room-safe-top) - var(--room-safe-bottom));
  margin-left: var(--room-safe-left);
  margin-top: var(--room-safe-top);
  display: grid;
  grid-template-rows: auto 1fr auto auto;
  gap: var(--room-panel-gap);
  padding: var(--room-panel-padding-y) var(--room-panel-padding-x);
  border-radius: var(--room-panel-radius);
  background: var(--room-panel-bg);
  color: #1f160d;
  box-sizing: border-box;
}

.room-board-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1vw;
}

.small-label,
.room-board-header h2 {
  margin: 0;
}

.small-label {
  font-size: clamp(0.75rem, 0.85vw, 1.2rem);
  color: rgba(31, 22, 13, 0.72);
  font-weight: 700;
}

.room-board-header h2 {
  font-size: clamp(1.2rem, 1.8vw, 2.7rem);
}

.room-badges {
  display: flex;
  gap: 0.6vw;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.room-badges span {
  border-radius: 999vw;
  background: rgba(255, 255, 255, 0.72);
  padding: 0.45vh 0.8vw;
  font-size: clamp(0.75rem, 0.85vw, 1.2rem);
  font-weight: 700;
}

.room-badge-clickable {
  cursor: pointer;
  transition: transform 0.16s ease, box-shadow 0.16s ease, opacity 0.16s ease;
}

.room-badge-clickable:hover {
  transform: translateY(-0.12vh);
  box-shadow: 0 0.4vw 0.85vw rgba(15, 23, 42, 0.14);
}

.seat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1vw;
}

.seat-card {
  display: grid;
  align-content: center;
  gap: 0.4vh;
  padding: 1.1vh 0.8vw;
  border: 0.08vw solid rgba(43, 31, 22, 0.38);
  border-radius: 0.6vw;
  background: rgba(255, 255, 255, 0.74);
  min-width: 0;
}

.seat-card.ready {
  border-color: rgba(22, 101, 52, 0.85);
}

.seat-card.host {
  border-color: rgba(37, 99, 235, 0.72);
}

.seat-card.empty {
  color: rgba(31, 22, 13, 0.45);
  border-style: dashed;
}

.seat-card strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: clamp(0.9rem, 1vw, 1.55rem);
}

.seat-index,
.seat-card small {
  font-size: clamp(0.72rem, 0.78vw, 1.1rem);
}

.seat-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45vh 0.35vw;
  margin-top: 0.35vh;
}

.seat-card-action {
  /*
  原本色塊按鈕基底，保留作為回退參考：
  border: 0.08vw solid #cbd5e1;
  border-radius: 999vw;
  color: #ffffff;
  */
  --lobby-button-aspect-ratio: 668 / 330;
  --lobby-button-text-offset-y: 1%;
  width: clamp(3.6rem, 4.8vw, 7rem);
  border: 0;
  border-radius: 0;
  padding: 0.3vh 0.55vw;
  color: #3c2714;
  display: inline-grid;
  place-items: center;
  aspect-ratio: var(--lobby-button-aspect-ratio);
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
  font-size: clamp(0.62rem, 0.7vw, 0.98rem);
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  text-shadow: 0 0.05vw 0.08vw rgba(255, 245, 220, 0.55);
  text-align: center;
  padding-block-start: var(--lobby-button-text-offset-y);
  transition: transform 0.16s ease, box-shadow 0.16s ease, opacity 0.16s ease;
}

.seat-card-action:hover:not(:disabled) {
  transform: translateY(-0.1vh);
  /*
  原本色塊 hover 陰影，保留作為回退參考：
  box-shadow: 0 0.32vw 0.65vw rgba(15, 23, 42, 0.14);
  */
  filter: brightness(1.06);
}

.seat-card-action:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.seat-card-host-action {
  
  /* 原本轉讓房主色塊按鈕，保留作為回退參考： */
  background: #2563eb;
  border-color: #1d4ed8;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #ffffff;
  /* background: var(--lobby-button-image) center / 100% 100% no-repeat; */
}

.seat-card-kick-action {
  
  /* 原本踢出玩家色塊按鈕，保留作為回退參考： */
  background: #ef4444;
  border-color: #dc2626;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #ffffff;
  /* background: var(--lobby-button-image) center / 100% 100% no-repeat; */
}

.small-wood-btn {
  width: clamp(7rem, 9.5vw, 13rem);
  min-height: 0;
  padding: 0.7vh 1vw;
  padding-block-start: var(--lobby-button-text-offset-y);
  font-size: clamp(0.9rem, 1vw, 1.5rem);
}

.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.48);
}

.join-room-modal {
  width: min(34vw, 70vh);
  min-width: min(88vw, 24rem);
  display: grid;
  gap: 1.4vh;
  padding: 2.4vh 2vw;
  border-radius: 0.9vw;
  background: rgba(255, 255, 255, 0.97);
  color: #1f160d;
  box-shadow: 0 1vw 2.2vw rgba(0, 0, 0, 0.35);
}

.join-room-modal h2,
.join-room-modal p {
  margin: 0;
}

.join-room-modal h2 {
  font-size: clamp(1.3rem, 2vw, 3rem);
}

.join-room-modal p {
  font-size: clamp(0.9rem, 1vw, 1.4rem);
}

.join-room-modal input {
  min-height: 5.5vh;
  border: 0.08vw solid rgba(43, 31, 22, 0.42);
  border-radius: 0.55vw;
  padding: 0 1vw;
  font-size: clamp(1rem, 1.2vw, 1.8rem);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 1vw;
}

.secondary {
  /*
  原本 modal 次要按鈕色塊樣式，保留作為回退參考：
  background: #f97316;
  border-color: #ea580c;
  */
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
}

:deep(.action-buttons) {
  justify-content: flex-end;
  gap: 0.7vw;
}

:deep(.action-btn) {
  min-width: 7.5vw;
  min-height: 0;
  aspect-ratio: 668 / 330;
  padding: 0.7vh 1vw;
  padding-block-start: var(--lobby-button-text-offset-y);
  border-radius: 0.55vw;
  font-size: clamp(0.78rem, 0.9vw, 1.35rem);
  --lobby-button-text-offset-y: 2%;
}

@media (max-aspect-ratio: 4 / 3) {
  .hall-board {
    width: 96vw;
  }

  .public-action-row {
    gap: 0.8%;
  }

  .wood-btn {
    font-size: clamp(0.95rem, 2.25vw, 2.6rem);
  }
}

@media (max-width: 760px) {
  .lobby-page {
    padding: 1.5vh 1.5vw;
  }

  .hall-board {
    width: 98vw;
  }

  .public-room-grid {
    row-gap: 1.8vh;
    column-gap: 2.4%;
  }

  .public-action-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .seat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
