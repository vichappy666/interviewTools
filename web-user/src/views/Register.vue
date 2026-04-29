<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { register as registerApi } from '@/api/auth'
import { extractError } from '@/api/client'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const store = useUserStore()

const username = ref('')
const password = ref('')
const phone = ref('')
const error = ref('')
const loading = ref(false)

async function submit(): Promise<void> {
  if (loading.value) return
  error.value = ''
  if (username.value.trim().length < 3) {
    error.value = '用户名至少 3 个字符'
    return
  }
  if (password.value.length < 8) {
    error.value = '密码至少 8 位'
    return
  }
  if (!/[a-zA-Z]/.test(password.value) || !/\d/.test(password.value)) {
    error.value = '密码需要包含字母和数字'
    return
  }
  loading.value = true
  try {
    const payload: { username: string; password: string; phone?: string } = {
      username: username.value.trim(),
      password: password.value,
    }
    if (phone.value.trim()) payload.phone = phone.value.trim()
    const { token, user } = await registerApi(payload)
    store.setAuth(token, user)
    router.push('/')
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
      <h1>注册</h1>
      <form @submit.prevent="submit">
        <label>
          用户名
          <input v-model="username" autocomplete="username" required />
          <small>4-32 字符，可含字母 / 数字 / _ / -</small>
        </label>
        <label>
          密码
          <input v-model="password" type="password" autocomplete="new-password" required />
          <small>至少 8 位，包含字母和数字</small>
        </label>
        <label>
          手机号 <span class="optional">（选填，用于找回密码）</span>
          <input v-model="phone" autocomplete="tel" />
        </label>
        <button type="submit" class="primary" :disabled="loading">
          {{ loading ? '注册中…' : '注册' }}
        </button>
      </form>
      <p v-if="error" class="error">{{ error }}</p>
      <div class="links">
        已有账号？<RouterLink to="/login">登录</RouterLink>
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
h1 { color: var(--accent); margin: 0 0 24px; font-size: 22px; letter-spacing: 1px; text-align: center; }
form { display: flex; flex-direction: column; gap: 14px; }
label { display: flex; flex-direction: column; gap: 6px; color: var(--text-dim); font-size: 13px; }
small { color: var(--text-muted); font-size: 11px; }
.optional { color: var(--text-muted); font-weight: normal; }
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
.error { color: var(--red); margin-top: 14px; font-size: 13px; text-align: center; }
.links { display: flex; gap: 8px; justify-content: center; margin-top: 18px; font-size: 13px; color: var(--text-muted); }
</style>
