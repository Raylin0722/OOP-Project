<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import cardBackUrl from '../assets/source/card-back.png';
import gameRoomUrl from '../assets/pictures/game_room.png';
import roleFortuneTellerUrl from '../assets/pictures/c1_fortune_teller.png';
import roleWizardUrl from '../assets/pictures/c2_wizard.png';
import roleScoutUrl from '../assets/pictures/c3_scout.png';
import roleQueenUrl from '../assets/pictures/c4_queen.png';

const TURN_SECONDS = 30;
const API_BASE = '/api';
const WS_BASE = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`;
const cardImages = import.meta.glob('../assets/pictures/[rbgyf]*.png', { eager: true, import: 'default' });
const gameRoomBackground = `url("${gameRoomUrl}")`;

const route = useRoute();
const router = useRouter();
const roomId = ref(String(route.query.room || '449102'));
const roomTitle = ref('娛樂房・4人');
const isTestMode = computed(() => route.query.test === '1');
const selectedCardIndex = ref(null);
const remainingSeconds = ref(TURN_SECONDS);
const showSettingsModal = ref(false);
const showColorPickerModal = ref(false);
const showTargetPickerModal = ref(false);
const showReturnCardPickerModal = ref(false);
const showSkillDiscardPickerModal = ref(false);
const showGameOverModal = ref(false);
const boardScale = ref(1);
let gameSocket = null;
let turnTimerId = null;
let currentTurnStartedAt = null;
let gameStartedAt = null;
let gameTimeLimitSeconds = 15 * 60;

const topCardCount = ref(6);
const leftCardCount = ref(7);
const rightCardCount = ref(8);
const opponentTargets = ref([]);
const opponentSlots = ref({
  top: { name: '等待中', card_count: 0, role: null },
  left: { name: '等待中', card_count: 0, role: null },
  right: { name: '等待中', card_count: 0, role: null },
});
const currentDiscardCard = ref('黃 7');
const currentColor = ref('黃');
const drawPenalty = ref(0);
const gameRemainingSeconds = ref(15 * 60);
const turnDirection = ref('順時針');
const currentPlayerName = ref('你');
const playerName = ref('你（玩家）');
const winnerAnnouncement = ref('');
const gameEndReasonText = ref('');
const finalRankings = ref([]);
const playerNamesById = ref({});
const playableCardIndexes = ref([]);
const latestGameEvent = ref('');
const myPlayerId = ref(null);
const matchResults = ref([]);
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
const roleByCode = {
  seer: { name: '占卜師', image: roleFortuneTellerUrl },
  painter: { name: '巫師', image: roleWizardUrl },
  scout: { name: '斥侯', image: roleScoutUrl },
  queen: { name: '女皇', image: roleQueenUrl },
  none: { name: '角色', image: roleFortuneTellerUrl },
};
const playerRole = ref(roleByCode.none);
const playerSkillCode = ref('none');
const isMyTurn = ref(false);
const pendingColorAction = ref('card');
const pendingTargetIndex = ref(null);
const colorOptions = [
  { label: '紅', value: 'red', className: 'red' },
  { label: '藍', value: 'blue', className: 'blue' },
  { label: '黃', value: 'yellow', className: 'yellow' },
  { label: '綠', value: 'green', className: 'green' },
];

const selectedCard = computed(() => {
  if (selectedCardIndex.value === null) {
    return null;
  }

  return {
    index: selectedCardIndex.value,
    name: playerCards.value[selectedCardIndex.value],
  };
});

const returnCardOptions = computed(() => (
  playerCards.value
    .map((name, index) => ({ name, index }))
    .filter((card) => card.index !== selectedCard.value?.index)
));

const playButtonLabel = computed(() => {
  if (!selectedCard.value) {
    return '出牌';
  }

  if (requiresColorChoice(selectedCard.value.name)) {
    return '選顏色';
  }

  if (requiresTargetChoice(selectedCard.value.name)) {
    return '選對手';
  }

  return '出牌';
});

const drawButtonLabel = computed(() => (
  drawPenalty.value > 0 ? `抽 ${drawPenalty.value} 張` : '抽牌'
));

const skillButtonLabel = computed(() => {
  const skillName = playerRole.value?.name || '技能';
  return `使用${skillName}`;
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

const drawPenaltyHint = computed(() => {
  if (drawPenalty.value <= 0) {
    return '';
  }

  return `可接 +2 或 +4，否則抽 ${drawPenalty.value} 張`;
});

function displayCardLabel(cardName) {
  const displayName = normalizeDisplayCardName(cardName);
  const colorMap = {
    紅: 'R',
    藍: 'B',
    黃: 'Y',
    綠: 'G',
  };
  const parts = displayName.split(/\s+/);

  if (parts.length >= 2 && colorMap[parts[0]]) {
    const value = parts.slice(1).join('');
    const valueMap = {
      跳過: 'SKIP',
      反轉: 'REV',
      偷牌: 'STEAL',
      換手: 'SWAP',
      鄰抽: 'DRAW1',
      指抽二: 'PICK+2',
      '+2': '+2',
    };

    return `${colorMap[parts[0]]}${valueMap[value] || value}`;
  }

  const specialMap = {
    跳過: 'SKIP',
    反轉: 'REV',
    萬用: 'WILD',
    抽四: '+4',
    偷牌: 'STEAL',
    換手: 'SWAP',
    鄰抽: 'DRAW1',
    指抽二: 'PICK+2',
  };

  return specialMap[displayName] || displayName;
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
  const displayName = normalizeDisplayCardName(cardName);
  const colorMap = {
    紅: 'r',
    藍: 'b',
    黃: 'y',
    綠: 'g',
  };
  const actionMap = {
    跳過: 'skip',
    反轉: 'reverse',
    偷牌: 'pick_throw1',
    '+2': '+2',
  };
  const blackActionMap = {
    換手: 'switch',
    鄰抽: 'draw1',
    指抽二: 'pick+2',
  };
  const normalized = displayName;

  if (normalized === '萬用') {
    return cardImages['../assets/pictures/f_change_color.png'];
  }

  if (normalized === '抽四') {
    return cardImages['../assets/pictures/f_change_color+4.png'];
  }

  if (blackActionMap[normalized]) {
    return cardImages[`../assets/pictures/f_${blackActionMap[normalized]}.png`];
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

function normalizeDisplayCardName(cardName) {
  const raw = String(cardName || '').trim();
  const compact = raw.replace(/[-_\s]/g, '').toLowerCase();
  const colorPrefixMap = {
    r: '紅',
    red: '紅',
    b: '藍',
    blue: '藍',
    y: '黃',
    yellow: '黃',
    g: '綠',
    green: '綠',
  };
  const rawValueMap = {
    draw2: '+2',
    draw_2: '+2',
    wild: '萬用',
    wilddraw4: '抽四',
    wild_draw4: '抽四',
    wild_draw_4: '抽四',
    skip: '跳過',
    reverse: '反轉',
    stealcard: '偷牌',
    steal_card: '偷牌',
    steal1swap: '偷牌',
    steal_1_swap: '偷牌',
    swaphand: '換手',
    swap_hand: '換手',
    swaphands: '換手',
    swap_hands: '換手',
    neighborswap: '鄰抽',
    neighbor_swap: '鄰抽',
    everyonestealneighbor: '鄰抽',
    everyone_steal_neighbor: '鄰抽',
    targetdraw2: '指抽二',
    target_draw2: '指抽二',
    targetdraw_2: '指抽二',
    target_draw_2: '指抽二',
  };

  if (!raw) {
    return raw;
  }

  const spacedParts = raw.split(/\s+/);
  if (spacedParts.length >= 2) {
    const color = colorPrefixMap[spacedParts[0].toLowerCase()];
    const valueRaw = spacedParts.slice(1).join('_').toLowerCase();
    const value = rawValueMap[valueRaw] || rawValueMap[valueRaw.replace(/[-_]/g, '')];
    if (color && value) {
      return value === '萬用' || value === '抽四' || value === '換手' || value === '鄰抽' || value === '指抽二'
        ? (value === '偷牌' || value === '+2' || value === '跳過' || value === '反轉' ? `${color} ${value}` : value)
        : `${color} ${value}`;
    }
  }

  const compactMatch = compact.match(/^(red|blue|yellow|green|r|b|y|g)(.+)$/);
  if (compactMatch) {
    const color = colorPrefixMap[compactMatch[1]];
    const value = rawValueMap[compactMatch[2]];
    if (color && value) {
      return `${color} ${value}`;
    }
  }

  return rawValueMap[raw.toLowerCase()] || rawValueMap[compact] || raw;
}

function cardActionKind(cardName) {
  const raw = String(cardName || '').trim();
  const normalized = normalizeDisplayCardName(raw);
  const compact = raw.replace(/[-_\s]/g, '').toLowerCase();
  const normalizedCompact = normalized.replace(/\s/g, '');

  if (normalizedCompact === '萬用' || compact.includes('wild') && !compact.includes('draw4') && !compact.includes('draw_4')) {
    return 'wild';
  }

  if (normalizedCompact === '抽四' || compact.includes('wilddraw4') || compact.includes('wilddraw_4')) {
    return 'wild_draw4';
  }

  if (normalizedCompact.includes('換手') || compact.includes('swaphand')) {
    return 'swap_hand';
  }

  if (normalizedCompact.includes('偷牌') || compact.includes('stealcard') || compact.includes('steal1swap')) {
    return 'steal_card';
  }

  if (normalizedCompact.includes('指抽二') || compact.includes('targetdraw2')) {
    return 'target_draw2';
  }

  if (normalizedCompact.includes('鄰抽') || compact.includes('neighborswap') || compact.includes('everyonestealneighbor')) {
    return 'neighbor_swap';
  }

  return null;
}

function cardImageStyle(cardName) {
  const imageUrl = cardAssetUrl(cardName);
  return imageUrl ? imageStyle(imageUrl) : {};
}

function handleUnauthorized() {
  localStorage.removeItem('authToken');
  closeGameSocket();
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

async function setupGameServerConnection() {
  try {
    const data = await request('/rooms/current/');
    if (data.room) {
      applyGameStatePayload({ room: data.room });
    }
  } catch (err) {
    console.error('Failed to load current room:', err);
  }

  connectGameSocket();
}

function connectGameSocket() {
  if (!roomId.value || gameSocket) {
    return;
  }

  gameSocket = new WebSocket(`${WS_BASE}/game/${roomId.value}/`);

  gameSocket.onopen = () => {
    gameSocket.send(JSON.stringify({ action: 'get_state' }));
    gameSocket.send(JSON.stringify({ action: 'start_game', test_mode: isTestMode.value }));
  };

  gameSocket.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === 'game_state') {
      applyConsumerState(data);
      return;
    }

    if (data.type === 'game_started') {
      return;
    }

    if (data.type === 'game_ended') {
      console.log('Received game event:', data);
      updateLatestGameEvent(data);
      handleGameEnded(data);
      return;
    }

      if (data.type === 'match_results') {
        handleMatchResults(data.results || data.results);
        return;
      }

    if (['card_played', 'card_drawn', 'skill_used'].includes(data.type)) {
      console.log('Received game event:', data);
      updateLatestGameEvent(data);
      return;
    }

    if (data.type === 'error') {
        console.error('Game socket error:', data.message);
        latestGameEvent.value = data.message || '遊戲操作失敗';
        // 伺服器回傳錯誤：重新拉一次 server 的遊戲狀態以回滾任何樂觀更新
        try {
          sendGameSocketAction({ action: 'get_state' });
        } catch (e) {
          console.warn('Failed to request state after error', e);
        }
    }
  };

  gameSocket.onclose = (event) => {
    gameSocket = null;

    if (event.code === 4401 || event.code === 4403) {
      handleUnauthorized();
      return;
    }

    if (event.code === 4408) {
      window.alert('此局已超過重連時間，將由 AI 代打至本局結束。');
      window.location.assign('/lobby?left=1');
    }
  };
}

function closeGameSocket() {
  if (gameSocket) {
    gameSocket.close();
    gameSocket = null;
  }
}

function openDebugPage() {
  if (!isTestMode.value) {
    return;
  }

  const debugUrl = new URL('/game-debug', window.location.origin);
  debugUrl.searchParams.set('room', roomId.value);
  window.open(debugUrl.toString(), '_blank', 'noopener,noreferrer');
}

function sendGameSocketAction(payload) {
  if (!gameSocket || gameSocket.readyState !== WebSocket.OPEN) {
    console.warn('Game socket is not connected. Prepared payload:', payload);
    return;
  }

  gameSocket.send(JSON.stringify(payload));
}

function applyConsumerState(data) {
  if (!data.state) {
    return;
  }

  const state = data.state;
  const hand = data.hand;
  const players = state.players || [];
  const currentPlayer = players[state.current_player_index];
  myPlayerId.value = hand?.player_id;
  const selfPlayer = players.find((player) => String(player.player_id) === String(myPlayerId.value));
  playerNamesById.value = players.reduce((names, player) => {
    names[String(player.player_id)] = formatPlayerDisplayName(player);
    return names;
  }, {});
  playerRole.value = roleFromPlayer(selfPlayer);
  playerSkillCode.value = String(selfPlayer?.skill_code || 'none').toLowerCase();
  isMyTurn.value = Boolean(hand?.is_my_turn);
  playerName.value = selfPlayer?.name ? `${formatPlayerDisplayName(selfPlayer)}（玩家）` : '你（玩家）';
  const opponentLayout = buildOpponentLayout(players, myPlayerId.value);

  applyGameStatePayload({
    player: {
      hand: (hand?.cards || []).map(normalizeEngineCard),
      playable_cards: hand?.playable_cards || [],
      skill_code: selfPlayer?.skill_code || 'none',
      skill_name: selfPlayer?.skill_name || '',
      is_my_turn: Boolean(hand?.is_my_turn),
    },
    opponents: {
      top: opponentLayout.slots.top,
      left: opponentLayout.slots.left,
      right: opponentLayout.slots.right,
      __targets: opponentLayout.targets,
    },
    discard: {
      top_card: normalizeEngineCard(state.discard_pile_top || currentDiscardCard.value),
    },
    turn: {
      current_player: currentPlayer ? formatPlayerDisplayName(currentPlayer) : '',
      direction: state.is_clockwise ? '順時針' : '逆時針',
      color: normalizeEngineColor(state.current_color),
      draw_penalty: state.draw_penalty || 0,
      current_turn_started_at: state.current_turn_started_at,
      turn_time_limit_seconds: state.turn_time_limit_seconds,
    },
    state: {
      game_start_time: state.game_start_time,
      time_limit_seconds: state.time_limit_seconds,
    },
  });

  if (state.phase === 'finished' && state.winners?.length && !showGameOverModal.value) {
    handleGameEnded({ final_rankings: state.winners, winner: state.winners[0]?.player_id });
  }
}

function handleMatchResults(results) {
  if (!Array.isArray(results)) return;
  matchResults.value = results;
}

function roleFromPlayer(player) {
  const skillCode = String(player?.skill_code || '').toLowerCase();
  const skillName = String(player?.skill_name || '');
  const roleByName = {
    占卜師: roleByCode.seer,
    巫師: roleByCode.painter,
    魔法師: roleByCode.painter,
    斥侯: roleByCode.scout,
    偵查者: roleByCode.scout,
    女皇: roleByCode.queen,
    皇后: roleByCode.queen,
  };

  return roleByCode[skillCode] || roleByName[skillName] || roleByCode.none;
}

function formatPlayerDisplayName(player) {
  if (!player) {
    return '';
  }

  const labels = [];
  if (player.is_ai_replacement) {
    labels.push('AI代打');
  } else if (player.is_disconnected) {
    labels.push('離線');
  }

  if (player.settlement_penalty) {
    labels.push('結算處罰');
  }

  return labels.length ? `${player.name}（${labels.join('、')}）` : player.name;
}

function handleGameEnded(data) {
  stopLocalTurnCountdown();
  gameEndReasonText.value = formatGameEndReason(data.end_reason_text || data.end_reason || data.reason || '');
  const winnerId = data.winner ?? data.WINNER ?? data.winner_id;
  const rankingWinner = data.final_rankings?.[0];
  const winnerName = data.winner_name
    || data.player_name
    || rankingWinner?.player_name
    || playerNamesById.value[String(winnerId)]
    || (winnerId ? `玩家 ${winnerId}` : '未知玩家');

  winnerAnnouncement.value = `${winnerName} 獲勝`;
  finalRankings.value = (data.final_rankings || []).map((ranking, index) => ({
    rank: ranking.rank ?? index + 1,
    player_id: ranking.player_id,
    player_name: ranking.player_name || playerNamesById.value[String(ranking.player_id)] || `玩家 ${ranking.player_id}`,
    hand_size: ranking.hand_size,
    settlement_penalty: Boolean(ranking.settlement_penalty),
  }));
  showGameOverModal.value = true;
}

function formatGameEndReason(reason) {
  const reasonText = String(reason || '');
  const reasonMap = {
    forced_settlement: '房主已強制結算',
    timeout: '遊戲時間結束，進入強制結算',
    two_winners: '已有兩位玩家完成出牌',
    one_remaining: '只剩一位玩家未完成',
    last_player_remaining: '只剩一位玩家未完成',
  };

  return reasonMap[reasonText] || reasonText;
}

function updateLatestGameEvent(data) {
  const playerName = data.player_name
    || playerNamesById.value[String(data.player_id)]
    || (data.player_id ? `玩家 ${data.player_id}` : '玩家');

  if (data.type === 'card_played') {
    latestGameEvent.value = `${playerName} 出了 ${normalizeEngineCard(data.card_played || data.card_name || '')}`;
    return;
  }

  if (data.type === 'card_drawn') {
    const reasonText = data.reason === 'turn_timeout'
      ? '因超時'
      : data.reason === 'disconnect_turn_timeout'
        ? '因離線超時'
        : '';
    latestGameEvent.value = `${playerName} ${reasonText}抽了 ${data.count ?? 1} 張`;
    return;
  }

  if (data.type === 'skill_used') {
    latestGameEvent.value = `${playerName} 使用技能`;
    return;
  }

  if (data.type === 'game_ended') {
    latestGameEvent.value = '遊戲結束';
  }
}

function normalizeEngineColor(color) {
  const colorMap = {
    red: '紅',
    blue: '藍',
    yellow: '黃',
    green: '綠',
    black: '黑',
  };

  return colorMap[String(color || '').toLowerCase()] || color;
}

function normalizeEngineCard(cardName) {
  const raw = String(cardName || '').trim();
  const parts = raw.split(/\s+/);
  const color = normalizeEngineColor(parts[0]);
  const valueMap = {
    draw2: '+2',
    wild: '萬用',
    wild_draw4: '抽四',
    skip: '跳過',
    reverse: '反轉',
    steal_card: '偷牌',
    swap_hand: '換手',
    neighbor_swap: '鄰抽',
    target_draw2: '指抽二',
  };

  if (parts.length >= 2) {
    const value = valueMap[parts.slice(1).join('_').toLowerCase()] || parts.slice(1).join(' ');
    return color === '黑' ? value : `${color} ${value}`;
  }

  return valueMap[raw.toLowerCase()] || raw;
}

function buildOpponentLayout(players, selfPlayerId) {
  const emptySlot = { name: '等待中', card_count: 0, role: roleByCode.none };
  const totalPlayers = players.length;
  const selfIndex = players.findIndex((candidate) => String(candidate.player_id) === String(selfPlayerId));
  const slotByOffset = totalPlayers === 2
    ? { 1: 'top' }
    : totalPlayers === 3
      ? { 1: 'right', 2: 'top' }
      : { 1: 'right', 2: 'top', 3: 'left' };
  const labelBySlot = {
    top: '上方',
    left: '左方',
    right: '右方',
  };
  const slots = {
    top: emptySlot,
    left: emptySlot,
    right: emptySlot,
  };
  const targets = [];

  if (selfIndex === -1) {
    return { slots, targets };
  }

  for (let offset = 1; offset < totalPlayers; offset += 1) {
    const slot = slotByOffset[offset];
    if (!slot) {
      continue;
    }

    const player = players[(selfIndex + offset) % totalPlayers];
    const opponent = {
      player_id: player.player_id,
      name: formatPlayerDisplayName(player),
      card_count: player.hand_size ?? 0,
      target_index: players.findIndex((candidate) => String(candidate.player_id) === String(player.player_id)),
      role: roleFromPlayer(player),
      has_finished: Boolean(player.has_finished || player.finished_rank),
      finished_rank: player.finished_rank ?? null,
    };

    slots[slot] = opponent;
    if (!opponent.has_finished) {
      targets.push({
        slot: labelBySlot[slot],
        ...opponent,
      });
    }
  }

  return { slots, targets };
}

function getScoreChangeForPlayer(playerId) {
  const entry = matchResults.value.find((r) => String(r.user_id) === String(playerId) || String(r.user_id) === String(rankingPlayerIdFallback(playerId)));
  return entry ? entry.score_change : null;
}

function rankingPlayerIdFallback(playerId) {
  // In some payloads player_id may be string; try to resolve by name fallback if needed
  return playerId;
}

function formatScoreChange(value) {
  if (value === null || value === undefined) return '';
  return (value >= 0 ? `+${value} 獎盃` : `${value} 獎盃`);
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
    const nextHand = [...payload.player.hand];
    const previousSelectedCard = selectedCard.value;
    const handChanged = handSignature(playerCards.value) !== handSignature(nextHand);
    playerCards.value = nextHand;
    playableCardIndexes.value = payload.player.playable_cards || [];

    if (payload.player.skill_code) {
      playerSkillCode.value = String(payload.player.skill_code || 'none').toLowerCase();
    }

    if (payload.player.is_my_turn !== undefined) {
      isMyTurn.value = Boolean(payload.player.is_my_turn);
    }

    if (handChanged) {
      selectedCardIndex.value = findSelectedCardIndex(nextHand, previousSelectedCard);
    }
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

  if (payload.opponents) {
    opponentSlots.value = {
      top: {
        name: payload.opponents.top?.name || '等待中',
        card_count: payload.opponents.top?.card_count ?? 0,
        role: payload.opponents.top?.role || roleByCode.none,
      },
      left: {
        name: payload.opponents.left?.name || '等待中',
        card_count: payload.opponents.left?.card_count ?? 0,
        role: payload.opponents.left?.role || roleByCode.none,
      },
      right: {
        name: payload.opponents.right?.name || '等待中',
        card_count: payload.opponents.right?.card_count ?? 0,
        role: payload.opponents.right?.role || roleByCode.none,
      },
    };
    opponentTargets.value = payload.opponents.__targets || [
      { slot: '上方', ...payload.opponents.top },
      { slot: '左方', ...payload.opponents.left },
      { slot: '右方', ...payload.opponents.right },
    ].filter((opponent) => Number.isInteger(opponent.target_index));
  }

  if (payload.discard?.top_card) {
    currentDiscardCard.value = payload.discard.top_card;
    currentColor.value = colorFromCard(payload.discard.top_card);
  }

  if (payload.turn?.direction) {
    turnDirection.value = payload.turn.direction;
  }

  if (payload.turn?.current_player) {
    currentPlayerName.value = payload.turn.current_player;
  }

  if (payload.turn?.color || payload.turn?.current_color) {
    currentColor.value = payload.turn.color || payload.turn.current_color;
  }

  if (payload.turn?.draw_penalty !== undefined) {
    drawPenalty.value = Number(payload.turn.draw_penalty) || 0;
  }

  if (payload.state?.game_start_time) {
    gameStartedAt = payload.state.game_start_time;
    gameTimeLimitSeconds = payload.state.time_limit_seconds || gameTimeLimitSeconds;
    updateGameCountdown();
  }

  if (payload.turn?.current_turn_started_at) {
    if (payload.turn.current_turn_started_at !== currentTurnStartedAt) {
      currentTurnStartedAt = payload.turn.current_turn_started_at;
      syncTurnCountdown(
        payload.turn.current_turn_started_at,
        payload.turn.turn_time_limit_seconds || TURN_SECONDS,
        payload.turn.remaining_seconds,
      );
    } else if (typeof payload.turn.remaining_seconds === 'number') {
      remainingSeconds.value = Math.max(0, Math.min(payload.turn.turn_time_limit_seconds || TURN_SECONDS, payload.turn.remaining_seconds));
    }
  }
}

function syncTurnCountdown(startedAt, turnLimitSeconds = TURN_SECONDS, serverRemainingSeconds = null) {
  stopLocalTurnCountdown();
  if (!startedAt) {
    if (typeof serverRemainingSeconds === 'number') {
      remainingSeconds.value = Math.max(0, Math.min(turnLimitSeconds, serverRemainingSeconds));
    }
    return;
  }

  const startedAtMs = new Date(startedAt).getTime();
  const tick = () => {
    const elapsedSeconds = Number.isFinite(startedAtMs) ? Math.floor((Date.now() - startedAtMs) / 1000) : 0;
    const nextSeconds = Number.isFinite(turnLimitSeconds)
      ? Math.max(0, turnLimitSeconds - elapsedSeconds)
      : Math.max(0, TURN_SECONDS - elapsedSeconds);
    remainingSeconds.value = nextSeconds;
    updateGameCountdown();
  };

  tick();
  turnTimerId = window.setInterval(() => {
    if (showGameOverModal.value) {
      return;
    }
    tick();
  }, 1000);
}

function stopLocalTurnCountdown() {
  if (turnTimerId) {
    window.clearInterval(turnTimerId);
    turnTimerId = null;
  }
}

function updateGameCountdown() {
  if (!gameStartedAt) {
    return;
  }

  const startedAtMs = new Date(gameStartedAt).getTime();
  const elapsedSeconds = Number.isFinite(startedAtMs) ? Math.floor((Date.now() - startedAtMs) / 1000) : 0;
  gameRemainingSeconds.value = Math.max(0, gameTimeLimitSeconds - elapsedSeconds);
}

function handSignature(cards) {
  return cards.join('|');
}

function findSelectedCardIndex(cards, previousSelectedCard) {
  if (!previousSelectedCard) {
    return null;
  }

  if (cards[previousSelectedCard.index] === previousSelectedCard.name) {
    return previousSelectedCard.index;
  }

  const nextIndex = cards.indexOf(previousSelectedCard.name);
  return nextIndex === -1 ? null : nextIndex;
}

function submitGameAction(action, card = null, extraPayload = {}) {
  const payload = {
    action,
    card_index: card?.index ?? null,
    card_name: card?.name ?? null,
    ...extraPayload,
  };

  console.log('Prepared game action payload:', payload);
  // 樂觀更新：如果是玩家出牌，先在本地移除該張卡並更新棄牌頂
  if (action === 'play_card' && card && Number.isInteger(card.index)) {
    optimisticPlayLocal(card);
  }

  sendGameSocketAction(payload);

  selectedCardIndex.value = null;
  showColorPickerModal.value = false;
  showTargetPickerModal.value = false;
  showReturnCardPickerModal.value = false;
  pendingTargetIndex.value = null;
}

function optimisticPlayLocal(card) {
  try {
    const idx = Number(card.index);
    if (idx >= 0 && idx < playerCards.value.length) {
      // 移除該張手牌
      playerCards.value.splice(idx, 1);
      // 更新顯示的棄牌頂
      currentDiscardCard.value = card.name || currentDiscardCard.value;
      // 清除可出牌索引，避免重複出
      playableCardIndexes.value = [];
    }
  } catch (e) {
    console.error('optimisticPlayLocal failed', e);
  }
}

function requiresColorChoice(cardName) {
  return ['wild', 'wild_draw4'].includes(cardActionKind(cardName));
}

function requiresTargetChoice(cardName) {
  return ['swap_hand', 'target_draw2', 'steal_card'].includes(cardActionKind(cardName));
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
  closeGameSocket();
  window.location.assign('/lobby?left=1');
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

  if (requiresColorChoice(selectedCard.value.name)) {
    pendingColorAction.value = 'card';
    showColorPickerModal.value = true;
    return;
  }

  if (requiresTargetChoice(selectedCard.value.name)) {
    showTargetPickerModal.value = true;
    return;
  }

  submitGameAction('play_card', selectedCard.value);
}

function handleColorChoice(colorValue) {
  if (pendingColorAction.value === 'skill_painter') {
    submitSkillAction({ new_color: colorValue });
    pendingColorAction.value = 'card';
    return;
  }

  if (!selectedCard.value) {
    showColorPickerModal.value = false;
    pendingColorAction.value = 'card';
    return;
  }

  submitGameAction('play_card', selectedCard.value, {
    chosen_color: colorValue,
  });
}

function closeColorPicker() {
  showColorPickerModal.value = false;
  pendingColorAction.value = 'card';
}

function handleTargetChoice(targetIndex) {
  if (!selectedCard.value) {
    showTargetPickerModal.value = false;
    return;
  }

  if (cardActionKind(selectedCard.value.name) === 'steal_card') {
    pendingTargetIndex.value = targetIndex;
    showTargetPickerModal.value = false;
    showReturnCardPickerModal.value = true;
    return;
  }

  const payload = {
    target_player_index: targetIndex,
  };

  submitGameAction('play_card', selectedCard.value, payload);
}

function closeTargetPicker() {
  showTargetPickerModal.value = false;
}

function handleReturnCardChoice(returnCardIndex) {
  if (!selectedCard.value || pendingTargetIndex.value === null) {
    closeReturnCardPicker();
    return;
  }

  submitGameAction('play_card', selectedCard.value, {
    target_player_index: pendingTargetIndex.value,
    return_card_index: returnCardIndex,
  });
}

function closeReturnCardPicker() {
  showReturnCardPickerModal.value = false;
  pendingTargetIndex.value = null;
}

function handleDrawCard() {
  submitGameAction('draw_card');
}

function submitSkillAction(params = {}) {
  sendGameSocketAction({
    action: 'use_skill',
    params,
  });

  showColorPickerModal.value = false;
  showSkillDiscardPickerModal.value = false;
  pendingColorAction.value = 'card';
  selectedCardIndex.value = null;
}

function handleUseSkill() {
  if (!isMyTurn.value) {
    latestGameEvent.value = '還沒輪到你，不能使用技能';
    return;
  }

  const skillCode = playerSkillCode.value;

  if (skillCode === 'painter') {
    pendingColorAction.value = 'skill_painter';
    showColorPickerModal.value = true;
    return;
  }

  if (skillCode === 'scout') {
    showSkillDiscardPickerModal.value = true;
    return;
  }

  if (skillCode === 'seer') {
    // 目前後端技能需要 new_order。先提供預設順序，讓技能流程可用；
    // 後續若要做拖曳排序，可以把這裡改成自訂 new_order。
    submitSkillAction({ new_order: [0, 1, 2, 3] });
    return;
  }

  if (skillCode === 'queen') {
    submitSkillAction();
    return;
  }

  latestGameEvent.value = '目前角色沒有可使用的技能';
}

function handleSkillDiscardChoice(cardIndex) {
  submitSkillAction({ discard_card_index: cardIndex });
}

function closeSkillDiscardPicker() {
  showSkillDiscardPickerModal.value = false;
}

function handleForceSettlement() {
  if (!window.confirm('確定要強制結算目前這局嗎？')) {
    return;
  }

  sendGameSocketAction({ action: 'force_settlement' });
  latestGameEvent.value = '已送出強制結算請求';
  showSettingsModal.value = false;
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
});

onBeforeUnmount(() => {
  stopLocalTurnCountdown();
  closeGameSocket();
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
      <button v-if="isTestMode" class="tool-btn debug-btn" type="button" @click.stop="openDebugPage">
        <span class="tool-icon">◫</span>
        <span>監測</span>
      </button>
      <button class="tool-btn" type="button" @click.stop="showSettingsModal = true">
        <span class="tool-icon">⚙</span>
        <span>設定</span>
      </button>
      <button class="tool-btn" type="button" @click.stop="handleExitRoom">
        <span class="tool-icon">↪</span>
        <span>退出</span>
      </button>
    </div>

    <section class="opponent opponent-top" :aria-label="opponentSlots.top.name">
      <div class="role-panel">
        <div class="role-card image-fill" :style="imageStyle(opponentSlots.top.role?.image || roleByCode.none.image)" aria-label="角色"></div>
        <strong class="role-name">{{ opponentSlots.top.role?.name || '角色' }}</strong>
      </div>
      <div class="opponent-name">{{ opponentSlots.top.name }}</div>
      <div class="opponent-card-summary">
        <div class="game-card card-back image-fill" :style="imageStyle(cardBackUrl)" aria-label="卡背"></div>
        <span class="card-count-badge">{{ topCardCount }}</span>
      </div>
    </section>

    <section class="opponent opponent-left" :aria-label="opponentSlots.left.name">
      <div class="role-panel">
        <div class="role-card image-fill" :style="imageStyle(opponentSlots.left.role?.image || roleByCode.none.image)" aria-label="角色"></div>
        <strong class="role-name">{{ opponentSlots.left.role?.name || '角色' }}</strong>
      </div>
      <div class="opponent-name">{{ opponentSlots.left.name }}</div>
      <div class="opponent-card-summary">
        <div class="game-card side-summary-card side-card-horizontal image-fill" :style="imageStyle(cardBackUrl)" aria-label="卡背"></div>
        <span class="card-count-badge">{{ leftCardCount }}</span>
      </div>
    </section>

    <section class="opponent opponent-right" :aria-label="opponentSlots.right.name">
      <div class="role-panel">
        <div class="role-card image-fill" :style="imageStyle(opponentSlots.right.role?.image || roleByCode.none.image)" aria-label="角色"></div>
        <strong class="role-name">{{ opponentSlots.right.role?.name || '角色' }}</strong>
      </div>
      <div class="opponent-name">{{ opponentSlots.right.name }}</div>
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
          <span>整局時間</span>
          <strong>{{ gameRemainingSeconds }}</strong>
        </div>
        <div class="turn-row">
          <span>當前顏色</span>
          <strong class="current-color">
            <span class="color-dot" :style="currentColorStyle"></span>
            {{ currentColor }}
          </strong>
        </div>
        <div v-if="drawPenalty > 0" class="turn-row penalty-row">
          <span>累積抽牌</span>
          <strong>+{{ drawPenalty }}</strong>
        </div>
        <div v-if="drawPenalty > 0" class="penalty-hint">
          {{ drawPenaltyHint }}
        </div>
        <div class="turn-row">
          <span>當前玩家</span>
          <strong>{{ currentPlayerName }}</strong>
        </div>
        <div class="turn-row">
          <span>方向</span>
          <strong>{{ turnDirection === '順時針' ? '↻' : '↺' }} {{ turnDirection }}</strong>
        </div>
        <div v-if="latestGameEvent" class="event-hint">
          {{ latestGameEvent }}
        </div>
      </div>
    </section>

    <section class="player-area" aria-label="玩家手牌">
      <div class="player-info">
        <div class="role-panel">
          <div class="role-card image-fill" :style="imageStyle(playerRole.image)" aria-label="角色"></div>
          <strong class="role-name">{{ playerRole.name }}</strong>
        </div>
        <div class="opponent-name">{{ playerName }}</div>
        <div class="card-count">{{ playerCards.length }}張</div>
      </div>
      <div class="player-hand">
        <button
          v-for="(card, index) in playerCards"
          :key="`${card}-${index}`"
          class="game-card player-card"
          :class="{
            'is-selected': selectedCardIndex === index,
            'is-playable': playableCardIndexes.includes(index),
            'is-blocked-by-penalty': drawPenalty > 0 && !playableCardIndexes.includes(index),
            'image-fill': cardAssetUrl(card),
          }"
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
        {{ playButtonLabel }}
      </button>
      <button class="action-btn" type="button" @click="handleDrawCard">{{ drawButtonLabel }}</button>
      <button class="action-btn" type="button" :disabled="!isMyTurn" @click="handleUseSkill">{{ skillButtonLabel }}</button>
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

        <button class="danger-action-btn" type="button" @click="handleForceSettlement">
          強制結算
        </button>
      </section>
    </div>

    <div v-if="showColorPickerModal" class="settings-backdrop" @click.self="closeColorPicker">
      <section class="color-picker-modal" aria-label="選擇顏色">
        <header class="settings-header">
          <h2>選擇顏色</h2>
          <button class="settings-close" type="button" @click="closeColorPicker">×</button>
        </header>

        <div class="selected-wild-card">
          {{ pendingColorAction === 'skill_painter' ? '選擇技能要更換的顏色' : selectedCard?.name }}
        </div>

        <div class="color-choice-grid">
          <button
            v-for="color in colorOptions"
            :key="color.value"
            class="color-choice-btn"
            :class="color.className"
            type="button"
            @click="handleColorChoice(color.value)"
          >
            <span class="color-choice-dot"></span>
            <span>{{ color.label }}</span>
          </button>
        </div>
      </section>
    </div>

    <div v-if="showTargetPickerModal" class="settings-backdrop" @click.self="closeTargetPicker">
      <section class="target-picker-modal" aria-label="選擇對手">
        <header class="settings-header">
          <h2>選擇對手</h2>
          <button class="settings-close" type="button" @click="closeTargetPicker">×</button>
        </header>

        <div class="selected-wild-card">
          {{ selectedCard?.name }}
        </div>

        <div class="target-choice-list">
          <button
            v-for="opponent in opponentTargets"
            :key="opponent.target_index"
            class="target-choice-btn"
            type="button"
            @click="handleTargetChoice(opponent.target_index)"
          >
            <span>{{ opponent.slot }}</span>
            <strong>{{ opponent.name || 'AI 玩家' }}</strong>
            <span>{{ opponent.card_count ?? 0 }}張</span>
          </button>
        </div>
      </section>
    </div>

    <div v-if="showReturnCardPickerModal" class="settings-backdrop" @click.self="closeReturnCardPicker">
      <section class="target-picker-modal" aria-label="選擇要還給對手的手牌">
        <header class="settings-header">
          <h2>選擇還牌</h2>
          <button class="settings-close" type="button" @click="closeReturnCardPicker">×</button>
        </header>

        <div class="selected-wild-card">
          {{ selectedCard?.name }}
        </div>

        <div class="target-choice-list">
          <p v-if="!returnCardOptions.length" class="empty-choice-hint">
            目前沒有可還給對手的手牌。
          </p>
          <button
            v-for="card in returnCardOptions"
            :key="`return-${card.name}-${card.index}`"
            class="target-choice-btn"
            type="button"
            @click="handleReturnCardChoice(card.index)"
          >
            <span>#{{ card.index }}</span>
            <strong>{{ displayCardLabel(card.name) }}</strong>
            <span>還牌</span>
          </button>
        </div>
      </section>
    </div>

    <div v-if="showSkillDiscardPickerModal" class="settings-backdrop" @click.self="closeSkillDiscardPicker">
      <section class="target-picker-modal" aria-label="選擇要丟棄的手牌">
        <header class="settings-header">
          <h2>選擇要丟棄的手牌</h2>
          <button class="settings-close" type="button" @click="closeSkillDiscardPicker">×</button>
        </header>

        <div class="selected-wild-card">
          斥侯技能：丟棄一張手牌，獲得牌堆最上方功能牌
        </div>

        <div class="target-choice-list">
          <button
            v-for="(card, index) in playerCards"
            :key="`skill-discard-${card}-${index}`"
            class="target-choice-btn"
            type="button"
            @click="handleSkillDiscardChoice(index)"
          >
            <span>#{{ index + 1 }}</span>
            <strong>{{ displayCardLabel(card) }}</strong>
            <span>丟棄</span>
          </button>
        </div>
      </section>
    </div>

    <div v-if="showGameOverModal" class="settings-backdrop">
      <section class="game-over-modal" aria-label="遊戲結束">
        <header class="settings-header">
          <h2>遊戲結束</h2>
        </header>

        <strong class="winner-title">{{ winnerAnnouncement }}</strong>
        <p v-if="gameEndReasonText" class="game-end-reason">結束原因：{{ gameEndReasonText }}</p>

        <div v-if="finalRankings.length" class="ranking-list">
          <div v-for="ranking in finalRankings" :key="`${ranking.rank}-${ranking.player_id}`" class="ranking-row">
            <span class="ranking-rank">#{{ ranking.rank }}</span>
            <span class="trophy-change">
              {{ matchResults.length ? formatScoreChange(getScoreChangeForPlayer(ranking.player_id)) : '' }}
            </span>
            <strong>{{ ranking.player_name }}{{ ranking.settlement_penalty ? '（結算處罰）' : '' }}</strong>
            <span v-if="ranking.hand_size !== undefined">{{ ranking.hand_size }}張</span>
          </div>
        </div>

        <button class="action-btn game-over-exit" type="button" @click="handleExitRoom">回到大廳</button>
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
  width: min(680px, calc(100vw - 360px));
  min-width: 520px;
  height: 230px;
  transform: translateX(-50%);
  display: grid;
  grid-template-columns: var(--card-width) 230px var(--card-width);
  grid-template-areas: "deck info discard";
  align-items: start;
  justify-content: center;
  gap: 64px;
}

.deck-stack {
  grid-area: deck;
  position: relative;
  justify-self: end;
  margin-top: 8px;
}

.deck-card {
  position: relative;
  width: var(--card-width);
  height: var(--card-height);
}

.discard-pile {
  grid-area: discard;
  position: relative;
  width: var(--card-width);
  height: var(--card-height);
  justify-self: start;
  margin-top: 8px;
}

.pile-card {
  width: var(--card-width);
  height: var(--card-height);
  font-weight: 800;
}

.turn-panel {
  grid-area: info;
  position: relative;
  width: 230px;
  justify-self: center;
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

.penalty-row {
  color: #fecaca;
}

.penalty-row strong {
  color: #fca5a5;
}

.penalty-hint {
  padding: 7px 0 8px;
  border-bottom: 1px solid rgba(248, 250, 252, 0.35);
  color: #fde68a;
  font-size: 13px;
  line-height: 1.3;
  text-align: right;
}

.event-hint {
  padding-top: 8px;
  color: #bfdbfe;
  font-size: 13px;
  line-height: 1.35;
  text-align: right;
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

.player-card.is-playable {
  border-color: #86efac;
  box-shadow: 0 0 0 2px rgba(134, 239, 172, 0.78);
}

.player-card.is-blocked-by-penalty {
  opacity: 0.58;
}

.player-card.is-selected.is-playable {
  border-color: #fde68a;
  box-shadow: 0 0 0 3px rgba(253, 230, 138, 0.95), 0 14px 26px rgba(0, 0, 0, 0.42);
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

.color-picker-modal {
  width: min(360px, calc(100vw - 32px));
  display: grid;
  gap: 14px;
  padding: 18px;
  border: 1px solid rgba(248, 250, 252, 0.8);
  border-radius: 8px;
  color: #f8fafc;
  background: rgba(8, 3, 18, 0.96);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
}

.target-picker-modal {
  width: min(380px, calc(100vw - 32px));
  display: grid;
  gap: 14px;
  padding: 18px;
  border: 1px solid rgba(248, 250, 252, 0.8);
  border-radius: 8px;
  color: #f8fafc;
  background: rgba(8, 3, 18, 0.96);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
}

.game-over-modal {
  width: min(560px, calc(100vw - 32px));
  display: grid;
  gap: 16px;
  padding: 20px;
  border: 1px solid rgba(248, 250, 252, 0.86);
  border-radius: 8px;
  color: #f8fafc;
  background: rgba(8, 3, 18, 0.96);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
}

.winner-title {
  min-height: 56px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(248, 250, 252, 0.24);
  border-radius: 8px;
  background: rgba(248, 250, 252, 0.08);
  font-size: 24px;
  text-align: center;
}

.ranking-list {
  display: grid;
  gap: 8px;
}

.ranking-row {
  min-height: 42px;
  display: grid;
  grid-template-columns: 48px 88px minmax(0, 1fr) 56px;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  border: 1px solid rgba(248, 250, 252, 0.26);
  border-radius: 8px;
  background: rgba(248, 250, 252, 0.06);
}

.ranking-rank,
.trophy-change {
  white-space: nowrap;
}

.trophy-change {
  color: #facc15;
}

.ranking-row strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.game-over-exit {
  width: 100%;
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

.danger-action-btn {
  min-height: 42px;
  border: 1px solid rgba(248, 113, 113, 0.82);
  border-radius: 8px;
  color: #fecaca;
  background: rgba(127, 29, 29, 0.42);
  cursor: pointer;
  font-size: 15px;
  font-weight: 800;
}

.danger-action-btn:hover {
  border-color: rgba(254, 202, 202, 0.95);
  background: rgba(153, 27, 27, 0.62);
}

.selected-wild-card {
  min-height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(248, 250, 252, 0.24);
  border-radius: 6px;
  background: rgba(248, 250, 252, 0.08);
  font-size: 16px;
  font-weight: 700;
}

.color-choice-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.color-choice-btn {
  min-height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border: 1px solid rgba(248, 250, 252, 0.62);
  border-radius: 8px;
  color: #f8fafc;
  background: rgba(5, 2, 16, 0.72);
  cursor: pointer;
  font-size: 16px;
  font-weight: 700;
}

.color-choice-btn:hover {
  background: rgba(38, 28, 66, 0.9);
}

.color-choice-dot {
  width: 18px;
  height: 18px;
  border: 1px solid rgba(248, 250, 252, 0.82);
  border-radius: 999px;
}

.color-choice-btn.red .color-choice-dot {
  background: #dc2626;
}

.color-choice-btn.blue .color-choice-dot {
  background: #2563eb;
}

.color-choice-btn.yellow .color-choice-dot {
  background: #facc15;
}

.color-choice-btn.green .color-choice-dot {
  background: #16a34a;
}

.target-choice-list {
  display: grid;
  gap: 10px;
}

.empty-choice-hint {
  margin: 0;
  padding: 12px;
  border: 1px solid rgba(248, 250, 252, 0.22);
  border-radius: 8px;
  color: #cbd5e1;
  background: rgba(248, 250, 252, 0.08);
  text-align: center;
}

.target-choice-btn {
  min-height: 54px;
  display: grid;
  grid-template-columns: 56px 1fr 48px;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  border: 1px solid rgba(248, 250, 252, 0.62);
  border-radius: 8px;
  color: #f8fafc;
  background: rgba(5, 2, 16, 0.72);
  cursor: pointer;
  font-size: 15px;
  text-align: left;
}

.target-choice-btn:hover {
  background: rgba(38, 28, 66, 0.9);
}

.target-choice-btn strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
    width: calc(100vw - 40px);
    min-width: 0;
    grid-template-columns: var(--card-width) minmax(190px, 230px) var(--card-width);
    gap: 24px;
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
