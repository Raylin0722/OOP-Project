import { createRouter, createWebHistory } from 'vue-router';
import AuthPage from './views/AuthPage.vue';
import LobbyPage from './views/LobbyPage.vue';
import GameBoardPage from './views/GameBoardPage.vue';
import GameDebugPage from './views/GameDebugPage.vue';

const API_BASE = `http://${window.location.hostname}:8000/api`;

const routes = [
  {
    path: '/auth',
    component: AuthPage,
    meta: { requiresGuest: true },
  },
  {
    path: '/lobby',
    component: LobbyPage,
    meta: { requiresAuth: true },
  },
  {
    path: '/game-ui',
    component: GameBoardPage,
    meta: { requiresAuth: true },
  },
  {
    path: '/game-debug',
    component: GameDebugPage,
    meta: { requiresAuth: true },
  },
  {
    path: '/',
    redirect: '/auth',
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

let authCheckPromise = null;

async function fetchCurrentUser() {
  const response = await fetch(`${API_BASE}/auth/me/`, {
    credentials: 'include',
  });

  if (!response.ok) {
    localStorage.removeItem('authToken');
    return null;
  }

  const data = await response.json().catch(() => ({}));
  if (!data.user) {
    localStorage.removeItem('authToken');
    return null;
  }

  localStorage.setItem('authToken', 'true');
  return data.user;
}

async function getCurrentUser() {
  if (!authCheckPromise) {
    authCheckPromise = fetchCurrentUser().finally(() => {
      authCheckPromise = null;
    });
  }

  return authCheckPromise;
}

function buildLoginRedirect(to) {
  return {
    path: '/auth',
    query: {
      redirect: to.fullPath,
      reason: 'login_required',
    },
  };
}

router.beforeEach(async (to) => {
  if (to.meta.requiresAuth) {
    const user = await getCurrentUser();

    if (!user) {
      return buildLoginRedirect(to);
    }
  }

  if (to.meta.requiresGuest) {
    const user = await getCurrentUser();

    if (user) {
      return '/lobby';
    }
  }

  return true;
});

export default router;
