<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

const API_BASE = `http://${window.location.hostname}:8000/api`;
const router = useRouter();
const route = useRoute();

const activeTab = ref('register');
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
    <section class="auth-shell">
      <header class="page-header">
        <h1>OOP Game Account</h1>
      </header>

      <nav class="tabs" aria-label="Account pages">
        <button
          :class="{ active: activeTab === 'register' }"
          :disabled="isLoggedIn"
          type="button"
          @click="switchTab('register')"
        >
          Register
        </button>
        <button
          :class="{ active: activeTab === 'verify' }"
          :disabled="isLoggedIn"
          type="button"
          @click="switchTab('verify')"
        >
          Verify
        </button>
        <button
          :class="{ active: activeTab === 'login' }"
          :disabled="isLoggedIn"
          type="button"
          @click="switchTab('login')"
        >
          Login
        </button>
        <button
          :class="{ active: activeTab === 'forgot' }"
          :disabled="isLoggedIn"
          type="button"
          @click="switchTab('forgot')"
        >
          Forgot
        </button>
      </nav>

      <p v-if="message" class="notice success">{{ message }}</p>
      <p v-if="error" class="notice error">{{ error }}</p>

      <form v-if="activeTab === 'register'" class="auth-form" @submit.prevent="submitRegister">
        <label>
          Username
          <input v-model.trim="registerForm.username" autocomplete="username" required type="text" />
        </label>
        <label>
          Nickname
          <input v-model.trim="registerForm.nickname" autocomplete="nickname" type="text" />
        </label>
        <label>
          Email
          <input v-model.trim="registerForm.email" autocomplete="email" required type="email" />
        </label>
        <label>
          Password
          <span class="password-control">
            <input
              v-model="registerForm.password"
              autocomplete="new-password"
              minlength="8"
              required
              :type="showRegisterPassword ? 'text' : 'password'"
            />
            <button
              class="icon-button"
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
          </span>
        </label>
        <label>
          Confirm Password
          <span class="password-control">
            <input
              v-model="registerForm.password_confirm"
              autocomplete="new-password"
              minlength="8"
              required
              :type="showRegisterPassword ? 'text' : 'password'"
            />
            <button
              class="icon-button"
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
          </span>
        </label>
        <button class="primary-action" :disabled="loading" type="submit">
          {{ loading ? 'Submitting...' : 'Create Account' }}
        </button>
      </form>

      <form v-if="activeTab === 'verify'" class="auth-form" @submit.prevent="submitVerify">
        <label>
          Email
          <input v-model.trim="verifyForm.email" autocomplete="email" required type="email" />
        </label>
        <label>
          Verification Code
          <input v-model.trim="verifyForm.code" inputmode="numeric" maxlength="6" required type="text" />
        </label>
        <button class="primary-action" :disabled="loading" type="submit">
          {{ loading ? 'Verifying...' : 'Verify Email' }}
        </button>
      </form>

      <form v-if="activeTab === 'login'" class="auth-form" @submit.prevent="submitLogin">
        <label>
          Username or Email
          <input v-model.trim="loginForm.username" autocomplete="username" required type="text" />
        </label>
        <label>
          Password
          <span class="password-control">
            <input
              v-model="loginForm.password"
              autocomplete="current-password"
              required
              :type="showLoginPassword ? 'text' : 'password'"
            />
            <button
              class="icon-button"
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
          </span>
        </label>
        <button class="primary-action" :disabled="loading" type="submit">
          {{ loading ? 'Logging in...' : 'Login' }}
        </button>
      </form>

      <form v-if="activeTab === 'forgot' && !hasResetToken" class="auth-form" @submit.prevent="submitRequestPasswordReset">
        <label>
          Email
          <input v-model.trim="resetForm.email" autocomplete="email" required type="email" />
        </label>
        <button
          class="secondary-action"
          :disabled="loading || !resetForm.email"
          type="submit"
        >
          {{ loading ? 'Sending...' : 'Send Reset Link' }}
        </button>
      </form>

      <form v-if="activeTab === 'forgot' && hasResetToken" class="auth-form" @submit.prevent="submitResetPassword">
        <label>
          Email
          <input v-model.trim="resetForm.email" autocomplete="email" required readonly type="email" />
        </label>
        <input v-model="resetForm.token" type="hidden" />
        <label>
          New Password
          <span class="password-control">
            <input
              v-model="resetForm.new_password"
              autocomplete="new-password"
              minlength="8"
              required
              :type="showResetPassword ? 'text' : 'password'"
            />
            <button
              class="icon-button"
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
          </span>
        </label>
        <label>
          Confirm New Password
          <span class="password-control">
            <input
              v-model="resetForm.new_password_confirm"
              autocomplete="new-password"
              minlength="8"
              required
              :type="showResetPassword ? 'text' : 'password'"
            />
            <button
              class="icon-button"
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
          </span>
        </label>
        <button class="primary-action" :disabled="loading" type="submit">
          {{ loading ? 'Resetting...' : 'Reset Password' }}
        </button>
      </form>

      <section v-if="activeTab === 'success' && isLoggedIn" class="success-panel">
        <h2>Login Successful</h2>
        <dl>
          <div>
            <dt>Username</dt>
            <dd>{{ currentUser.username }}</dd>
          </div>
          <div>
            <dt>Email</dt>
            <dd>{{ currentUser.email }}</dd>
          </div>
          <div>
            <dt>Nickname</dt>
            <dd>{{ currentUser.nickname }}</dd>
          </div>
        </dl>
        <button class="secondary-action" :disabled="loading" type="button" @click="submitLogout">
          Logout
        </button>
      </section>
    </section>
  </main>
</template>
