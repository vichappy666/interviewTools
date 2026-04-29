<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { stopSession as stopSessionApi } from '@/api/sessions'
import MarkdownPanel from '@/components/MarkdownPanel.vue'
import { useAudioCapture } from '@/composables/useAudioCapture'
import { useSessionStore, type AnswerSegment } from '@/stores/session'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const userStore = useUserStore()
const { start: startMic, stop: stopMic, error: micError } = useAudioCapture()

const sessionId = Number(route.params.id)
let ws: WebSocket | null = null
let pingTimer: number | null = null

// ---------------- 倒计时 HUD ----------------
const remainingDisplay = computed(() => {
  const s = Math.max(0, sessionStore.balanceSeconds)
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${String(r).padStart(2, '0')}`
})

// ---------------- 手动输入 ----------------
const manualText = ref('')

// ---------------- 复制按钮反馈 ----------------
const copiedFlag = ref<Record<AnswerSegment, boolean>>({
  key_points: false,
  script: false,
  full: false,
})

// ---------------- 划选浮动气泡 ----------------
const popupVisible = ref(false)
const popupX = ref(0)
const popupY = ref(0)
const selectedText = ref('')

function onSelectionChange(): void {
  const sel = window.getSelection()
  const text = sel ? sel.toString().trim() : ''
  if (!sel || !text || text.length < 2) {
    popupVisible.value = false
    return
  }
  // 限定只在转写区 / 问题区 / 回答区内才显示
  const node = sel.anchorNode as Node | null
  if (!node) {
    popupVisible.value = false
    return
  }
  const elNode = (node.nodeType === 1 ? (node as Element) : node.parentElement) as Element | null
  const inScope = elNode?.closest(
    '.transcript-pane, .questions-pane, .answer-area',
  )
  if (!inScope) {
    popupVisible.value = false
    return
  }
  if (sel.rangeCount === 0) {
    popupVisible.value = false
    return
  }
  const rect = sel.getRangeAt(0).getBoundingClientRect()
  selectedText.value = text
  popupX.value = Math.min(window.innerWidth - 140, rect.right + 6)
  popupY.value = Math.max(4, rect.top - 36)
  popupVisible.value = true
}

function hidePopup(): void {
  popupVisible.value = false
  selectedText.value = ''
}

function askSelected(): void {
  const t = selectedText.value
  hidePopup()
  if (!t || ws?.readyState !== WebSocket.OPEN) return
  ws.send(JSON.stringify({ type: 'ask_manual', text: t }))
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') hidePopup()
}

// ---------------- WebSocket ----------------
type WsIncoming =
  | { type: 'snapshot'; [k: string]: unknown }
  | { type: 'transcript_partial'; text: string }
  | { type: 'transcript_final'; text: string; ts: number }
  | { type: 'question_added'; qa_id: number; text: string; asked_at: number }
  | { type: 'answer_start'; qa_id: number; segment: AnswerSegment; question?: string }
  | { type: 'answer_chunk'; qa_id: number; segment: AnswerSegment; text: string }
  | { type: 'answer_end'; qa_id: number; segment: AnswerSegment }
  | { type: 'answer_error'; qa_id: number; segment: AnswerSegment; error: string }
  | { type: 'session_ended'; reason: string }
  | { type: 'balance_update'; balance_seconds: number }
  | { type: 'balance_low'; balance_seconds: number }
  | { type: 'pong' }
  | { type: 'error'; code: string; message: string }

function buildWsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const token = userStore.token ?? ''
  return `${proto}://${location.host}/ws/session/${sessionId}?token=${encodeURIComponent(token)}`
}

function connectWs(): void {
  sessionStore.connectionState = 'connecting'
  ws = new WebSocket(buildWsUrl())
  ws.binaryType = 'arraybuffer'

  ws.onopen = async () => {
    sessionStore.connectionState = 'connected'
    // 启麦：每帧 100ms 16kHz mono Int16 直接 ws.send
    try {
      await startMic((buf) => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(buf)
        }
      })
    } catch {
      // composable 已经 set error；这里不重复 alert
    }
    // 心跳 30s 一次
    pingTimer = window.setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, 30000)
  }

  ws.onmessage = (e: MessageEvent) => {
    if (typeof e.data !== 'string') return // 服务端不发二进制
    let msg: WsIncoming
    try {
      msg = JSON.parse(e.data) as WsIncoming
    } catch {
      return
    }
    dispatchMessage(msg)
  }

  ws.onclose = () => {
    sessionStore.connectionState = 'disconnected'
    cleanup()
  }

  ws.onerror = () => {
    sessionStore.error = '连接错误'
  }
}

function dispatchMessage(msg: WsIncoming): void {
  switch (msg.type) {
    case 'snapshot':
      sessionStore.handleSnapshot(msg as never)
      break
    case 'transcript_partial':
      sessionStore.handleTranscriptPartial(msg.text)
      break
    case 'transcript_final':
      sessionStore.handleTranscriptFinal(msg.text, msg.ts)
      break
    case 'question_added':
      sessionStore.handleQuestionAdded(msg.qa_id, msg.text, msg.asked_at)
      break
    case 'answer_start':
      sessionStore.handleAnswerStart(msg.qa_id, msg.segment, msg.question)
      break
    case 'answer_chunk':
      sessionStore.handleAnswerChunk(msg.qa_id, msg.segment, msg.text)
      break
    case 'answer_end':
      sessionStore.handleAnswerEnd(msg.qa_id, msg.segment)
      break
    case 'answer_error':
      sessionStore.handleAnswerError(msg.qa_id, msg.segment, msg.error)
      break
    case 'session_ended':
      sessionStore.sessionEnded = true
      sessionStore.endReason = msg.reason
      cleanup()
      // 1.5s 后自动跳首页（让用户看清结束原因）
      window.setTimeout(() => router.push('/'), 1500)
      break
    case 'balance_update':
      sessionStore.balanceSeconds = msg.balance_seconds
      break
    case 'balance_low':
      sessionStore.balanceLow = true
      sessionStore.balanceSeconds = msg.balance_seconds
      break
    case 'pong':
      break
    case 'error':
      sessionStore.error = msg.message
      break
  }
}

function cleanup(): void {
  stopMic()
  if (pingTimer !== null) {
    clearInterval(pingTimer)
    pingTimer = null
  }
  if (ws) {
    try {
      ws.onopen = null
      ws.onmessage = null
      ws.onclose = null
      ws.onerror = null
      if (
        ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CONNECTING
      ) {
        ws.close()
      }
    } catch {
      /* ignore */
    }
    ws = null
  }
}

// ---------------- 用户操作 ----------------
function clickQuestion(qa_id: number): void {
  if (!ws || ws.readyState !== WebSocket.OPEN) return
  // 有选区时让用户走划选气泡，不立即发问
  const sel = window.getSelection()
  if (sel && sel.toString().trim().length >= 2) return
  ws.send(JSON.stringify({ type: 'ask', qa_id }))
  sessionStore.markQuestionAsked(qa_id)
}

function sendManual(): void {
  const text = manualText.value.trim()
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return
  ws.send(JSON.stringify({ type: 'ask_manual', text }))
  manualText.value = ''
}

async function stopSession(): Promise<void> {
  if (!confirm('确认结束本次面试？')) return
  // 优先走 WS（让其他 join 的设备也收到 session_ended 广播）
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'stop' }))
  } else {
    // WS 已断开：走 REST 兜底
    try {
      await stopSessionApi(Number(route.params.id))
    } catch {
      // 忽略：可能 session 已经 ended
    }
  }
  cleanup()
  router.push('/')
}

function copySegment(seg: AnswerSegment): void {
  const text = sessionStore.currentAnswer?.[seg]
  if (!text) return
  // 复制时去掉 ** 标记，更适合粘贴到聊天框
  const clean = text.replace(/\*\*/g, '').trim()
  void navigator.clipboard.writeText(clean).then(() => {
    copiedFlag.value[seg] = true
    window.setTimeout(() => {
      copiedFlag.value[seg] = false
    }, 1500)
  })
}

// ---------------- 文案/状态 ----------------
const endReasonText = computed(() => {
  switch (sessionStore.endReason) {
    case 'user_stop':
      return '用户主动结束'
    case 'balance_zero':
      return '余额耗尽'
    case 'idle_timeout':
      return '空闲超时'
    case 'admin_force':
      return '管理员强制下线'
    case 'error':
      return '服务器异常'
    default:
      return sessionStore.endReason ?? '未知'
  }
})

const segmentLabel: Record<AnswerSegment, string> = {
  key_points: '要点',
  script: '话术',
  full: '完整答案',
}

const segments: AnswerSegment[] = ['key_points', 'script', 'full']

// ---------------- 生命周期 ----------------
onMounted(() => {
  if (!Number.isFinite(sessionId) || sessionId <= 0) {
    sessionStore.error = '会话 ID 非法'
    return
  }
  sessionStore.reset()
  sessionStore.sessionId = sessionId
  connectWs()
  document.addEventListener('selectionchange', onSelectionChange)
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('selectionchange', onSelectionChange)
  document.removeEventListener('keydown', onKeydown)
  cleanup()
})
</script>

<template>
  <div class="session-page">
    <!-- 顶栏 -->
    <header class="top-bar">
      <span class="dot" :class="sessionStore.connectionState"></span>
      <span class="title">面试中</span>
      <span class="conn-text" :class="sessionStore.connectionState">{{
        sessionStore.connectionState === 'connected'
          ? '● 已连接'
          : sessionStore.connectionState === 'connecting'
            ? '连接中...'
            : sessionStore.connectionState === 'disconnected'
              ? '● 已断开'
              : '--'
      }}</span>
      <span class="spacer"></span>
      <span class="hud" :class="{ low: sessionStore.balanceLow }">剩余 {{ remainingDisplay }}</span>
      <button class="stop-btn" @click="stopSession">🛑 结束</button>
    </header>

    <!-- 上半双栏 -->
    <div class="top-row">
      <section class="panel transcript-pane">
        <div class="section-label">实时转写</div>
        <div class="scroll-box transcript-box">
          <p v-for="(f, i) in sessionStore.transcriptFinals" :key="i" class="final-line">
            {{ f.text }}
          </p>
          <p v-if="sessionStore.transcriptPartial" class="partial-line">
            {{ sessionStore.transcriptPartial }}
          </p>
        </div>
      </section>

      <section class="panel questions-pane">
        <div class="section-label">识别的问题（点击发问）</div>
        <div class="scroll-box questions-box">
          <p v-if="sessionStore.questions.length === 0" class="empty">
            暂无识别问题；可在下方手动输入或在转写区划选发问
          </p>
          <div
            v-for="q in sessionStore.questions"
            :key="q.qa_id"
            class="q-item"
            :class="{ asked: q.asked }"
            @click="clickQuestion(q.qa_id)"
          >
            {{ q.text }}
          </div>
        </div>
      </section>
    </div>

    <!-- 中部手动输入框 -->
    <form class="ask-bar" @submit.prevent="sendManual">
      <input
        v-model="manualText"
        placeholder="手动输入问题，回车或点击发送..."
        autocomplete="off"
      />
      <button type="submit">🤖 发送</button>
    </form>

    <!-- 下半三段回答 -->
    <div class="section-label answer-label">AI 回答</div>
    <section class="answer-area">
      <p v-if="!sessionStore.currentAnswer" class="answer-empty">
        点击右侧问题或在转写区划选文字后发问...
      </p>
      <template v-else>
        <p v-if="sessionStore.currentAnswer.question" class="q-head">
          Q：{{ sessionStore.currentAnswer.question }}
        </p>
        <div v-for="seg in segments" :key="seg" class="answer-segment">
          <div class="segment-head">
            <span class="name">{{ segmentLabel[seg] }}</span>
            <span class="status" :class="{
              streaming: sessionStore.currentAnswer.loading[seg],
              done: !sessionStore.currentAnswer.loading[seg] && sessionStore.currentAnswer[seg],
              idle: !sessionStore.currentAnswer.loading[seg] && !sessionStore.currentAnswer[seg],
            }">
              {{
                sessionStore.currentAnswer.loading[seg]
                  ? '⏳ 生成中'
                  : sessionStore.currentAnswer[seg]
                    ? '✓ 已完成'
                    : '· 等待中'
              }}
            </span>
            <button class="copy-btn" type="button" @click="copySegment(seg)">
              {{ copiedFlag[seg] ? '已复制 ✓' : '📋 复制' }}
            </button>
          </div>
          <MarkdownPanel :text="sessionStore.currentAnswer[seg]" />
          <p v-if="sessionStore.currentAnswer.errors[seg]" class="seg-error">
            错误：{{ sessionStore.currentAnswer.errors[seg] }}
          </p>
        </div>
      </template>
    </section>

    <!-- 划选浮动气泡 -->
    <div
      v-if="popupVisible"
      class="selection-popup"
      :style="{ left: popupX + 'px', top: popupY + 'px' }"
    >
      <button type="button" class="ask-pop" @click="askSelected">🤖 问 AI</button>
      <button type="button" class="close-pop" @click="hidePopup">×</button>
    </div>

    <!-- 错误提示 toast -->
    <div v-if="micError" class="toast mic-toast">{{ micError }}</div>
    <div v-if="sessionStore.error" class="toast err-toast">{{ sessionStore.error }}</div>

    <!-- session ended overlay -->
    <div v-if="sessionStore.sessionEnded" class="ended-overlay">
      <div class="ended-card">
        <h2>面试已结束</h2>
        <p>原因：{{ endReasonText }}</p>
        <button class="primary" @click="router.push('/')">返回首页</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.session-page {
  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  padding: 14px;
  gap: 10px;
  box-sizing: border-box;
  background: radial-gradient(ellipse at top, #1a1a2e 0%, var(--bg0) 70%);
  overflow: hidden;
}

/* ---------- 顶栏 ---------- */
.top-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  background: rgba(15, 18, 26, 0.85);
  backdrop-filter: blur(8px);
  border: 1px solid var(--border);
  border-radius: 10px;
}
.top-bar .dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--text-muted);
  box-shadow: 0 0 6px currentColor;
}
.top-bar .dot.connected {
  background: var(--green);
}
.top-bar .dot.connecting {
  background: #fbbf24;
}
.top-bar .dot.disconnected {
  background: var(--red);
}
.top-bar .title {
  color: var(--accent);
  font-weight: 700;
  font-size: 15px;
  letter-spacing: 1px;
}
.top-bar .conn-text {
  color: var(--text-muted);
  font-size: 11px;
}
.top-bar .conn-text.connected {
  color: var(--green);
}
.top-bar .conn-text.disconnected {
  color: var(--red);
}
.top-bar .spacer {
  flex: 1;
}
.top-bar .hud {
  background: rgba(126, 184, 240, 0.12);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
}
.top-bar .hud.low {
  color: var(--red);
  border-color: rgba(248, 113, 113, 0.5);
  background: rgba(248, 113, 113, 0.12);
}
.top-bar .stop-btn {
  background: rgba(248, 113, 113, 0.12);
  border: 1px solid rgba(248, 113, 113, 0.5);
  color: var(--red);
  padding: 6px 14px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 700;
}
.top-bar .stop-btn:hover {
  background: rgba(248, 113, 113, 0.22);
}

/* ---------- 上半双栏 ---------- */
.top-row {
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 10px;
  height: 38vh;
  min-height: 240px;
}

.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.section-label {
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 2px;
  margin-bottom: 6px;
}
.scroll-box {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
  color: var(--text);
  line-height: 1.6;
  user-select: text;
}
.transcript-box {
  font-family: 'SF Mono', Menlo, monospace;
  font-size: 13px;
  white-space: pre-wrap;
}
.transcript-box .final-line {
  margin: 0 0 4px 0;
}
.transcript-box .partial-line {
  margin: 0;
  color: var(--text-dim);
  font-style: italic;
}
.questions-box {
  font-size: 13px;
}
.questions-box .empty {
  color: var(--text-muted);
  font-size: 12px;
}
.q-item {
  padding: 4px 0;
  cursor: pointer;
  transition: color 0.15s;
}
.q-item:hover {
  color: var(--accent);
}
.q-item.asked {
  color: var(--text-muted);
}
.q-item:not(:last-child) {
  border-bottom: 1px dashed rgba(255, 255, 255, 0.04);
}

/* ---------- 手动输入 ---------- */
.ask-bar {
  display: flex;
  gap: 8px;
}
.ask-bar input {
  flex: 1;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 8px 12px;
  font-size: 13px;
  outline: none;
}
.ask-bar input:focus {
  border-color: rgba(100, 140, 200, 0.6);
}
.ask-bar button {
  background: linear-gradient(to right, rgba(70, 120, 200, 0.9), rgba(100, 150, 230, 0.9));
  border: none;
  border-radius: 8px;
  color: white;
  padding: 8px 18px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.ask-bar button:hover {
  filter: brightness(1.12);
}

/* ---------- 回答区 ---------- */
.answer-label {
  padding-left: 4px;
}
.answer-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 14px;
}
.answer-empty {
  color: var(--text-muted);
  margin: 0;
}
.q-head {
  color: var(--accent);
  font-weight: 700;
  font-size: 14px;
  margin: 0 0 10px;
}
.answer-segment {
  margin-bottom: 12px;
}
.segment-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.segment-head .name {
  color: var(--accent);
  font-weight: 700;
}
.segment-head .status {
  font-size: 11px;
}
.segment-head .status.idle {
  color: var(--text-muted);
}
.segment-head .status.streaming {
  color: #fbbf24;
}
.segment-head .status.done {
  color: var(--green);
}
.segment-head .copy-btn {
  margin-left: auto;
  background: rgba(255, 255, 255, 0.08);
  border: none;
  border-radius: 5px;
  color: var(--text-dim);
  padding: 3px 10px;
  font-size: 11px;
  cursor: pointer;
}
.segment-head .copy-btn:hover {
  background: rgba(255, 255, 255, 0.18);
  color: var(--text);
}
.seg-error {
  color: var(--red);
  font-size: 12px;
  margin: 4px 0 0;
}

/* ---------- 划选气泡 ---------- */
.selection-popup {
  position: fixed;
  z-index: 1000;
  display: inline-flex;
  gap: 4px;
  background: #1a1a2e;
  border: 1px solid rgba(126, 184, 240, 0.4);
  border-radius: 8px;
  padding: 4px 6px;
}
.selection-popup button {
  border: none;
  border-radius: 5px;
  padding: 4px 10px;
  font-size: 11px;
  cursor: pointer;
  font-weight: 700;
}
.selection-popup .ask-pop {
  background: linear-gradient(to right, rgba(70, 120, 200, 0.95), rgba(100, 150, 230, 0.95));
  color: white;
}
.selection-popup .close-pop {
  background: rgba(255, 255, 255, 0.15);
  color: var(--text-dim);
}

/* ---------- toast ---------- */
.toast {
  position: fixed;
  right: 16px;
  bottom: 16px;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  z-index: 1100;
  max-width: 360px;
  box-shadow: var(--shadow);
}
.mic-toast {
  background: rgba(251, 191, 36, 0.12);
  border: 1px solid rgba(251, 191, 36, 0.5);
  color: #fbbf24;
}
.err-toast {
  background: rgba(248, 113, 113, 0.12);
  border: 1px solid rgba(248, 113, 113, 0.5);
  color: var(--red);
  bottom: 64px;
}

/* ---------- ended overlay ---------- */
.ended-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1200;
  backdrop-filter: blur(4px);
}
.ended-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 32px 36px;
  text-align: center;
  min-width: 280px;
}
.ended-card h2 {
  color: var(--accent);
  margin: 0 0 12px;
  font-size: 20px;
}
.ended-card p {
  color: var(--text-dim);
  margin: 0 0 20px;
  font-size: 14px;
}
.ended-card .primary {
  background: linear-gradient(135deg, rgba(70, 120, 200, 0.95), rgba(100, 150, 230, 0.95));
  border: none;
  border-radius: 10px;
  color: white;
  padding: 10px 28px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}
.ended-card .primary:hover {
  filter: brightness(1.1);
}

/* ---------- 滚动条 ---------- */
.scroll-box::-webkit-scrollbar,
.answer-area::-webkit-scrollbar {
  width: 8px;
}
.scroll-box::-webkit-scrollbar-thumb,
.answer-area::-webkit-scrollbar-thumb {
  background: rgba(100, 140, 200, 0.25);
  border-radius: 4px;
}
.scroll-box::-webkit-scrollbar-thumb:hover,
.answer-area::-webkit-scrollbar-thumb:hover {
  background: rgba(100, 140, 200, 0.45);
}
</style>
