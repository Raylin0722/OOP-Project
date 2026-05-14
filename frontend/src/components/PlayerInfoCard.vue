<script setup>
defineProps({
  user: {
    type: Object,
    required: true,
  },
});

defineEmits(['click']);
</script>

<template>
  <div class="player-info-card" @click="$emit('click')">
    <div class="card-content">
      <div class="player-avatar">
        <span class="avatar-initial">{{ user.username.charAt(0).toUpperCase() }}</span>
      </div>
      <div class="player-details">
        <h2 class="player-name">{{ user.username }}</h2>
        <div class="player-stats">
          <div class="stat-item">
            <span class="stat-label">獎盃</span>
            <span class="stat-value">0</span>
          </div>
        </div>
      </div>
    </div>
    <div class="card-footer">
      <span class="hint-text">點擊查看詳細統計</span>
    </div>
  </div>
</template>

<style scoped>
.player-info-card {
  position: absolute;
  top: 0;
  left: 0;
  background: #ffffff;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  padding: 16px;
  width: 280px;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.1);
  cursor: pointer;
  transition: all 0.3s ease;
}

.player-info-card:hover {
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.15);
  transform: translateY(-2px);
}

.card-content {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.player-avatar {
  width: 56px;
  height: 56px;
  border-radius: 8px;
  background: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.avatar-initial {
  color: #ffffff;
  font-size: 24px;
  font-weight: bold;
}

.player-details {
  flex: 1;
}

.player-name {
  margin: 0 0 8px 0;
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}

.player-stats {
  display: flex;
  gap: 12px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

.stat-value {
  font-size: 18px;
  font-weight: 700;
  color: #1d4ed8;
}

.card-footer {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f1f5f9;
}

.hint-text {
  font-size: 12px;
  color: #94a3b8;
  display: block;
  text-align: center;
}
</style>
