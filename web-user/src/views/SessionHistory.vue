<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import {
  getSessionQA,
  listSessions,
  type SessionQA,
  type SessionRow,
} from '@/api/sessions'
import { extractError } from '@/api/client'

const route = useRoute()
const router = useRouter()
const sessionId = Number(route.params.id)

const session = ref<SessionRow | null>(null)
const qas = ref<SessionQA[]>([])
const loading = ref(true)
const error = ref('')

type AnswerTab = 'key_points' | 'script' | 'full'
const activeTab = ref<Record<number, AnswerTab>>({})

onMounted(async () => {
  loading.value = true
  try {
    qas.value = await getSessionQA(sessionId)
    // session 元信息从最近 100 条列表里找；找不到也不阻塞渲染
    try {
      const list = await listSessions(1, 100)
      session.value = list.items.find(s => s.id === sessionId) ?? null
    } catch { /* 静默忽略 */ }
  } catch (e) {
    error.value = extractError(e).message
  } finally {
    loading.value = false
  }
})

function tabOf(qa: SessionQA): AnswerTab {
  return activeTab.value[qa.id] ?? 'key_points'
}
function setTab(qa: SessionQA, t: AnswerTab): void {
  activeTab.value[qa.id] = t
}
function answerOf(qa: SessionQA, t: AnswerTab): string | null {
  if (t === 'key_points') return qa.answer_key_points
  if (t === 'script') return qa.answer_script
  return qa.answer_full
}
function formatDuration(start: string, end: string | null): string {
  if (!end) return '—'
  const s = (new Date(end + 'Z').getTime() - new Date(start + 'Z').getTime()) / 1000
  return `${Math.round(s)}s`
}
function formatTime(iso: string): string {
  const d = new Date(iso + 'Z')
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}
</script>

<template>
  <AppLayout>
    <div class="page-head">
      <h1 class="page-title">面试详情 #{{ sessionId }}</h1>
      <button class="ghost" @click="router.push('/')">回首页</button>
    </div>

    <p v-if="loading" class="empty">加载中…</p>
    <p v-else-if="error" class="msg-err">{{ error }}</p>

    <template v-else>
      <section v-if="session" class="card meta">
        <div><label>开始</label> {{ formatTime(session.started_at) }}</div>
        <div><label>结束</label> {{ session.ended_at ? formatTime(session.ended_at) : '—' }}</div>
        <div><label>时长</label> {{ session.total_seconds }}s</div>
        <div><label>状态</label>
          <span :class="['status', session.status]">
            {{ session.status === 'active' ? '进行中' : '已结束' }}
          </span>
        </div>
      </section>

      <p v-if="qas.length === 0" class="empty">本次面试没有产生问答记录。</p>

      <section v-for="qa in qas" :key="qa.id" class="card qa">
        <div class="qa-head">
          <span class="q-time">{{ formatTime(qa.asked_at) }}</span>
          <span class="q-source">{{ qa.source === 'detected' ? '自动检测' : '手动输入' }}</span>
          <span class="q-dur">耗时 {{ formatDuration(qa.asked_at, qa.finished_at) }}</span>
        </div>
        <p class="question">{{ qa.question }}</p>

        <div class="tabs">
          <button :class="{ active: tabOf(qa) === 'key_points' }" @click="setTab(qa, 'key_points')">要点</button>
          <button :class="{ active: tabOf(qa) === 'script' }" @click="setTab(qa, 'script')">话术</button>
          <button :class="{ active: tabOf(qa) === 'full' }" @click="setTab(qa, 'full')">完整</button>
        </div>
        <div class="answer">
          <pre v-if="answerOf(qa, tabOf(qa))">{{ answerOf(qa, tabOf(qa)) }}</pre>
          <p v-else class="empty">该段未生成。</p>
        </div>
      </section>
    </template>
  </AppLayout>
</template>

<style scoped>
.page-head { display: flex; align-items: center; justify-content: space-between; margin: 0 0 18px; }
.page-title { color: var(--accent); margin: 0; font-size: 22px; }

.empty { color: var(--text-muted); font-size: 14px; }
.msg-err { color: #f99; }

.card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 18px 22px; margin-bottom: 14px; }

.meta { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px 24px; }
.meta div { color: var(--text); font-size: 14px; }
.meta label { color: var(--text-dim); font-size: 11px; letter-spacing: 1px; text-transform: uppercase; margin-right: 8px; }

.status { padding: 2px 8px; border-radius: 6px; font-size: 12px; background: rgba(255,255,255,0.04); color: var(--text-muted); }
.status.active { color: #7eb8f0; background: rgba(126,184,240,0.12); }

.qa-head { display: flex; gap: 12px; color: var(--text-muted); font-size: 12px; margin-bottom: 8px; }
.q-source { background: rgba(126,184,240,0.08); color: #7eb8f0; padding: 2px 8px; border-radius: 6px; }
.qa .question { color: var(--text); font-size: 15px; font-weight: 700; margin: 0 0 12px; line-height: 1.6; }

.tabs { display: flex; gap: 4px; margin-bottom: 10px; border-bottom: 1px solid var(--border); }
.tabs button { background: transparent; border: none; color: var(--text-muted); padding: 8px 14px; cursor: pointer; font-size: 13px; border-bottom: 2px solid transparent; }
.tabs button.active { color: var(--accent); border-color: var(--accent); }

.answer pre {
  background: rgba(255,255,255,0.03);
  border-radius: 8px;
  padding: 12px 14px;
  margin: 0;
  color: var(--text);
  font-family: inherit;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

button.ghost {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-muted);
  border-radius: 8px;
  padding: 7px 16px;
  cursor: pointer;
  font-size: 13px;
}
button.ghost:hover { color: var(--text); }
</style>
