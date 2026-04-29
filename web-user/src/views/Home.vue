<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import JoinDialog from '@/components/JoinDialog.vue'
import { useUserStore } from '@/stores/user'
import { useRouter } from 'vue-router'
import {
  startSession as apiStart,
  getActiveSessions,
  listSessions,
  type SessionRow,
} from '@/api/sessions'

const store = useUserStore()
const router = useRouter()

const dialogVisible = ref(false)
const activeSessionId = ref<number | null>(null)
const activeStartedAt = ref<string>('')
const recentSessions = ref<SessionRow[]>([])
const loadingRecent = ref(false)
const error = ref<string | null>(null)

function describeStartError(e: any): string {
  const code = e?.response?.data?.error?.code ?? e?.response?.data?.detail?.error?.code
  if (code === 'INSUFFICIENT_BALANCE') return '余额不足，请先充值'
  if (code === 'SESSION_LIMIT') return '已达最大并发会话数（请先结束其他会话）'
  return '启动失败：' + (e?.message || '未知错误')
}

async function startInterview(): Promise<void> {
  error.value = null
  try {
    const active = await getActiveSessions()
    if (active.length > 0) {
      // 有 active → 弹窗，让用户选择加入或新开
      const a = active[0]
      activeSessionId.value = a.id
      activeStartedAt.value = a.started_at
      dialogVisible.value = true
      return
    }
    // 无 active → 直接开
    const r = await apiStart()
    router.push(`/session/${r.session_id}`)
  } catch (e: any) {
    error.value = describeStartError(e)
  }
}

function onJoin(): void {
  if (activeSessionId.value !== null) {
    router.push(`/session/${activeSessionId.value}`)
  }
  dialogVisible.value = false
}

async function onNew(): Promise<void> {
  dialogVisible.value = false
  error.value = null
  try {
    const r = await apiStart()
    router.push(`/session/${r.session_id}`)
  } catch (e: any) {
    error.value = describeStartError(e)
  }
}

function onCancel(): void {
  dialogVisible.value = false
  activeSessionId.value = null
}

function recharge(): void {
  alert('充值功能将在 M3 上线，敬请期待。')
}

function formatBalance(seconds: number): string {
  if (seconds <= 0) return '0s'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return `${h}h ${m}m ${s}s`
}

function formatRecentDate(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

async function loadRecent(): Promise<void> {
  loadingRecent.value = true
  try {
    const r = await listSessions(1, 5)
    recentSessions.value = r.items
  } catch {
    // 忽略：M2 不阻塞主流程
  } finally {
    loadingRecent.value = false
  }
}

onMounted(() => {
  loadRecent()
})
</script>

<template>
  <AppLayout>
    <section class="hero">
      <h1>欢迎回来{{ store.user ? '，' + store.user.username : '' }}</h1>
      <p class="hint">
        当前余额可用 <strong>{{ store.user ? formatBalance(store.user.balance_seconds) : '...' }}</strong>
      </p>
      <button class="big-cta" @click="startInterview">🎤 开始面试</button>
      <p v-if="error" class="error-msg">{{ error }}</p>
    </section>

    <section class="actions">
      <button class="action" @click="recharge">
        🪙 充值
        <span>买面试时间（M3 上线）</span>
      </button>
      <button class="action" @click="router.push('/ledger')">
        📜 余额流水
        <span>查看充值 / 扣费记录</span>
      </button>
      <button class="action" @click="router.push('/profile')">
        👤 个人资料
        <span>改手机号 / 改密码</span>
      </button>
    </section>

    <section class="recent">
      <h2>最近面试</h2>
      <p v-if="loadingRecent" class="empty">加载中...</p>
      <p v-else-if="recentSessions.length === 0" class="empty">暂无</p>
      <ul v-else class="recent-list">
        <li v-for="s in recentSessions" :key="s.id">
          <span class="recent-date">{{ formatRecentDate(s.started_at) }}</span>
          <span class="recent-status" :class="s.status">{{ s.status === 'active' ? '进行中' : '已结束' }}</span>
          <span class="recent-duration">{{ formatDuration(s.total_seconds) }}</span>
          <span class="recent-hint">M4 支持回看</span>
        </li>
      </ul>
    </section>

    <JoinDialog
      :visible="dialogVisible"
      :started-at="activeStartedAt"
      @join="onJoin"
      @new="onNew"
      @cancel="onCancel"
    />
  </AppLayout>
</template>

<style scoped>
.hero {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 50px 30px;
  text-align: center;
  margin-bottom: 24px;
}
.hero h1 { color: var(--accent); margin: 0 0 12px; font-size: 24px; }
.hint { color: var(--text-dim); margin: 0 0 30px; font-size: 14px; }
.hint strong { color: var(--text); }

.big-cta {
  background: linear-gradient(135deg, rgba(70,120,200,0.95), rgba(100,150,230,0.95));
  border: none;
  border-radius: 14px;
  color: white;
  padding: 22px 56px;
  font-size: 18px;
  font-weight: 700;
  cursor: pointer;
  letter-spacing: 1px;
  box-shadow: 0 8px 28px rgba(70, 120, 200, 0.35);
}
.big-cta:hover { filter: brightness(1.1); transform: translateY(-1px); }
.error-msg { color: #f99; margin-top: 14px; font-size: 13px; }

.actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
  margin-bottom: 24px;
}

.action {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 20px;
  color: var(--text);
  cursor: pointer;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 14px;
  font-weight: 700;
}
.action span {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: normal;
}
.action:hover { border-color: rgba(126,184,240,0.55); }

.recent {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 22px 24px;
}
.recent h2 { color: var(--text-dim); font-size: 13px; font-weight: 700; letter-spacing: 2px; margin: 0 0 12px; text-transform: uppercase; }
.empty { color: var(--text-muted); font-size: 13px; }

.recent-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 10px; }
.recent-list li {
  display: flex; align-items: center; gap: 14px;
  background: rgba(126,184,240,0.04);
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 13px;
}
.recent-date { color: var(--text); font-weight: 600; min-width: 90px; }
.recent-status { color: var(--text-muted); font-size: 12px; padding: 2px 8px; border-radius: 6px; background: rgba(255,255,255,0.04); }
.recent-status.active { color: #7eb8f0; background: rgba(126,184,240,0.12); }
.recent-duration { color: var(--text-dim); margin-left: auto; font-variant-numeric: tabular-nums; }
.recent-hint { color: var(--text-muted); font-size: 11px; }
</style>
