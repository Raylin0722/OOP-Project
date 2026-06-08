const API_BASE = '/api';
const IDLE_TIMEOUT_MS = 30 * 60 * 1000;
const ACTIVITY_EVENTS = ['click', 'keydown', 'mousemove', 'mousedown', 'touchstart', 'scroll'];

let idleTimerId = null;
let enabled = false;
let isLoggingOut = false;

function isAuthenticated() {
  return localStorage.getItem('authToken') === 'true';
}

function redirectToAuth(reason = 'idle_timeout') {
  const nextUrl = `/auth?reason=${encodeURIComponent(reason)}`;
  if (window.location.pathname !== '/auth') {
    window.location.assign(nextUrl);
  }
}

async function logoutForIdleTimeout() {
  if (isLoggingOut || !isAuthenticated()) {
    return;
  }

  isLoggingOut = true;
  try {
    await fetch(`${API_BASE}/auth/logout/`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'idle_timeout' }),
    });
  } catch (err) {
    console.warn('Idle timeout logout failed:', err);
  } finally {
    localStorage.removeItem('authToken');
    redirectToAuth('idle_timeout');
  }
}

function resetIdleTimer() {
  if (!enabled) {
    return;
  }

  if (idleTimerId) {
    window.clearTimeout(idleTimerId);
  }

  if (!isAuthenticated()) {
    return;
  }

  idleTimerId = window.setTimeout(logoutForIdleTimeout, IDLE_TIMEOUT_MS);
}

export function startSessionTimeoutWatcher() {
  if (enabled) {
    resetIdleTimer();
    return;
  }

  enabled = true;
  ACTIVITY_EVENTS.forEach((eventName) => {
    window.addEventListener(eventName, resetIdleTimer, { passive: true });
  });
  resetIdleTimer();
}

export function stopSessionTimeoutWatcher() {
  enabled = false;
  if (idleTimerId) {
    window.clearTimeout(idleTimerId);
    idleTimerId = null;
  }
  ACTIVITY_EVENTS.forEach((eventName) => {
    window.removeEventListener(eventName, resetIdleTimer);
  });
}

export function notifySessionActivity() {
  resetIdleTimer();
}

export function forceSessionLogout() {
  return logoutForIdleTimeout();
}
