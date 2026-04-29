<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { changePassword, updateMe } from '@/api/users'
import { extractError } from '@/api/client'
import { useUserStore } from '@/stores/user'

const store = useUserStore()

const phone = ref('')
const phoneMsg = ref('')
const phoneErr = ref('')
const phoneLoading = ref(false)

const oldPass = ref('')
const newPass = ref('')
const passMsg = ref('')
const passErr = ref('')
const passLoading = ref(false)

onMounted(async () => {
  if (store.token && !store.user) {
    try { await store.fetchMe() } catch { /* interceptor handles 401 */ }
  }
  phone.value = store.user?.phone ?? ''
})

async function savePhone(): Promise<void> {
  phoneMsg.value = ''
  phoneErr.value = ''
  phoneLoading.value = true
  try {
    const updated = await updateMe({ phone: phone.value.trim() || null })
    store.user = updated
    phoneMsg.value = '已保存'
  } catch (err) {
    phoneErr.value = extractError(err).message
  } finally {
    phoneLoading.value = false
  }
}

async function savePassword(): Promise<void> {
  passMsg.value = ''
  passErr.value = ''
  passLoading.value = true
  try {
    await changePassword({ old_password: oldPass.value, new_password: newPass.value })
    passMsg.value = '密码已更新'
    oldPass.value = ''
    newPass.value = ''
  } catch (err) {
    passErr.value = extractError(err).message
  } finally {
    passLoading.value = false
  }
}
</script>

<template>
  <AppLayout>
    <h1 class="page-title">个人资料</h1>

    <section class="card">
      <h2>账号信息</h2>
      <div class="field">
        <label>用户名</label>
        <span>{{ store.user?.username || '...' }}</span>
      </div>
    </section>

    <section class="card">
      <h2>修改手机号</h2>
      <form @submit.prevent="savePhone">
        <input v-model="phone" placeholder="留空表示清除手机号" />
        <button class="primary" :disabled="phoneLoading">
          {{ phoneLoading ? '保存中…' : '保存' }}
        </button>
      </form>
      <p v-if="phoneMsg" class="msg-ok">{{ phoneMsg }}</p>
      <p v-if="phoneErr" class="msg-err">{{ phoneErr }}</p>
    </section>

    <section class="card">
      <h2>修改密码</h2>
      <form @submit.prevent="savePassword">
        <input v-model="oldPass" type="password" placeholder="旧密码" autocomplete="current-password" required />
        <input v-model="newPass" type="password" placeholder="新密码（至少 8 位，含字母和数字）" autocomplete="new-password" required />
        <button class="primary" :disabled="passLoading">
          {{ passLoading ? '更新中…' : '更新密码' }}
        </button>
      </form>
      <p v-if="passMsg" class="msg-ok">{{ passMsg }}</p>
      <p v-if="passErr" class="msg-err">{{ passErr }}</p>
    </section>
  </AppLayout>
</template>

<style scoped>
.page-title { color: var(--accent); margin: 0 0 18px; font-size: 22px; }
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 22px 24px;
  margin-bottom: 16px;
}
.card h2 {
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 2px;
  text-transform: uppercase;
  margin: 0 0 14px;
}
.field {
  display: flex;
  gap: 10px;
  font-size: 14px;
}
.field label {
  color: var(--text-muted);
  width: 80px;
}
.field span {
  color: var(--text);
}
form {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
input {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--text);
  outline: none;
  flex: 1;
  min-width: 200px;
}
input:focus { border-color: rgba(126, 184, 240, 0.6); }
.primary {
  background: linear-gradient(to right, rgba(70,120,200,0.9), rgba(100,150,230,0.9));
  border: none;
  border-radius: 8px;
  color: white;
  padding: 10px 22px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.primary:disabled { opacity: 0.6; cursor: not-allowed; }
.msg-ok { color: var(--green); margin-top: 10px; font-size: 12px; }
.msg-err { color: var(--red); margin-top: 10px; font-size: 12px; }
</style>
