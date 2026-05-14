<script setup>
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import PlayerInfoCard from '../components/PlayerInfoCard.vue';
import PlayerStatsPanel from '../components/PlayerStatsPanel.vue';
import LobbyActionButtons from '../components/LobbyActionButtons.vue';

const API_BASE = 'http://127.0.0.1:8000/api';
const router = useRouter();

const currentUser = ref(null);
const loading = ref(false);
const showStatsPanel = ref(false);

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

async function submitLogout() {
  loading.value = true;
  try {
    await request('/auth/logout/', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    currentUser.value = null;
    localStorage.removeItem('authToken');
    router.push('/auth');
  } catch (err) {
    console.error('Logout failed:', err);
  } finally {
    loading.value = false;
  }
}

function toggleStatsPanel() {
  showStatsPanel.value = !showStatsPanel.value;
}

onMounted(async () => {
  try {
    const data = await request('/auth/me/');
    currentUser.value = data.user;
  } catch (err) {
    console.error('Failed to load user:', err);
    router.push('/auth');
  }
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

      <LobbyActionButtons />
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
</style>
