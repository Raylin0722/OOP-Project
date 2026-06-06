<script setup>
import { computed } from 'vue';

const props = defineProps({
  user: {
    type: Object,
    required: true,
  },
});

defineEmits(['close']);

const trophyCount = computed(() => Number(props.user.total_score ?? 0));
const totalGames = computed(() => Number(props.user.total_games ?? 0));
const wins = computed(() => Number(props.user.wins ?? 0));
const winRateText = computed(() => {
  const rawRate = Number(props.user.win_rate ?? 0);
  const percentage = rawRate <= 1 ? rawRate * 100 : rawRate;
  return `${percentage.toFixed(1)}%`;
});
</script>

<template>
  <div class="stats-panel-overlay" @click="$emit('close')">
    <div class="stats-panel" @click.stop>
      <header class="panel-header">
        <h2>玩家統計數據</h2>
        <button class="close-btn" @click="$emit('close')">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          </svg>
        </button>
      </header>

      <div class="panel-content">
        <div class="stats-section">
          <h3>基本統計</h3>
          <div class="stat-grid">
            <div class="stat-card">
              <span class="stat-label">玩家名稱</span>
              <span class="stat-value">{{ user.username }}</span>
            </div>
            <div class="stat-card">
              <span class="stat-label">獎盃數</span>
              <span class="stat-value">{{ trophyCount }}</span>
            </div>
            <div class="stat-card">
              <span class="stat-label">總遊戲場次</span>
              <span class="stat-value">{{ totalGames }}</span>
            </div>
            <div class="stat-card">
              <span class="stat-label">勝場（勝率）</span>
              <span class="stat-value">{{ wins }}（{{ winRateText }}）</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stats-panel-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

.stats-panel {
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.2);
  max-width: 600px;
  width: 90%;
  max-height: 80vh;
  overflow-y: auto;
  animation: slideUp 0.3s ease;
}

@keyframes slideUp {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid #e2e8f0;
  position: sticky;
  top: 0;
  background: #ffffff;
}

.panel-header h2 {
  margin: 0;
  font-size: 20px;
  color: #1f2937;
}

.close-btn {
  background: transparent;
  border: 0;
  color: #64748b;
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.2s;
}

.close-btn:hover {
  color: #1f2937;
}

.close-btn svg {
  width: 20px;
  height: 20px;
  stroke-width: 2;
  fill: none;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.panel-content {
  padding: 24px;
}

.stats-section {
  margin-bottom: 24px;
}

.stats-section:last-child {
  margin-bottom: 0;
}

.stats-section h3 {
  margin: 0 0 16px 0;
  font-size: 14px;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.stat-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: #1d4ed8;
}

@media (max-width: 600px) {
  .stats-panel {
    width: 95%;
    max-height: 90vh;
  }

  .stat-grid {
    grid-template-columns: 1fr;
  }
}
</style>
