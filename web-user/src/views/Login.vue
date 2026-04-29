<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { login as loginApi } from '@/api/auth'
import { extractError } from '@/api/client'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const store = useUserStore()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function submit(): Promise<void> {
  if (loading.value) return
  error.value = ''
  if (!username.value || !password.value) {
    error.value = '请填写用户名和密码'
    return
  }
  loading.value = true
  try {
    const { token, user } = await loginApi({
      username: username.value.trim(),
      password: password.value,
    })
    store.setAuth(token, user)
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } catch (err) {
    const e = extractError(err)
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="card">
      <h1>登录</h1>
      <form @submit.prevent="submit">
        <label>
          用户名
          <input v-model="username" autocomplete="username" required />
        </label>
        <label>
          密码
          <input v-model="password" type="password" autocomplete="current-password" required />
        </label>
        <button type="submit" class="primary" :disabled="loading">
          {{ loading ? '登录中…' : '登录' }}
        </button>
      </form>
      <p v-if="error" class="error">{{ error }}</p>
      <div class="links">
        <RouterLink to="/register">没有账号？注册</RouterLink>
        <span>·</span>
        <RouterLink to="/forgot-password">忘记密码</RouterLink>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
}

.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 32px 36px;
  width: 100%;
  max-width: 380px;
}

h1 {
  color: var(--accent);
  margin: 0 0 24px;
  font-size: 22px;
  letter-spacing: 1px;
  text-align: center;
}

form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--text-dim);
  font-size: 13px;
}

input {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--text);
  outline: none;
}
input:focus { border-color: rgba(126, 184, 240, 0.6); }

.primary {
  background: linear-gradient(to right, rgba(70,120,200,0.9), rgba(100,150,230,0.9));
  border: none;
  border-radius: 8px;
  color: white;
  padding: 10px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  margin-top: 6px;
}
.primary:hover:not(:disabled) { filter: brightness(1.12); }
.primary:disabled { opacity: 0.6; cursor: not-allowed; }

.error {
  color: var(--red);
  margin-top: 14px;
  font-size: 13px;
  text-align: center;
}

.links {
  display: flex;
  gap: 10px;
  justify-content: center;
  margin-top: 18px;
  font-size: 13px;
  color: var(--text-muted);
}
</style>
