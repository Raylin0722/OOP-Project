import { createRouter, createWebHistory } from 'vue-router';
import AuthPage from './views/AuthPage.vue';
import LobbyPage from './views/LobbyPage.vue';
import GameBoardPage from './views/GameBoardPage.vue';

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
    path: '/',
    redirect: '/auth',
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to, from, next) => {
  const isLoggedIn = !!localStorage.getItem('authToken');

  if (to.meta.requiresAuth && !isLoggedIn) {
    next('/auth');
  } else if (to.meta.requiresGuest && isLoggedIn) {
    next('/lobby');
  } else {
    next();
  }
});

export default router;
