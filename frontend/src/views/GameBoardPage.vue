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
const boardPageEl = ref(null);
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
const showSeerOrderModal = ref(false);
const showGameOverModal = ref(false);
const boardScale = ref(1);
let gameSocket = null;
let leaveGameResolver = null;
let turnTimerId = null;
let currentTurnStartedAt = null;
let gameStartedAt = null;
let gameTimeLimitSeconds = 15 * 60;
let suppressPageUnloadLeave = false;
let pageUnloadLeaveSent = false;

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
const canUseSkill = ref(false);
const skillDisabledReason = ref('');
const seerPreviewCards = ref([]);
const seerOrderCards = ref([]);
const seerSelectedOrder = ref([]);
const isSkillPreviewLoading = ref(false);
const seerOrderTouched = ref(false);
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

const selectedCardIsPlayable = computed(() => (
  selectedCardIndex.value !== null
  && isMyTurn.value
  && playableCardIndexes.value.includes(selectedCardIndex.value)
));

const canDrawCard = computed(() => isMyTurn.value);

const canUseSkillAction = computed(() => (
  Boolean(canUseSkill.value)
));

const canSubmitSeerOrder = computed(() => {
  const total = seerPreviewCards.value.length;
  const selected = seerSelectedOrder.value.length;

  if (total === 0) {
    return false;
  }

  if (!seerOrderTouched.value) {
    return true;
  }

  return selected === total;
});

const returnCardOptions = computed(() => (
  playerCards.value
    .map((name, index) => ({ name, index }))
    .filter((card) => card.index !== selectedCard.value?.index)
));

function seerCardDisplayName(card) {
  if (!card) {
    return '';
  }

  if (typeof card === 'string') {
    return normalizeDisplayCardName(card);
  }

  const colorMap = {
    red: '紅',
    blue: '藍',
    yellow: '黃',
    green: '綠',
    black: '',
  };
  const valueMap = {
    draw2: '+2',
    wild: '萬用',
    wild_draw4: '抽四',
    skip: '跳過',
    reverse: '反轉',
    swap_hand: '換手',
    steal_card: '偷牌',
    neighbor_swap: '鄰抽',
    target_draw2: '指抽二',
  };

  const color = colorMap[String(card.color || '').toLowerCase()] ?? '';
  const value = valueMap[String(card.value || card.type || '').toLowerCase()] || card.value || card.type || '';
  return normalizeDisplayCardName(color ? `${color} ${value}` : value);
}

function seerCardSnapshot(card) {
  return {
    color: String(card?.color || ''),
    value: String(card?.value || ''),
    type: String(card?.type || ''),
  };
}

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

    if (data.type === 'game_left') {
      if (leaveGameResolver) {
        leaveGameResolver(data);
        leaveGameResolver = null;
      }
      return;
    }

    if (data.type === 'game_ended') {
      console.log('Received game event:', data);
      updateLatestGameEvent(data);
      handleGameEnded(data);
      return;
    }

    if (data.type === 'skill_preview') {
      handleSkillPreview(data);
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
        isSkillPreviewLoading.value = false;
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
  if (leaveGameResolver) {
    leaveGameResolver(null);
    leaveGameResolver = null;
  }

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

function canSelectCard(index) {
  return isMyTurn.value && playableCardIndexes.value.includes(index);
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
      can_draw: Boolean(hand?.can_draw),
      can_use_skill: Boolean(hand?.can_use_skill),
      skill_disabled_reason: hand?.skill_disabled_reason || '',
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
  const sortedRankings = [...(data.final_rankings || [])].sort((a, b) => {
    const rankA = Number(a.rank ?? 999);
    const rankB = Number(b.rank ?? 999);
    return rankA - rankB;
  });
  const rankingWinner = sortedRankings.find((ranking) => Number(ranking.rank) === 1) || sortedRankings[0];
  const winnerName = rankingWinner?.player_name
    || data.winner_name
    || data.player_name
    || playerNamesById.value[String(winnerId)]
    || (winnerId ? `玩家 ${winnerId}` : '未知玩家');

  winnerAnnouncement.value = `${winnerName} 獲勝`;
  finalRankings.value = sortedRankings.map((ranking, index) => ({
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

    if (payload.player.can_use_skill !== undefined) {
      canUseSkill.value = Boolean(payload.player.can_use_skill);
    }

    skillDisabledReason.value = payload.player.skill_disabled_reason || '';

    if (handChanged) {
      selectedCardIndex.value = findSelectedCardIndex(nextHand, previousSelectedCard);
    }

    if (
      selectedCardIndex.value !== null
      && (!isMyTurn.value || !playableCardIndexes.value.includes(selectedCardIndex.value))
    ) {
      selectedCardIndex.value = null;
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
  sendGameSocketAction(payload);

  selectedCardIndex.value = null;
  showColorPickerModal.value = false;
  showTargetPickerModal.value = false;
  showReturnCardPickerModal.value = false;
  pendingTargetIndex.value = null;
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

function sendLeaveRoomBeacon(reason) {
  if (!roomId.value) {
    return;
  }

  const url = `${API_BASE}/rooms/${roomId.value}/leave/`;
  const payload = JSON.stringify({ reason });

  if (navigator.sendBeacon) {
    const blob = new Blob([payload], { type: 'application/json' });
    navigator.sendBeacon(url, blob);
    return;
  }

  fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: payload,
    keepalive: true,
  }).catch(() => {});
}

function sendLeaveGameSocketOnUnload() {
  if (!gameSocket || gameSocket.readyState !== WebSocket.OPEN) {
    return;
  }

  try {
    gameSocket.send(JSON.stringify({ action: 'leave_game' }));
  } catch (err) {
    console.warn('Failed to send leave_game before page unload:', err);
  }
}

function leaveGameOnPageUnload() {
  if (suppressPageUnloadLeave || pageUnloadLeaveSent || !roomId.value) {
    return;
  }

  pageUnloadLeaveSent = true;

  if (showGameOverModal.value) {
    sendLeaveRoomBeacon('game_over_page_unload');
    return;
  }

  // 關閉遊戲頁要盡量等同按下「退出」：先通知遊戲 WS 執行 leave_game，
  // 讓後端可把玩家改成 AI 代打；再用 keepalive/beacon 補一個房間離開請求。
  sendLeaveGameSocketOnUnload();
  sendLeaveRoomBeacon('game_page_unload');
}

function handleGameBeforeUnload(event) {
  if (suppressPageUnloadLeave || showGameOverModal.value) {
    return;
  }

  event.preventDefault();
  event.returnValue = '確定要離開本局遊戲嗎？離開後本局會由 AI 代打，你將無法重新加入。';
}

async function handleExitRoom() {
  if (showGameOverModal.value) {
    await leaveRoomAfterGame();
    return;
  }

  const confirmed = window.confirm('確定要離開本局遊戲嗎？離開後本局會由 AI 代打，你將無法重新加入，結算時會標記離線處罰。');
  if (!confirmed) {
    return;
  }

  await leaveCurrentGame();
  suppressPageUnloadLeave = true;
  pageUnloadLeaveSent = true;
  closeGameSocket();
  window.location.assign('/lobby?left=1');
}

async function leaveRoomAfterGame() {
  // 結算後按「回到大廳」代表放棄下一局，只移除自己。
  // 其他玩家若按「再來一局」仍會留在原房間。
  try {
    await leaveRoom();
  } catch (err) {
    console.warn('Failed to leave room after game ended:', err);
  }

  suppressPageUnloadLeave = true;
  pageUnloadLeaveSent = true;
  closeGameSocket();
  window.location.assign('/lobby');
}

function returnToRoomForNextRound() {
  // 結算後按「再來一局」代表保留自己的 RoomMember。
  // 回到 lobby 後 current-room API 會把玩家帶回原本房間。
  suppressPageUnloadLeave = true;
  closeGameSocket();
  window.location.assign('/lobby');
}

function getCardDisabledReason(index) {
  if (!isMyTurn.value) {
    return '還沒輪到你，不能出牌';
  }

  if (!playableCardIndexes.value.includes(index)) {
    return drawPenalty.value > 0
      ? `目前累加抽牌中，請接 +2 / +4 或抽 ${drawPenalty.value} 張`
      : '這張牌目前不能出';
  }

  return '';
}

function leaveCurrentGame() {
  if (!gameSocket || gameSocket.readyState !== WebSocket.OPEN) {
    return Promise.resolve(null);
  }

  return new Promise((resolve) => {
    leaveGameResolver = resolve;
    gameSocket.send(JSON.stringify({ action: 'leave_game' }));
    window.setTimeout(() => {
      if (leaveGameResolver === resolve) {
        leaveGameResolver = null;
        resolve(null);
      }
    }, 1500);
  });
}

function handleCardClick(index) {
  if (!canSelectCard(index)) {
    latestGameEvent.value = getCardDisabledReason(index);
    return;
  }

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

  if (!isMyTurn.value) {
    latestGameEvent.value = '還沒輪到你，不能出牌';
    return;
  }

  if (!selectedCardIsPlayable.value) {
    latestGameEvent.value = getCardDisabledReason(selectedCard.value.index);
    selectedCardIndex.value = null;
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
    if (!canUseSkillAction.value) {
      latestGameEvent.value = '目前不能使用技能';
      closeColorPicker();
      return;
    }

    submitSkillAction({ new_color: colorValue });
    pendingColorAction.value = 'card';
    return;
  }

  if (!selectedCard.value || !selectedCardIsPlayable.value) {
    showColorPickerModal.value = false;
    pendingColorAction.value = 'card';
    latestGameEvent.value = selectedCard.value ? '這張牌目前不能出' : latestGameEvent.value;
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
  if (!selectedCard.value || !selectedCardIsPlayable.value) {
    showTargetPickerModal.value = false;
    latestGameEvent.value = selectedCard.value ? '這張牌目前不能出' : latestGameEvent.value;
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
  if (!selectedCard.value || !selectedCardIsPlayable.value || pendingTargetIndex.value === null) {
    latestGameEvent.value = selectedCard.value && !selectedCardIsPlayable.value
      ? '這張牌目前不能出'
      : latestGameEvent.value;
    closeReturnCardPicker();
    return;
  }

  const adjustedReturnCardIndex =
    returnCardIndex > selectedCard.value.index
      ? returnCardIndex - 1
      : returnCardIndex;

  submitGameAction('play_card', selectedCard.value, {
    target_player_index: pendingTargetIndex.value,
    return_card_index: adjustedReturnCardIndex,
  });
}

function closeReturnCardPicker() {
  showReturnCardPickerModal.value = false;
  pendingTargetIndex.value = null;
}

function handleDrawCard() {
  if (!canDrawCard.value) {
    latestGameEvent.value = '還沒輪到你，不能抽牌';
    return;
  }

  submitGameAction('draw_card');
}

function submitSkillAction(params = {}) {
  sendGameSocketAction({
    action: 'use_skill',
    params,
  });

  showColorPickerModal.value = false;
  showSkillDiscardPickerModal.value = false;
  showSeerOrderModal.value = false;
  pendingColorAction.value = 'card';
  selectedCardIndex.value = null;
}

function requestSkillPreview() {
  isSkillPreviewLoading.value = true;
  sendGameSocketAction({
    action: 'preview_skill',
  });
}

function handleSkillPreview(data) {
  isSkillPreviewLoading.value = false;
  if (String(data.skill_code || '').toLowerCase() !== 'seer') {
    latestGameEvent.value = data.message || '技能預覽完成';
    return;
  }

  seerPreviewCards.value = (data.cards_viewed || []).map((card, index) => ({
    ...card,
    originalIndex: index,
    displayName: seerCardDisplayName(card),
  }));
  seerOrderCards.value = [...seerPreviewCards.value];
  seerSelectedOrder.value = [];
  seerOrderTouched.value = false;
  showSeerOrderModal.value = true;
  latestGameEvent.value = '占卜師看見牌庫頂4張牌';
}

function seerSelectionNumber(card) {
  const selectedIndex = seerSelectedOrder.value.indexOf(card.originalIndex);
  return selectedIndex >= 0 ? selectedIndex + 1 : null;
}

function toggleSeerCardSelection(card) {
  seerOrderTouched.value = true;
  const selectedIndex = seerSelectedOrder.value.indexOf(card.originalIndex);
  if (selectedIndex >= 0) {
    seerSelectedOrder.value = seerSelectedOrder.value.filter((index) => index !== card.originalIndex);
    return;
  }

  if (seerSelectedOrder.value.length >= seerPreviewCards.value.length) {
    return;
  }

  seerSelectedOrder.value = [...seerSelectedOrder.value, card.originalIndex];
}

function submitSeerOrder() {
  if (seerOrderTouched.value && seerSelectedOrder.value.length !== seerPreviewCards.value.length) {
    latestGameEvent.value = '已開始排序時，請依序選完全部牌才能送出';
    return;
  }

  const finalOrder = seerOrderTouched.value
    ? seerSelectedOrder.value
    : seerOrderCards.value.map((card) => card.originalIndex);

  submitSkillAction({
    new_order: finalOrder,
    preview_cards: seerPreviewCards.value.map(seerCardSnapshot),
  });

  seerPreviewCards.value = [];
  seerOrderCards.value = [];
  seerSelectedOrder.value = [];
  seerOrderTouched.value = false;
}

function closeSeerOrderModal() {
  showSeerOrderModal.value = false;
  isSkillPreviewLoading.value = false;
  seerSelectedOrder.value = [];
}

function handleUseSkill() {
  if (!canUseSkill.value) {
    latestGameEvent.value = skillDisabledReason.value || '目前不能使用技能';
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
    requestSkillPreview();
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

function readBoardCssNumber(variableName, fallback) {
  if (!boardPageEl.value) {
    return fallback;
  }

  const rawValue = getComputedStyle(boardPageEl.value).getPropertyValue(variableName).trim();
  const parsed = Number.parseFloat(rawValue);
  return Number.isFinite(parsed) ? parsed : fallback;
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
  const visibleCornerGap = readBoardCssNumber('--hand-fan-corner-gap', 18);
  const maxRotationFloor = readBoardCssNumber('--hand-fan-max-rotation-floor', 46);
  const maxRotationStart = readBoardCssNumber('--hand-fan-max-rotation-start', 84);
  const maxRotationDecay = readBoardCssNumber('--hand-fan-max-rotation-decay', 3);
  const minReadableStepFloor = readBoardCssNumber('--hand-fan-min-step-floor', 4.8);
  const minReadableStepStart = readBoardCssNumber('--hand-fan-min-step-start', 13);
  const minReadableStepDecay = readBoardCssNumber('--hand-fan-min-step-decay', 0.7);
  const fanStepCap = readBoardCssNumber('--hand-fan-step-cap', 16);
  const sideDropMax = readBoardCssNumber('--hand-fan-side-drop', 28);
  const extraCardCount = Math.max(0, count - 8);
  const maxRotation = Math.max(maxRotationFloor, maxRotationStart - extraCardCount * maxRotationDecay);
  const minReadableStep = Math.max(minReadableStepFloor, minReadableStepStart - extraCardCount * minReadableStepDecay);
  const fullFanStep = count <= 1 ? 0 : (maxRotation * 2) / (count - 1);
  const step = count <= 1 ? 0 : Math.max(minReadableStep, Math.min(fanStepCap, fullFanStep));
  const angle = (index - center) * step;
  const offset = (index - center) * visibleCornerGap;
  const edgeRatio = Math.abs(index - center) / Math.max(center, 1);
  const sideDrop = edgeRatio * sideDropMax;

  return {
    bottom: `${-sideDrop}px`,
    zIndex: index + 1,
    '--rotation': `${angle}deg`,
    '--fan-offset': `${offset}px`,
  };
}

onMounted(() => {
  window.addEventListener('beforeunload', handleGameBeforeUnload);
  window.addEventListener('pagehide', leaveGameOnPageUnload);
  setupGameServerConnection();
});

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', handleGameBeforeUnload);
  window.removeEventListener('pagehide', leaveGameOnPageUnload);
  stopLocalTurnCountdown();
  closeGameSocket();
});
</script>

<template>
  <main ref="boardPageEl" class="game-board-page">
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
            'is-playable': canSelectCard(index),
            'is-disabled': !canSelectCard(index),
            'is-blocked-by-penalty': drawPenalty > 0 && !playableCardIndexes.includes(index),
            'image-fill': cardAssetUrl(card),
          }"
          :aria-pressed="selectedCardIndex === index"
          :data-selected="selectedCardIndex === index ? 'true' : 'false'"
          :style="{ ...playerCardStyle(index), ...cardImageStyle(card) }"
          type="button"
          :disabled="!canSelectCard(index)"
          :title="getCardDisabledReason(index)"
          @click="handleCardClick(index)"
        >
          <span class="card-label">{{ displayCardLabel(card) }}</span>
        </button>
      </div>
    </section>

    <aside class="action-panel" aria-label="玩家操作">
      <button class="action-btn" type="button" :disabled="!selectedCard || !selectedCardIsPlayable" @click="handlePlayButton">
        {{ playButtonLabel }}
      </button>
      <button class="action-btn" type="button" :disabled="!canDrawCard" @click="handleDrawCard">{{ drawButtonLabel }}</button>
      <button class="action-btn" type="button" :disabled="!canUseSkillAction || isSkillPreviewLoading" :title="skillDisabledReason" @click="handleUseSkill">{{ skillButtonLabel }}</button>
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

    <div v-if="showSeerOrderModal" class="settings-backdrop">
      <section class="seer-order-modal" aria-label="占卜師排列牌庫頂端">
        <header class="settings-header">
          <h2>占卜師</h2>
        </header>

        <div class="selected-wild-card">
          不調整順序可直接確認；若開始點牌排序，請依序選完全部牌。
        </div>

        <div class="seer-card-grid">
          <button
            v-for="card in seerOrderCards"
            :key="`seer-${card.originalIndex}-${card.displayName}`"
            class="seer-card-choice"
            :class="{ 'is-selected': seerSelectionNumber(card) }"
            type="button"
            @click="toggleSeerCardSelection(card)"
          >
            <div
              class="game-card seer-preview-card"
              :class="{ 'image-fill': cardAssetUrl(card.displayName) }"
              :style="cardImageStyle(card.displayName)"
            >
              <span class="card-label">{{ displayCardLabel(card.displayName) }}</span>
            </div>
            <span v-if="seerSelectionNumber(card)" class="seer-order-badge">{{ seerSelectionNumber(card) }}</span>
            <strong>{{ displayCardLabel(card.displayName) }}</strong>
          </button>
        </div>

        <button
          class="action-btn seer-submit-btn"
          type="button"
          :disabled="!canSubmitSeerOrder"
          @click="submitSeerOrder"
        >
          確認排序
        </button>
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

        <div class="game-over-actions">
          <button class="action-btn game-over-exit" type="button" @click="leaveRoomAfterGame">回到大廳</button>
          <button class="action-btn game-over-next" type="button" @click="returnToRoomForNextRound">再來一局</button>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.game-board-page {
  /* ===== 遊戲畫布基準 ===== */
  --board-width: min(100vw, calc(100vh * 16 / 9));
  --board-height: min(100vh, calc(100vw * 9 / 16));

  /* ===== 可調 ratio 參數：之後優先改這一區 ===== */
  --card-width-ratio: 0.062;
  --font-xs-ratio: 0.05;
  --font-sm-ratio: 0.05;
  --font-md-ratio: 0.05;
  --font-lg-ratio: 0.02;
  --font-xl-ratio: 0.02;

  --room-panel-top-ratio: 0.017;
  --room-panel-left-ratio: 0.012;
  --room-panel-width-ratio: 0.105;
  --room-row-height-ratio: 0.035;
  --room-panel-gap-ratio: 0.007;

  --top-tools-top-ratio: 0.018;
  --top-tools-right-ratio: 0.016;
  --top-tools-gap-ratio: 0.006;
  --tool-btn-width-ratio: 0.034;
  --tool-btn-height-ratio: 0.065;

  --opponent-top-y-ratio: 0.028;
  --opponent-side-card-center-y-ratio: 0.54;
  --opponent-side-offset-ratio: 0.014;
  --opponent-side-width-ratio: 0.11;
  --side-name-gap-ratio: 0.18;
  --side-role-gap-ratio: 0.44;
  --role-card-width-ratio: 1.22;
  --opponent-top-column-gap-ratio: 0.009;
  --opponent-gap-ratio: 0.004;
  --role-panel-gap-ratio: 0.0055;

  --table-center-y-ratio: 0.48;
  --table-center-gap-ratio: 0.033;
  --turn-panel-width-ratio: 0.16;

  --player-area-width-ratio: 0.5;
  --player-area-bottom-ratio: 0.15;
  --player-area-height-ratio: 0.19;
  --player-info-left-ratio: -0.15;
  --player-info-bottom-ratio: -0.08;
  --player-info-gap-ratio: 0.005;
  --player-role-card-width-ratio: 1.22;

  --action-panel-width-ratio: 0.085;
  --action-panel-right-ratio: 0.014;
  --action-panel-bottom-ratio: 0.055;

  --hand-fan-corner-gap-ratio: 0.0105;
  --hand-fan-side-drop-ratio: 0.031;
  --hand-fan-max-rotation-start: 84;
  --hand-fan-max-rotation-floor: 46;
  --hand-fan-max-rotation-decay: 3;
  --hand-fan-min-step-start: 13;
  --hand-fan-min-step-floor: 4.8;
  --hand-fan-min-step-decay: 0.7;
  --hand-fan-step-cap: 16;

  /* ===== 派生尺寸：一般不需要直接改 ===== */
  --card-width: clamp(44px, calc(var(--board-width) * var(--card-width-ratio)), 108px);
  --card-height: calc(var(--card-width) * 7 / 5);

  --font-xs: clamp(7px, calc(var(--board-width) * var(--font-xs-ratio)), 12px);
  --font-sm: clamp(8px, calc(var(--board-width) * var(--font-sm-ratio)), 14px);
  --font-md: clamp(9px, calc(var(--board-width) * var(--font-md-ratio)), 16px);
  --font-lg: clamp(11px, calc(var(--board-width) * var(--font-lg-ratio)), 20px);
  --font-xl: clamp(13px, calc(var(--board-width) * var(--font-xl-ratio)), 25px);

  --room-panel-top: calc(var(--board-height) * var(--room-panel-top-ratio));
  --room-panel-left: calc(var(--board-width) * var(--room-panel-left-ratio));
  --room-panel-width: calc(var(--board-width) * var(--room-panel-width-ratio));
  --room-row-height: calc(var(--board-height) * var(--room-row-height-ratio));
  --room-panel-gap: calc(var(--board-height) * var(--room-panel-gap-ratio));

  --top-tools-top: calc(var(--board-height) * var(--top-tools-top-ratio));
  --top-tools-right: calc(var(--board-width) * var(--top-tools-right-ratio));
  --top-tools-gap: calc(var(--board-width) * var(--top-tools-gap-ratio));
  --tool-btn-width: calc(var(--board-width) * var(--tool-btn-width-ratio));
  --tool-btn-height: calc(var(--board-height) * var(--tool-btn-height-ratio));

  --opponent-top-y: calc(var(--board-height) * var(--opponent-top-y-ratio));
  --opponent-side-card-center-y: calc(var(--board-height) * var(--opponent-side-card-center-y-ratio));
  --opponent-side-offset: calc(var(--board-width) * var(--opponent-side-offset-ratio));
  --opponent-side-width: calc(var(--board-width) * var(--opponent-side-width-ratio));
  --side-name-gap: calc(var(--card-width) * var(--side-name-gap-ratio));
  --side-role-gap: calc(var(--card-width) * var(--side-role-gap-ratio));
  --role-card-width: calc(var(--card-width) * var(--role-card-width-ratio));
  --role-card-height: calc(var(--role-card-width) * 1771 / 1271);
  --opponent-top-column-gap: calc(var(--board-width) * var(--opponent-top-column-gap-ratio));
  --opponent-gap: calc(var(--board-height) * var(--opponent-gap-ratio));
  --role-panel-gap: calc(var(--board-height) * var(--role-panel-gap-ratio));

  --table-center-y: calc(var(--board-height) * var(--table-center-y-ratio));
  --table-center-gap: calc(var(--board-width) * var(--table-center-gap-ratio));
  --turn-panel-width: clamp(150px, calc(var(--board-width) * var(--turn-panel-width-ratio)), 265px);

  --player-area-width: calc(var(--board-width) * var(--player-area-width-ratio));
  --player-area-bottom: calc(var(--board-height) * var(--player-area-bottom-ratio));
  --player-area-height: calc(var(--board-height) * var(--player-area-height-ratio));
  --player-info-left: calc(var(--player-area-width) * var(--player-info-left-ratio));
  --player-info-bottom: calc(var(--board-height) * var(--player-info-bottom-ratio));
  --player-info-gap: calc(var(--board-height) * var(--player-info-gap-ratio));
  --player-role-card-width: calc(var(--card-width) * var(--player-role-card-width-ratio));
  --action-panel-width: calc(var(--board-width) * var(--action-panel-width-ratio));
  --action-panel-right: calc(var(--board-width) * var(--action-panel-right-ratio));
  --action-panel-bottom: calc(var(--board-height) * var(--action-panel-bottom-ratio));

  --hand-fan-corner-gap: calc(var(--board-width) * var(--hand-fan-corner-gap-ratio));
  --hand-fan-side-drop: calc(var(--board-height) * var(--hand-fan-side-drop-ratio));

  position: relative;
  width: 100vw;
  height: 100vh;
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

.game-board-stage {
  position: absolute;
  left: 50%;
  top: 50%;
  width: var(--board-width);
  height: var(--board-height);
  transform: translate(-50%, -50%);
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
  top: var(--room-panel-top);
  left: var(--room-panel-left);
  width: var(--room-panel-width);
  min-width: 110px;
  display: grid;
  gap: var(--room-panel-gap);
}

.room-row {
  min-height: clamp(22px, var(--room-row-height), 38px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 0 clamp(6px, calc(var(--board-width) * 0.007), 14px);
  border: 1px solid rgba(248, 250, 252, 0.88);
  border-radius: clamp(4px, calc(var(--board-width) * 0.004), 8px);
  background: rgba(5, 2, 16, 0.72);
  font-size: var(--font-sm);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.signal-icon {
  flex: 0 0 auto;
  font-weight: 700;
  transform: rotate(-18deg);
}

.top-tools {
  top: var(--top-tools-top);
  right: var(--top-tools-right);
  display: flex;
  gap: var(--top-tools-gap);
}

.tool-btn,
.action-btn,
.player-card {
  cursor: pointer;
}

.tool-btn {
  width: clamp(38px, var(--tool-btn-width), 70px);
  height: clamp(42px, var(--tool-btn-height), 76px);
  display: grid;
  place-items: center;
  gap: 2px;
  border: 1px solid rgba(248, 250, 252, 0.9);
  border-radius: clamp(4px, calc(var(--board-width) * 0.004), 8px);
  color: inherit;
  background: rgba(5, 2, 16, 0.68);
  font-size: var(--font-xs);
}

.tool-icon {
  font-size: var(--font-xl);
  line-height: 1;
}

.opponent {
  display: grid;
  justify-items: center;
  gap: var(--opponent-gap);
}

.opponent-top {
  top: var(--opponent-top-y);
  left: 50%;
  transform: translateX(-50%);
  grid-template-columns: calc(var(--role-card-width) * 1.15) auto;
  grid-template-rows: repeat(3, auto);
  column-gap: var(--opponent-top-column-gap);
  align-items: start;
}

.opponent-top .role-panel {
  grid-row: 1 / 4;
}

.opponent-left,
.opponent-right {
  top: var(--opponent-side-card-center-y);
  width: var(--opponent-side-width);
  height: calc(var(--role-card-height) + var(--card-width) + var(--card-height) * 0.35);
  transform: translateY(-50%);
}

.opponent-left {
  left: var(--opponent-side-offset);
}

.opponent-right {
  right: var(--opponent-side-offset);
}

.opponent-left .role-panel,
.opponent-right .role-panel {
  position: absolute;
  left: 50%;
  top: calc(50% - (var(--card-width) / 2) - var(--role-card-height) - var(--side-role-gap));
  transform: translateX(-50%);
}

.opponent-left > .opponent-name,
.opponent-right > .opponent-name {
  position: absolute;
  left: 50%;
  top: calc(50% + (var(--card-width) / 2) + var(--side-name-gap));
  transform: translateX(-50%);
}

.opponent-left .opponent-card-summary,
.opponent-right .opponent-card-summary {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
}

.role-panel {
  display: grid;
  justify-items: center;
  gap: var(--role-panel-gap);
}

.role-card {
  width: var(--role-card-width);
  height: var(--role-card-height);
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 0;
  background: transparent;
  font-size: var(--font-md);
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
  min-width: calc(var(--role-card-width) * 0.70);
  max-width: calc(var(--role-card-width) * 1.08);
  padding: calc(var(--board-height) * 0.004) calc(var(--board-width) * 0.004);
  border: 1px solid rgba(248, 250, 252, 0.86);
  border-radius: clamp(4px, calc(var(--board-width) * 0.004), 8px);
  color: #f8fafc;
  background: rgba(5, 2, 16, 0.78);
  font-size: var(--font-xs);
  line-height: 1.15;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.opponent-name,
.card-count {
  max-width: calc(var(--board-width) * 0.12);
  font-size: var(--font-sm);
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: center;
}

.opponent-card-summary {
  position: relative;
  width: max-content;
}

.card-count-badge {
  position: absolute;
  top: calc(var(--card-width) * -0.12);
  right: calc(var(--card-width) * -0.15);
  min-width: calc(var(--card-width) * 0.32);
  height: calc(var(--card-width) * 0.32);
  display: grid;
  place-items: center;
  padding: 0 calc(var(--card-width) * 0.06);
  border: 1px solid rgba(248, 250, 252, 0.95);
  border-radius: 999px;
  color: #080312;
  background: #f8fafc;
  font-size: var(--font-sm);
  font-weight: 800;
}

.game-card {
  width: var(--card-width);
  height: var(--card-height);
  display: grid;
  place-items: center;
  border: 1px solid rgba(248, 250, 252, 0.92);
  border-radius: clamp(4px, calc(var(--board-width) * 0.004), 8px);
  color: #f8fafc;
  background-color: rgba(5, 2, 16, 0.72);
  font-size: var(--font-sm);
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
  top: calc(var(--card-width) * -0.15);
  right: calc(var(--card-width) * -0.18);
}

.table-center {
  top: var(--table-center-y);
  left: 50%;
  width: calc(var(--card-width) * 2 + var(--turn-panel-width) + var(--table-center-gap) * 2);
  min-width: 0;
  transform: translate(-50%, -50%);
  display: grid;
  grid-template-columns: var(--card-width) var(--turn-panel-width) var(--card-width);
  grid-template-areas: "deck info discard";
  align-items: center;
  justify-content: center;
  gap: var(--table-center-gap);
}

.deck-stack {
  grid-area: deck;
  position: relative;
  justify-self: end;
  align-self: center;
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
  align-self: center;
}

.pile-card {
  width: var(--card-width);
  height: var(--card-height);
  font-weight: 800;
}

.turn-panel {
  grid-area: info;
  position: relative;
  width: var(--turn-panel-width);
  justify-self: center;
  padding: calc(var(--board-height) * 0.011) calc(var(--board-width) * 0.007);
  border: 1px solid rgba(248, 250, 252, 0.92);
  border-radius: clamp(4px, calc(var(--board-width) * 0.004), 8px);
  background: rgba(5, 2, 16, 0.74);
}

.turn-row {
  min-height: clamp(18px, calc(var(--board-height) * 0.028), 32px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: calc(var(--board-width) * 0.006);
  border-bottom: 1px solid rgba(248, 250, 252, 0.35);
  font-size: var(--font-md);
  white-space: nowrap;
}

.turn-row:last-child {
  border-bottom: 0;
}

.turn-row strong {
  flex: 0 0 auto;
  font-size: var(--font-lg);
}

.penalty-row {
  color: #fecaca;
}

.penalty-row strong {
  color: #fca5a5;
}

.penalty-hint {
  padding: calc(var(--board-height) * 0.006) 0 calc(var(--board-height) * 0.007);
  border-bottom: 1px solid rgba(248, 250, 252, 0.35);
  color: #fde68a;
  font-size: var(--font-xs);
  line-height: 1.3;
  text-align: right;
}

.event-hint {
  padding-top: calc(var(--board-height) * 0.007);
  color: #bfdbfe;
  font-size: var(--font-xs);
  line-height: 1.35;
  text-align: right;
}

.color-dot {
  width: calc(var(--font-lg) * 1.05);
  height: calc(var(--font-lg) * 1.05);
  border: 1px solid rgba(248, 250, 252, 0.92);
  border-radius: 50%;
}

.current-color {
  display: inline-flex;
  align-items: center;
  gap: calc(var(--board-width) * 0.004);
  font-size: var(--font-md);
}

.player-area {
  left: 50%;
  width: var(--player-area-width);
  height: var(--player-area-height);
  transform: translateX(-50%);
  bottom: var(--player-area-bottom);
  display: block;
}

.player-info {
  --role-card-width: var(--player-role-card-width);
  --role-card-height: calc(var(--role-card-width) * 1771 / 1271);
  position: absolute;
  left: var(--player-info-left);
  bottom: var(--player-info-bottom);
  display: grid;
  justify-items: center;
  gap: var(--player-info-gap);
}

.player-hand {
  position: relative;
  height: 100%;
}

.player-card {
  position: absolute;
  left: 50%;
  bottom: 0;
  width: var(--card-width);
  min-width: var(--card-width);
  padding: 0 calc(var(--card-width) * 0.04);
  transform: translateX(calc(-50% + var(--fan-offset))) rotate(var(--rotation));
  transform-origin: center 140%;
  transition: background 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.face-card,
.player-card {
  align-items: start;
  justify-items: start;
  padding: calc(var(--card-width) * 0.09) 0 0 calc(var(--card-width) * 0.09);
  font-size: var(--font-md);
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
  transform: translateX(calc(-50% + var(--fan-offset))) rotate(var(--rotation)) translateY(calc(var(--card-width) * -0.35)) scale(1.04);
}

.player-card.is-playable {
  border-color: #86efac;
  box-shadow: 0 0 0 2px rgba(134, 239, 172, 0.78);
}

.player-card.is-blocked-by-penalty {
  opacity: 0.58;
}

.player-card:disabled,
.player-card.is-disabled {
  cursor: not-allowed;
  opacity: 0.45;
  filter: grayscale(0.45);
}

.player-card.is-selected.is-playable {
  border-color: #fde68a;
  box-shadow: 0 0 0 3px rgba(253, 230, 138, 0.95), 0 14px 26px rgba(0, 0, 0, 0.42);
}

.action-panel {
  right: var(--action-panel-right);
  bottom: var(--action-panel-bottom);
  width: var(--action-panel-width);
  min-width: 92px;
  display: grid;
  gap: calc(var(--board-height) * 0.013);
}

.action-btn {
  height: clamp(32px, calc(var(--board-height) * 0.048), 54px);
  border: 1px solid rgba(248, 250, 252, 0.92);
  border-radius: clamp(4px, calc(var(--board-width) * 0.004), 8px);
  color: #f8fafc;
  background: rgba(5, 2, 16, 0.72);
  font-size: var(--font-md);
  white-space: nowrap;
}

.action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.tool-btn:hover,
.action-btn:hover:not(:disabled),
.player-card:hover:not(:disabled) {
  background-color: rgba(38, 28, 66, 0.9);
}

.player-card.is-selected:hover:not(:disabled) {
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

.settings-modal,
.color-picker-modal,
.target-picker-modal,
.seer-order-modal,
.game-over-modal {
  width: min(560px, calc(100vw - 32px));
  display: grid;
  gap: 16px;
  padding: 18px;
  border: 1px solid rgba(248, 250, 252, 0.8);
  border-radius: 8px;
  color: #f8fafc;
  background: rgba(8, 3, 18, 0.96);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
}

.settings-modal {
  width: min(340px, calc(100vw - 32px));
}

.color-picker-modal {
  width: min(360px, calc(100vw - 32px));
}

.target-picker-modal {
  width: min(380px, calc(100vw - 32px));
}

.seer-order-modal {
  width: min(620px, calc(100vw - 32px));
}

.seer-card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.seer-card-choice {
  position: relative;
  min-height: 148px;
  display: grid;
  justify-items: center;
  align-content: start;
  gap: 8px;
  padding: 10px 8px;
  border: 1px solid rgba(248, 250, 252, 0.28);
  border-radius: 8px;
  color: #f8fafc;
  background: rgba(248, 250, 252, 0.06);
  cursor: pointer;
}

.seer-card-choice:hover {
  background: rgba(38, 28, 66, 0.9);
}

.seer-card-choice.is-selected {
  border-color: #fde68a;
  box-shadow: 0 0 0 2px rgba(253, 230, 138, 0.78);
}

.seer-preview-card {
  position: relative;
  width: var(--card-width);
  height: var(--card-height);
  min-width: var(--card-width);
  padding: 8px 0 0 8px;
  font-size: 13px;
  font-weight: 800;
}

.seer-order-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  min-width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(248, 250, 252, 0.96);
  border-radius: 999px;
  color: #080312;
  background: #fde68a;
  font-size: 15px;
  font-weight: 900;
}

.seer-card-choice strong {
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.seer-submit-btn {
  width: 100%;
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

.game-over-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
}

.game-over-exit,
.game-over-next {
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

@media (max-aspect-ratio: 4 / 3) {
  .game-board-page {
    --room-panel-width-ratio: 0.13;
    --opponent-side-offset-ratio: 0.006;
    --opponent-side-width-ratio: 0.13;
    --table-center-gap-ratio: 0.03;
    --player-area-width-ratio: 0.60;
  }
}

@media (max-width: 760px) {
  .game-board-page {
    --font-xs-ratio: 0.0050;
    --font-sm-ratio: 0.0058;
    --font-md-ratio: 0.0068;
    --font-lg-ratio: 0.0084;
    --turn-panel-width-ratio: 0.16;
    --action-panel-width-ratio: 0.11;
  }
}
</style>
