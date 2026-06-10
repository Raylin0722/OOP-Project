<script setup>
defineProps({
  busy: {
    type: Boolean,
    default: false,
  },
  canStart: {
    type: Boolean,
    default: false,
  },
  inRoom: {
    type: Boolean,
    default: false,
  },
  isReady: {
    type: Boolean,
    default: false,
  },
  isPlaying: {
    type: Boolean,
    default: false,
  },
  isHost: {
    type: Boolean,
    default: false,
  },
  isMatchmaking: {
    type: Boolean,
    default: false,
  },
  startLabel: {
    type: String,
    default: '開始遊戲',
  },
});

defineEmits([
  'create-room',
  'join-room',
  'toggle-ready',
  'start-game',
  'leave-room',
  'return-game',
  'join-matchmaking',
  'cancel-matchmaking',
  'matchmaking-ready-locked',
]);
</script>

<template>
  <div class="action-buttons">
    <template v-if="inRoom">
      <button v-if="isPlaying" class="action-btn return-btn" :disabled="busy" @click="$emit('return-game')">
        返回遊戲
      </button>
      <button
        v-if="!isPlaying && !isHost"
        class="action-btn ready-btn"
        :class="{ 'locked-ready-btn': isMatchmaking }"
        :disabled="busy"
        @click="isMatchmaking ? $emit('matchmaking-ready-locked') : $emit('toggle-ready')"
      >
        {{ isMatchmaking ? '配對中' : (isReady ? '取消準備' : '準備') }}
      </button>
      <button
        v-if="!isPlaying && !(isHost && isMatchmaking)"
        class="action-btn start-btn"
        :disabled="busy || !canStart"
        @click="$emit('start-game')"
      >
        {{ startLabel }}
      </button>
      <button
        v-if="!isPlaying && isHost && isMatchmaking"
        class="action-btn matchmaking-cancel-btn"
        :disabled="busy"
        @click="$emit('cancel-matchmaking')"
      >
        取消配對
      </button>
      <button class="action-btn leave-btn" :disabled="busy" @click="$emit('leave-room')">
        離開房間
      </button>
    </template>

    <template v-else>
      <button class="action-btn create-btn" :disabled="busy" @click="$emit('create-room')">
        建立房間
      </button>
      <button class="action-btn join-btn" :disabled="busy" @click="$emit('join-room')">
        加入房間
      </button>
      <button
        v-if="!isMatchmaking"
        class="action-btn matchmaking-btn"
        :disabled="busy"
        @click="$emit('join-matchmaking')"
      >
        開始配對
      </button>
      <button
        v-else
        class="action-btn matchmaking-cancel-btn"
        :disabled="busy"
        @click="$emit('cancel-matchmaking')"
      >
        取消配對
      </button>
    </template>
  </div>
</template>

<style scoped>
.action-buttons {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.action-btn {
  --lobby-button-aspect-ratio: 668 / 330;
  --lobby-button-text-offset-y: 5%;
  width: 116px;
  min-height: 0;
  padding: 10px 16px;
  border: 0;
  border-radius: 0;
  color: #3c2714;
  display: inline-grid;
  place-items: center;
  aspect-ratio: var(--lobby-button-aspect-ratio);
  background: var(--lobby-button-image, url("../assets/pictures/lobbybutton.png")) center / 100% 100% no-repeat;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  text-shadow: 0 1px 1px rgba(255, 245, 220, 0.55);
  text-align: center;
  padding-block-start: var(--lobby-button-text-offset-y);
  transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
}

.action-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.06);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.create-btn,
.join-btn {
  background: var(--lobby-button-image, url("../assets/pictures/lobbybutton.png")) center / 100% 100% no-repeat;
}

.ready-btn {
  background: var(--lobby-button-image, url("../assets/pictures/lobbybutton.png")) center / 100% 100% no-repeat;
}

.locked-ready-btn {
  opacity: 0.72;
}

.start-btn,
.matchmaking-btn {
  background: var(--lobby-button-image, url("../assets/pictures/lobbybutton.png")) center / 100% 100% no-repeat;
}

.return-btn {
  background: var(--lobby-button-image, url("../assets/pictures/lobbybutton.png")) center / 100% 100% no-repeat;
}

.matchmaking-cancel-btn {
  background: var(--lobby-button-image, url("../assets/pictures/lobbybutton.png")) center / 100% 100% no-repeat;
}

.leave-btn {
  background: var(--lobby-button-image, url("../assets/pictures/lobbybutton.png")) center / 100% 100% no-repeat;
}
</style>
