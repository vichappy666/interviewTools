<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { extractError } from '@/api/client'

const router = useRouter()
const store = useUserStore()
const errorMsg = ref('')

onMounted(async () => {
  if (store.token && !store.user) {
    try {
      await store.fetchMe()
    } catch (err) {
      const e = extractError(err)
      // 401 already handled by interceptor; here mostly network errors.
      errorMsg.value = e.message
    }
  }
})

function formatBalance(seconds: number): string {
  if (seconds <= 0) return '0s'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const parts: string[] = []
  if (h) parts.push(`${h}h`)
  if (m || h) parts.push(`${m}m`)
  parts.push(`${s}s`)
  return parts.join('')
}

function logout(): void {
  store.logout()
  router.push('/login')
}
</script>

<template>
  <div class="app-layout">
    <header class="topbar">
      <div class="brand" @click="router.push('/')">
        <span class="dot" />
        <span class="title">面试助手</span>
      </div>
      <div class="spacer" />
      <div v-if="store.user" class="topbar-right">
        <button class="balance-pill" @click="router.push('/ledger')" title="查看余额流水">
          余额 <strong>{{ formatBalance(store.user.balance_seconds) }}</strong>
        </button>
        <span class="username" @click="router.push('/profile')">
          👤 {{ store.user.username }}
        </span>
        <button class="logout-btn" @click="logout">退出</button>
      </div>
    </header>
    <main class="content">
      <p v-if="errorMsg" class="error-banner">{{ errorMsg }}</p>
      <slot />
    </main>
  </div>
</template>

<style scoped>
.app-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 28px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.brand .dot {
  width: 10px; height: 10px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 6px currentColor;
}

.brand .title {
  color: var(--accent);
  font-weight: 700;
  letter-spacing: 1px;
}

.spacer { flex: 1; }

.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.balance-pill {
  background: rgba(126, 184, 240, 0.12);
  border: 1px solid var(--border);
  color: var(--text-dim);
  padding: 6px 14px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 13px;
}
.balance-pill strong {
  color: var(--text);
  margin-left: 4px;
}
.balance-pill:hover { background: rgba(126, 184, 240, 0.22); }

.username {
  color: var(--text-dim);
  cursor: pointer;
  font-size: 13px;
}
.username:hover { color: var(--accent); }

.logout-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-dim);
  padding: 4px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
}
.logout-btn:hover { color: var(--red); border-color: var(--red); }

.content {
  flex: 1;
  padding: 28px;
  max-width: 1100px;
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
}

.error-banner {
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.4);
  color: var(--red);
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 13px;
}
</style>
