<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { notifySessionActivity } from '../sessionTimeout.js';
import hallImage from '../assets/pictures/hall.jpg';
import lobbyButtonImage from '../assets/pictures/lobbybutton.png';

const API_BASE = '/api';
const router = useRouter();
const route = useRoute();

const activeTab = ref('login');
const loading = ref(false);
const message = ref('');
const error = ref('');
const currentUser = ref(null);
const showRegisterPassword = ref(false);
const showLoginPassword = ref(false);
const showResetPassword = ref(false);

const registerForm = reactive({
  username: '',
  nickname: '',
  email: '',
  password: '',
  password_confirm: '',
});

const verifyForm = reactive({
  email: '',
  code: '',
});

const loginForm = reactive({
  username: '',
  password: '',
});

const resetForm = reactive({
  email: '',
  token: '',
  new_password: '',
  new_password_confirm: '',
});

const isLoggedIn = computed(() => Boolean(currentUser.value));
const hasResetToken = computed(() => Boolean(resetForm.token));
const passwordIconTitle = computed(() => (showRegisterPassword.value ? 'Hide password' : 'Show password'));
const loginPasswordIconTitle = computed(() => (showLoginPassword.value ? 'Hide password' : 'Show password'));
const resetPasswordIconTitle = computed(() => (showResetPassword.value ? 'Hide password' : 'Show password'));
const tabTitleMap = {
  register: 'Sign up',
  verify: 'Verify Email',
  login: 'Login',
  forgot: 'Forgot Password',
  success: 'Account Center',
};
const activePanelTitle = computed(() => tabTitleMap[activeTab.value] || 'Login');

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

function setFeedback(successMessage = '') {
  message.value = successMessage;
  error.value = '';
}

function setError(err) {
  error.value = err.message || 'Something went wrong.';
  message.value = '';
}

function clearFeedback() {
  message.value = '';
  error.value = '';
}

function clearRegisterForm() {
  registerForm.username = '';
  registerForm.nickname = '';
  registerForm.email = '';
  registerForm.password = '';
  registerForm.password_confirm = '';
}

function clearVerifyForm() {
  verifyForm.email = '';
  verifyForm.code = '';
}

function clearLoginForm() {
  loginForm.username = '';
  loginForm.password = '';
}

function clearResetForm(keepEmail = false) {
  const email = resetForm.email;
  resetForm.email = keepEmail ? email : '';
  resetForm.token = '';
  resetForm.new_password = '';
  resetForm.new_password_confirm = '';
}

function clearForms() {
  clearRegisterForm();
  clearVerifyForm();
  clearLoginForm();
  clearResetForm();
}

function switchTab(tab) {
  if (isLoggedIn.value && tab !== 'success') {
    activeTab.value = 'success';
    setFeedback('You are already logged in. Please logout before switching accounts.');
    return;
  }
  clearFeedback();
  clearForms();
  activeTab.value = tab;
}

async function submitRegister() {
  if (registerForm.password !== registerForm.password_confirm) {
    setError(new Error('Passwords do not match.'));
    return;
  }
  loading.value = true;
  try {
    const data = await request('/auth/register/', {
      method: 'POST',
      body: JSON.stringify(registerForm),
    });
    currentUser.value = data.user;
    verifyForm.email = registerForm.email;
    clearRegisterForm();
    activeTab.value = 'verify';
    setFeedback('Registration successful. Please enter the email verification code.');
  } catch (err) {
    setError(err);
  } finally {
    loading.value = false;
  }
}

async function submitVerify() {
  loading.value = true;
  try {
    const data = await request('/auth/verify-email/', {
      method: 'POST',
      body: JSON.stringify(verifyForm),
    });
    currentUser.value = data.user;
    clearVerifyForm();
    activeTab.value = 'login';
    setFeedback('Email verified. You can log in now.');
  } catch (err) {
    setError(err);
  } finally {
    loading.value = false;
  }
}

async function submitLogin() {
  loading.value = true;
  try {
    const data = await request('/auth/login/', {
      method: 'POST',
      body: JSON.stringify(loginForm),
    });
    currentUser.value = data.user;
    localStorage.setItem('authToken', 'true');
    notifySessionActivity();
    clearLoginForm();
    router.push(typeof route.query.redirect === 'string' ? route.query.redirect : '/lobby');
  } catch (err) {
    setError(err);
  } finally {
    loading.value = false;
  }
}

async function submitRequestPasswordReset() {
  loading.value = true;
  try {
    await request('/auth/request-password-reset/', {
      method: 'POST',
      body: JSON.stringify({ email: resetForm.email }),
    });
    clearResetForm(true);
    setFeedback('If the email is registered, a password reset link has been sent.');
  } catch (err) {
    setError(err);
  } finally {
    loading.value = false;
  }
}

async function submitResetPassword() {
  if (resetForm.new_password !== resetForm.new_password_confirm) {
    setError(new Error('Passwords do not match.'));
    return;
  }
  loading.value = true;
  try {
    await request('/auth/reset-password/', {
      method: 'POST',
      body: JSON.stringify(resetForm),
    });
    clearResetForm();
    activeTab.value = 'login';
    setFeedback('Password reset successful. You can log in now.');
  } catch (err) {
    setError(err);
  } finally {
    loading.value = false;
  }
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
    activeTab.value = 'login';
    setFeedback('Logged out.');
    router.push('/auth');
  } catch (err) {
    setError(err);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  const params = new URLSearchParams(window.location.search);
  const resetEmail = params.get('reset_email');
  const resetToken = params.get('reset_token');
  if (resetEmail && resetToken) {
    resetForm.email = resetEmail;
    resetForm.token = resetToken;
    activeTab.value = 'forgot';
    window.history.replaceState({}, '', window.location.pathname);
    setFeedback('Reset link loaded. Enter a new password.');
    return;
  }

  if (route.query.reason === 'login_required') {
    activeTab.value = 'login';
    error.value = '請先登入後再進入大廳或遊戲房間。';
  }

  if (route.query.reason === 'idle_timeout') {
    activeTab.value = 'login';
    setFeedback('已超過 30 分鐘沒有操作，系統已自動登出並清理房間狀態。');
  }

  try {
    const data = await request('/auth/me/');
    currentUser.value = data.user;
    localStorage.setItem('authToken', 'true');
    router.push('/lobby');
    activeTab.value = 'success';
  } catch {
    currentUser.value = null;
    localStorage.removeItem('authToken');
  }
});
</script>

<template>
  <main class="auth-page">
    <section class="auth-stage">
      <div class="auth-board" :style="{ '--auth-board-image': `url(${hallImage})`, '--lobby-button-image': `url(${lobbyButtonImage})` }">
        <header class="auth-title-panel">
          <h1>{{ activePanelTitle }}</h1>
        </header>

        <section class="auth-workspace">
          <div class="auth-feedback-stack">
            <p v-if="message" class="auth-notice success">{{ message }}</p>
            <p v-if="error" class="auth-notice error">{{ error }}</p>
          </div>

          <div class="auth-form-stage">
            <form v-if="activeTab === 'login'" class="auth-grid-form" @submit.prevent="submitLogin">
              <label class="field-label" for="login-username">Account</label>
              <div class="field-input">
                <input id="login-username" v-model.trim="loginForm.username" autocomplete="username" required type="text" />
              </div>

              <label class="field-label" for="login-password">Password</label>
              <div class="field-input field-input-password">
                <input
                  id="login-password"
                  v-model="loginForm.password"
                  autocomplete="current-password"
                  required
                  :type="showLoginPassword ? 'text' : 'password'"
                />
                <button
                  class="input-icon-button"
                  type="button"
                  :aria-label="loginPasswordIconTitle"
                  :title="loginPasswordIconTitle"
                  @click="showLoginPassword = !showLoginPassword"
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24">
                    <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                </button>
              </div>

              <div class="auth-action-row form-span">
                <button type="button" class="auth-action-btn warning-orange-btn" @click="switchTab('forgot')">
                  忘記密碼
                </button>
                <button type="button" class="auth-action-btn accent-purple-btn" @click="switchTab('register')">
                  註冊
                </button>
                <button class="auth-action-btn success-green-btn" :disabled="loading" type="submit">
                  {{ loading ? 'Logging in...' : '登入' }}
                </button>
              </div>
            </form>

            <form v-if="activeTab === 'register'" class="auth-grid-form" @submit.prevent="submitRegister">
              <label class="field-label" for="register-username">Account</label>
              <div class="field-input">
                <input id="register-username" v-model.trim="registerForm.username" autocomplete="username" required type="text" />
              </div>

              <label class="field-label" for="register-nickname">Nickname</label>
              <div class="field-input">
                <input id="register-nickname" v-model.trim="registerForm.nickname" autocomplete="nickname" type="text" />
              </div>

              <label class="field-label" for="register-email">Email</label>
              <div class="field-input">
                <input id="register-email" v-model.trim="registerForm.email" autocomplete="email" required type="email" />
              </div>

              <label class="field-label" for="register-password">Password</label>
              <div class="field-input field-input-password">
                <input
                  id="register-password"
                  v-model="registerForm.password"
                  autocomplete="new-password"
                  minlength="8"
                  required
                  :type="showRegisterPassword ? 'text' : 'password'"
                />
                <button
                  class="input-icon-button"
                  type="button"
                  :aria-label="passwordIconTitle"
                  :title="passwordIconTitle"
                  @click="showRegisterPassword = !showRegisterPassword"
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24">
                    <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                </button>
              </div>

              <label class="field-label" for="register-password-confirm">Confirm</label>
              <div class="field-input field-input-password">
                <input
                  id="register-password-confirm"
                  v-model="registerForm.password_confirm"
                  autocomplete="new-password"
                  minlength="8"
                  required
                  :type="showRegisterPassword ? 'text' : 'password'"
                />
                <button
                  class="input-icon-button"
                  type="button"
                  :aria-label="passwordIconTitle"
                  :title="passwordIconTitle"
                  @click="showRegisterPassword = !showRegisterPassword"
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24">
                    <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                </button>
              </div>

              <div class="auth-action-row form-span">
                <button type="button" class="auth-action-btn utility-blue-btn" @click="switchTab('login')">
                  返回登入
                </button>
                <button class="auth-action-btn accent-purple-btn" :disabled="loading" type="submit">
                  {{ loading ? 'Submitting...' : '創建帳號' }}
                </button>
              </div>
            </form>

            <form v-if="activeTab === 'verify'" class="auth-grid-form" @submit.prevent="submitVerify">
              <label class="field-label" for="verify-email">Email</label>
              <div class="field-input">
                <input id="verify-email" v-model.trim="verifyForm.email" autocomplete="email" required type="email" />
              </div>

              <label class="field-label" for="verify-code">Code</label>
              <div class="field-input">
                <input id="verify-code" v-model.trim="verifyForm.code" inputmode="numeric" maxlength="6" required type="text" />
              </div>

              <div class="auth-action-row form-span">
                <button type="button" class="auth-action-btn utility-blue-btn" @click="switchTab('login')">
                  返回登入
                </button>
                <button class="auth-action-btn success-green-btn" :disabled="loading" type="submit">
                  {{ loading ? 'Verifying...' : 'Verify email' }}
                </button>
              </div>
            </form>

            <form
              v-if="activeTab === 'forgot' && !hasResetToken"
              class="auth-grid-form"
              @submit.prevent="submitRequestPasswordReset"
            >
              <label class="field-label" for="forgot-email">Email</label>
              <div class="field-input">
                <input id="forgot-email" v-model.trim="resetForm.email" autocomplete="email" required type="email" />
              </div>

              <div class="auth-action-row form-span">
                <button type="button" class="auth-action-btn utility-blue-btn" @click="switchTab('login')">
                  返回登入
                </button>
                <button class="auth-action-btn warning-orange-btn" :disabled="loading || !resetForm.email" type="submit">
                  {{ loading ? 'Sending...' : '發送重設連結' }}
                </button>
              </div>
            </form>

            <form
              v-if="activeTab === 'forgot' && hasResetToken"
              class="auth-grid-form"
              @submit.prevent="submitResetPassword"
            >
              <label class="field-label" for="reset-email">Email</label>
              <div class="field-input">
                <input id="reset-email" v-model.trim="resetForm.email" autocomplete="email" required readonly type="email" />
              </div>
              <input v-model="resetForm.token" type="hidden" />

              <label class="field-label" for="reset-password">New Password</label>
              <div class="field-input field-input-password">
                <input
                  id="reset-password"
                  v-model="resetForm.new_password"
                  autocomplete="new-password"
                  minlength="8"
                  required
                  :type="showResetPassword ? 'text' : 'password'"
                />
                <button
                  class="input-icon-button"
                  type="button"
                  :aria-label="resetPasswordIconTitle"
                  :title="resetPasswordIconTitle"
                  @click="showResetPassword = !showResetPassword"
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24">
                    <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                </button>
              </div>

              <label class="field-label" for="reset-password-confirm">Confirm</label>
              <div class="field-input field-input-password">
                <input
                  id="reset-password-confirm"
                  v-model="resetForm.new_password_confirm"
                  autocomplete="new-password"
                  minlength="8"
                  required
                  :type="showResetPassword ? 'text' : 'password'"
                />
                <button
                  class="input-icon-button"
                  type="button"
                  :aria-label="resetPasswordIconTitle"
                  :title="resetPasswordIconTitle"
                  @click="showResetPassword = !showResetPassword"
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24">
                    <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                </button>
              </div>

              <div class="auth-action-row form-span">
                <button type="button" class="auth-action-btn utility-blue-btn" @click="switchTab('login')">
                  返回登入
                </button>
                <button class="auth-action-btn warning-orange-btn" :disabled="loading" type="submit">
                  {{ loading ? 'Resetting...' : 'Reset password' }}
                </button>
              </div>
            </form>

            <section v-if="activeTab === 'success' && isLoggedIn" class="success-panel">
              <div class="success-summary">
                <div>
                  <span>Username</span>
                  <strong>{{ currentUser.username }}</strong>
                </div>
                <div>
                  <span>Email</span>
                  <strong>{{ currentUser.email }}</strong>
                </div>
                <div>
                  <span>Nickname</span>
                  <strong>{{ currentUser.nickname }}</strong>
                </div>
              </div>

              <div class="auth-action-row centered">
                <button class="auth-action-btn success-green-btn" type="button" @click="router.push('/lobby')">
                  Enter lobby
                </button>
                <button class="auth-action-btn danger-red-btn" :disabled="loading" type="button" @click="submitLogout">
                  {{ loading ? 'Logging out...' : 'Logout' }}
                </button>
              </div>
            </section>
          </div>
        </section>
      </div>
    </section>
  </main>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  overflow: hidden;
  padding: 3vh 3vw;
  background:
    radial-gradient(circle at 50% 15%, rgba(112, 135, 188, 0.22), transparent 22%),
    linear-gradient(180deg, #08111d 0%, #0a1730 46%, #07101d 100%);
}

.auth-stage {
  width: min(90vw, 160vh);
  aspect-ratio: 1.72 / 1;
  display: grid;
  place-items: center;
}

.auth-board {
  --board-safe-left: 11%;
  --board-safe-right: 11%;
  --board-safe-top: 10.8%;
  --board-safe-bottom: 1%;
  --title-left: 25%;
  --title-width: 50%;
  --title-height: 10%;
  --workspace-top: 20%;
  --workspace-height: 68%;
  --workspace-padding-y: 1%;
  --workspace-padding-x: 3.2%;
  --workspace-radius: 1%;
  --workspace-gap: 1.2%;
  --notice-padding-y: 0.95%;
  --notice-padding-x: 1.3%;
  --form-column-gap: 2.4%;
  --form-row-gap: 1.7vh;
  --field-label-width: 25%;
  --field-min-height: 7.8vh;
  --field-radius: 0.75vw;
  --field-font-size: clamp(0.94rem, 1vw, 1.35rem);
  --label-font-size: clamp(1rem, 1.45vw, 2.2rem);
  --title-font-size: clamp(1.8rem, 3.35vw, 4.2rem);
  --action-gap: 0.9vw;
  --action-button-min-width: 10.4vw;
  --action-button-aspect-ratio: 668 / 330;
  --action-button-font-size: clamp(0.84rem, 0.92vw, 1.2rem);
  --password-icon-size: 1.65vw;
  --success-card-gap: 1vw;
  position: relative;
  width: 100%;
  height: 100%;
  background: var(--auth-board-image) center / 100% 100% no-repeat;
  filter: drop-shadow(0 1.2vw 1.6vw rgba(0, 0, 0, 0.42));
}

.auth-title-panel,
.auth-workspace {
  position: absolute;
  left: var(--board-safe-left);
  right: var(--board-safe-right);
}

.auth-title-panel {
  top: var(--board-safe-top);
  left: var(--title-left);
  right: auto;
  width: var(--title-width);
  height: var(--title-height);
  display: grid;
  place-items: center;
  border: none;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.auth-title-panel h1 {
  margin: 0;
  color: #4b2e18;
  font-family: Georgia, 'Times New Roman', serif;
  font-size: var(--title-font-size);
  font-weight: 700;
  letter-spacing: 0.04em;
}

.auth-workspace {
  top: var(--workspace-top);
  min-height: var(--workspace-height);
  display: grid;
  grid-template-rows: auto 1fr;
  gap: var(--workspace-gap);
  padding: var(--workspace-padding-y) var(--workspace-padding-x);
  border: none;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  overflow: hidden;
}

.auth-feedback-stack {
  display: grid;
  gap: 0.7vh;
  align-content: start;
}

.auth-form-stage {
  min-height: 0;
  height: 100%;
  display: grid;
  align-items: center;
  overflow: hidden;
}

.auth-action-btn {
  --lobby-button-text-offset-y: 2%;
  border: 0;
  border-radius: 0;
  color: #3c2714;
  cursor: pointer;
  display: inline-grid;
  place-items: center;
  font-size: clamp(0.92rem, 1vw, 1.45rem);
  font-weight: 700;
  line-height: 1;
  aspect-ratio: var(--action-button-aspect-ratio);
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
  transition: transform 0.16s ease, box-shadow 0.16s ease, opacity 0.16s ease;
  box-shadow: none;
  text-shadow: 0 0.05vw 0.08vw rgba(255, 245, 220, 0.55);
  text-align: center;
  padding-block-start: var(--lobby-button-text-offset-y);
}

.auth-action-btn:hover:not(:disabled) {
  transform: translateY(-0.25vh);
  filter: brightness(1.06);
}

.auth-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.utility-blue-btn {
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
}

.success-green-btn {
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
}

.accent-purple-btn {
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
}

.warning-orange-btn {
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
}

.danger-red-btn {
  background: var(--lobby-button-image) center / 100% 100% no-repeat;
}

.auth-notice {
  margin: 0;
  padding: var(--notice-padding-y) var(--notice-padding-x);
  border-radius: 0.7vw;
  text-align: center;
  font-size: clamp(0.78rem, 0.86vw, 1.1rem);
  font-weight: 700;
}

.auth-notice.success {
  background: rgba(220, 252, 231, 0.96);
  color: #166534;
}

.auth-notice.error {
  background: rgba(254, 226, 226, 0.96);
  color: #991b1b;
}

.auth-grid-form {
  display: grid;
  grid-template-columns: var(--field-label-width) 1fr;
  gap: var(--form-row-gap) var(--form-column-gap);
  height: 100%;
  align-content: center;
  align-self: stretch;
  min-height: 0;
  overflow: auto;
  padding-right: 0.4%;
}

.field-label,
.field-input {
  min-height: var(--field-min-height);
  box-sizing: border-box;
}

.field-label {
  display: grid;
  place-items: center;
  padding: 0 1vw;
  border: none;
  border-radius: 0;
  background: transparent;
  color: #4b2e18;
  font-family: Georgia, 'Times New Roman', serif;
  font-size: var(--label-font-size);
  font-weight: 700;
  text-align: center;
}

.field-input {
  position: relative;
  display: flex;
  align-items: center;
  border: 0.08vw solid rgba(145, 145, 145, 0.74);
  border-radius: var(--field-radius);
  background: rgba(255, 255, 255, 0.96);
  padding: 0 1.5vw;
}

.field-input input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: #2f241c;
  font-size: var(--field-font-size);
  font-family: 'Segoe UI', system-ui, sans-serif;
}

.field-input input::placeholder {
  color: rgba(77, 58, 44, 0.48);
}

.field-input input[readonly] {
  color: rgba(47, 36, 28, 0.72);
}

.field-input-password {
  padding-right: 4vw;
}

.input-icon-button {
  position: absolute;
  top: 50%;
  right: 1.1vw;
  width: var(--password-icon-size);
  min-width: 1.6rem;
  aspect-ratio: 1;
  display: grid;
  place-items: center;
  border: none;
  background: transparent;
  color: rgba(58, 42, 28, 0.76);
  cursor: pointer;
  transform: translateY(-50%);
}

.input-icon-button svg {
  width: 100%;
  height: 100%;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
}

.form-span {
  grid-column: 1 / -1;
}

.auth-action-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--action-gap);
  margin-top: 0.45vh;
}

.auth-action-row.centered {
  justify-content: center;
}

.auth-action-btn {
  width: var(--action-button-min-width);
  min-height: 0;
  padding: 0.8vh 1.2vw;
  padding-block-start: var(--lobby-button-text-offset-y);
  font-size: var(--action-button-font-size);
}

.success-panel {
  display: grid;
  gap: 1.9vh;
  align-content: center;
  justify-items: center;
  align-self: stretch;
  height: 100%;
  min-height: 0;
}

.success-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--success-card-gap);
}

.success-summary > div {
  display: grid;
  gap: 0.8vh;
  padding: 1.4vh 1vw;
  border: 0.08vw solid rgba(145, 145, 145, 0.74);
  border-radius: 0.75vw;
  background: rgba(255, 255, 255, 0.96);
}

.success-summary span {
  color: rgba(75, 46, 24, 0.72);
  font-size: clamp(0.8rem, 0.88vw, 1.2rem);
  font-weight: 700;
}

.success-summary strong {
  color: #2f241c;
  font-size: clamp(1rem, 1.18vw, 1.65rem);
}

@media (max-width: 980px), (max-aspect-ratio: 4 / 3) {
  .auth-stage {
    width: 96vw;
  }

  .auth-board {
    --workspace-padding-y: 2.8%;
    --workspace-padding-x: 2.8%;
    --field-min-height: 7vh;
    --label-font-size: clamp(0.95rem, 2.2vw, 1.5rem);
    --field-font-size: clamp(0.9rem, 1.9vw, 1.2rem);
    --action-button-min-width: 9.5rem;
    --password-icon-size: 1.2rem;
  }

  .auth-workspace {
    gap: 1.8%;
  }

  .auth-grid-form {
    grid-template-columns: 1fr;
  }

  .field-label,
  .field-input {
    min-height: 7.4vh;
  }

  .field-label {
    font-size: clamp(1rem, 2.8vw, 2rem);
  }

  .field-input-password {
    padding-right: 3.4rem;
  }

  .success-summary {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .auth-page {
    padding: 1.6vh 1.6vw;
  }

  .auth-stage {
    width: 99vw;
  }

  .auth-board {
    --title-left: 18%;
    --title-width: 64%;
    --title-height: 10.5%;
    --workspace-top: 19%;
    --workspace-height: 68%;
    --workspace-padding-y: 2.6%;
    --workspace-padding-x: 2.4%;
    --field-min-height: 6.1vh;
    --action-button-min-height: 5.1vh;
    --action-gap: 0.65rem;
  }

  .auth-action-btn {
    flex: 1 1 100%;
    min-width: 0;
  }
}
</style>
