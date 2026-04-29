<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { resetPassword } from '@/api/auth'
import { extractError } from '@/api/client'

const router = useRouter()
const username = ref('')
const phone = ref('')
const newPassword = ref('')
const error = ref('')
const success = ref(false)
const loading = ref(false)

async function submit(): Promise<void> {
  if (loading.value) return
  error.value = ''
  loading.value = true
  try {
    await resetPassword({
      username: username.value.trim(),
      phone: phone.value.trim(),
      new_password: newPassword.value,
    })
    success.value = true
    setTimeout(() => router.push('/login'), 1500)
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
      <h1>找回密码</h1>
      <form @submit.prevent="submit">
        <label>用户名 <input v-model="username" required /></label>
        <label>注册时填写的手机号 <input v-model="phone" required /></label>
        <label>新密码 <input v-model="newPassword" type="password" required /></label>
        <button type="submit" class="primary" :disabled="loading">
          {{ loading ? '提交中…' : '重置密码' }}
        </button>
      </form>
      <p v-if="success" class="success">密码已重置，正在跳转登录…</p>
      <p v-else-if="error" class="error">{{ error }}</p>
      <div class="links">
        <RouterLink to="/login">返回登录</RouterLink>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-page { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 24px; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 32px 36px; width: 100%; max-width: 380px; }
h1 { color: var(--accent); margin: 0 0 24px; font-size: 22px; letter-spacing: 1px; text-align: center; }
form { display: flex; flex-direction: column; gap: 14px; }
label { display: flex; flex-direction: column; gap: 6px; color: var(--text-dim); font-size: 13px; }
input { background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; color: var(--text); outline: none; }
input:focus { border-color: rgba(126, 184, 240, 0.6); }
.primary { background: linear-gradient(to right, rgba(70,120,200,0.9), rgba(100,150,230,0.9)); border: none; border-radius: 8px; color: white; padding: 10px; font-size: 14px; font-weight: 700; cursor: pointer; margin-top: 6px; }
.primary:hover:not(:disabled) { filter: brightness(1.12); }
.primary:disabled { opacity: 0.6; cursor: not-allowed; }
.error { color: var(--red); margin-top: 14px; font-size: 13px; text-align: center; }
.success { color: var(--green); margin-top: 14px; font-size: 13px; text-align: center; }
.links { display: flex; justify-content: center; margin-top: 18px; font-size: 13px; }
</style>
