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
});

defineEmits([
  'create-room',
  'join-room',
  'toggle-ready',
  'start-game',
  'test-start',
  'leave-room',
]);
</script>

<template>
  <div class="action-buttons">
    <template v-if="inRoom">
      <button class="action-btn ready-btn" :disabled="busy" @click="$emit('toggle-ready')">
        {{ isReady ? '取消準備' : '準備' }}
      </button>
      <button class="action-btn start-btn" :disabled="busy || !canStart" @click="$emit('start-game')">
        開始遊戲
      </button>
      <button class="action-btn test-btn" :disabled="busy" @click="$emit('test-start')">
        測試進入
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
  min-width: 116px;
  min-height: 42px;
  padding: 10px 16px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #ffffff;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
}

.action-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.14);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.create-btn,
.join-btn {
  background: #2563eb;
  border-color: #1d4ed8;
}

.ready-btn {
  background: #0f766e;
  border-color: #0f766e;
}

.start-btn {
  background: #16a34a;
  border-color: #15803d;
}

.test-btn {
  background: #7c3aed;
  border-color: #6d28d9;
}

.leave-btn {
  background: #ef4444;
  border-color: #dc2626;
}
</style>
