<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import QRCode from 'qrcode'
import AppLayout from '@/components/AppLayout.vue'
import {
  getOrder,
  submitHash,
  type OrderRow,
  type OrderStatus,
} from '@/api/recharge'
import { extractError } from '@/api/client'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const orderId = Number(route.params.id)
const order = ref<OrderRow | null>(null)
const loading = ref(true)
const loadError = ref('')

const qrCanvas = ref<HTMLCanvasElement | null>(null)

const txHash = ref('')
const submitting = ref(false)
const submitError = ref('')
const successMsg = ref('')
const copyMsg = ref('')

const remaining = ref(0) // seconds to expiry
let timer: number | null = null

const statusLabel: Record<OrderStatus, string> = {
  pending: '等待支付',
  submitted: '已提交',
  verifying: '链上核验中',
  succeeded: '充值成功',
  failed: '失败',
  expired: '已过期',
}

const statusClass = computed(() => order.value?.status ?? 'pending')

function formatRemaining(s: number): string {
  if (s <= 0) return '已过期'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return `${h}h ${m}m ${sec}s`
}

function tickRemaining(): void {
  if (!order.value) {
    remaining.value = 0
    return
  }
  const expires = new Date(order.value.expires_at + 'Z').getTime()
  remaining.value = Math.max(0, Math.floor((expires - Date.now()) / 1000))
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    order.value = await getOrder(orderId)
  } catch (e) {
    loadError.value = extractError(e).message
  } finally {
    loading.value = false
    tickRemaining()
  }
}

async function drawQR(): Promise<void> {
  if (!order.value || !qrCanvas.value) return
  try {
    await QRCode.toCanvas(qrCanvas.value, order.value.to_address, {
      width: 192,
      margin: 1,
      color: { dark: '#0a0a14', light: '#ffffff' },
    })
  } catch {
    // 二维码失败不影响主流程，地址仍可文本复制
  }
}

async function copyAddr(): Promise<void> {
  if (!order.value) return
  try {
    await navigator.clipboard.writeText(order.value.to_address)
    copyMsg.value = '已复制'
    setTimeout(() => { copyMsg.value = '' }, 1500)
  } catch {
    copyMsg.value = '复制失败，请手动选中地址'
  }
}

async function submit(): Promise<void> {
  submitError.value = ''
  successMsg.value = ''
  const hash = txHash.value.trim()
  if (!hash) { submitError.value = '请填写交易 hash'; return }
  submitting.value = true
  try {
    const updated = await submitHash(orderId, hash)
    order.value = updated
    if (updated.status === 'succeeded') {
      successMsg.value = `充值成功，已加 ${updated.granted_seconds} 秒。3 秒后跳转充值历史…`
      // 余额变了，刷新一下
      void store.fetchMe().catch(() => {})
      setTimeout(() => { router.push('/orders') }, 3000)
    }
  } catch (e) {
    submitError.value = extractError(e).message
    // 失败后重新拉一下订单（status 可能变成 failed）
    void load()
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await load()
  await drawQR()
  timer = window.setInterval(tickRemaining, 1000)
})

watch(order, () => { void drawQR() })

onBeforeUnmount(() => {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
})
</script>

<template>
  <AppLayout>
    <h1 class="page-title">USDT-TRC20 充值</h1>

    <p v-if="loading" class="empty">加载中…</p>
    <section v-else-if="loadError" class="card">
      <p class="msg-err">{{ loadError }}</p>
      <button class="ghost" @click="router.push('/recharge')">返回</button>
    </section>

    <template v-else-if="order">
      <section class="card">
        <h2>步骤 2：用钱包向以下地址转账</h2>
        <div class="amount-row">
          <span class="big">{{ order.amount_usdt }}</span>
          <span class="unit">USDT</span>
          <span class="net">TRC20 (Tron)</span>
        </div>

        <div class="qr-row">
          <canvas ref="qrCanvas" class="qr"></canvas>
          <div class="addr-block">
            <label>收款地址</label>
            <div class="addr-line">
              <code>{{ order.to_address }}</code>
              <button class="copy-btn" @click="copyAddr">{{ copyMsg || '复制' }}</button>
            </div>
            <label class="mt">订单状态</label>
            <span class="status" :class="statusClass">{{ statusLabel[order.status] }}</span>
            <label class="mt">订单有效期剩余</label>
            <span class="countdown" :class="{ 'expired': remaining === 0 }">
              {{ formatRemaining(remaining) }}
            </span>
            <label class="mt">必须从此钱包转出</label>
            <code class="from-addr">{{ order.from_address }}</code>
          </div>
        </div>

        <p class="hint">
          ⚠️ 本订单只接受从上面这个钱包地址转出，金额必须 ≥ <strong>{{ order.amount_usdt }}</strong> USDT。
          转账后请等约 1 分钟（19 个区块）再提交 hash 核验。
        </p>
      </section>

      <section
        v-if="order.status === 'pending' || order.status === 'failed'"
        class="card"
      >
        <h2>步骤 3：粘贴交易 Hash 提交核验</h2>
        <p class="hint" v-if="order.status === 'failed' && order.fail_reason">
          上次失败原因：<span class="fail-reason">{{ order.fail_reason }}</span>。
          可以再次尝试提交（hash 必须与之前不同，或联系管理员重置订单）。
        </p>
        <form @submit.prevent="submit">
          <div class="field">
            <label>Tron 交易 Hash（64 位 hex，可带 0x）</label>
            <input
              v-model="txHash"
              type="text"
              placeholder="转账后从钱包复制 transaction hash"
              spellcheck="false"
            />
          </div>
          <button class="primary" type="submit" :disabled="submitting">
            {{ submitting ? '链上核验中…' : '提交核验' }}
          </button>
        </form>
        <p v-if="submitError" class="msg-err">{{ submitError }}</p>
        <p v-if="successMsg" class="msg-ok">{{ successMsg }}</p>
      </section>

      <section v-else-if="order.status === 'succeeded'" class="card success">
        <h2>充值已完成</h2>
        <p>已为账户增加 <strong>{{ order.granted_seconds }}</strong> 秒面试时长。</p>
        <button class="primary" @click="router.push('/')">回首页</button>
      </section>

      <section v-else-if="order.status === 'expired'" class="card">
        <h2>订单已过期</h2>
        <p class="hint">订单已超过 24 小时有效期，请重新创建。</p>
        <button class="primary" @click="router.push('/recharge')">重新创建</button>
      </section>

      <section v-else class="card">
        <h2>订单状态：{{ statusLabel[order.status] }}</h2>
        <p class="hint">链上核验中，请稍候。</p>
      </section>
    </template>
  </AppLayout>
</template>

<style scoped>
.page-title { color: var(--accent); margin: 0 0 18px; font-size: 22px; }
.empty { color: var(--text-muted); font-size: 14px; }

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

.amount-row { display: flex; align-items: baseline; gap: 8px; margin-bottom: 16px; }
.big { color: var(--accent); font-size: 32px; font-weight: 700; }
.unit { color: var(--text-dim); font-size: 14px; }
.net {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 12px;
  background: rgba(126,184,240,0.1);
  padding: 4px 10px;
  border-radius: 6px;
}

.qr-row {
  display: flex;
  gap: 24px;
  align-items: flex-start;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.qr {
  background: white;
  border-radius: 10px;
  padding: 8px;
}
.addr-block {
  flex: 1; min-width: 280px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.addr-block label {
  color: var(--text-dim);
  font-size: 11px;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.addr-block .mt { margin-top: 12px; }
.addr-line {
  display: flex; gap: 8px; align-items: center;
}
.addr-line code, .from-addr {
  flex: 1;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 9px 12px;
  font-family: ui-monospace, monospace;
  font-size: 13px;
  color: var(--text);
  word-break: break-all;
}
.copy-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-dim);
  border-radius: 6px;
  padding: 8px 14px;
  cursor: pointer;
  font-size: 12px;
}
.copy-btn:hover { color: var(--text); border-color: rgba(126,184,240,0.55); }

.status {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  background: rgba(255,255,255,0.04);
  color: var(--text-muted);
  align-self: flex-start;
}
.status.pending { color: #7eb8f0; background: rgba(126,184,240,0.12); }
.status.submitted, .status.verifying { color: #f0c87e; background: rgba(240,200,126,0.12); }
.status.succeeded { color: #7af0a5; background: rgba(122,240,165,0.12); }
.status.failed { color: #f99; background: rgba(255,153,153,0.12); }
.status.expired { color: var(--text-muted); }

.countdown { color: var(--text); font-variant-numeric: tabular-nums; }
.countdown.expired { color: #f99; }

.hint {
  color: var(--text-muted);
  font-size: 13px;
  margin: 6px 0 0;
  line-height: 1.6;
}
.hint strong { color: var(--text); }
.fail-reason { color: #f99; }

.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.field label { color: var(--text-dim); font-size: 12px; letter-spacing: 1px; text-transform: uppercase; }
.field input {
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--text);
  font-size: 14px;
  font-family: ui-monospace, monospace;
}
.field input:focus { outline: none; border-color: rgba(126,184,240,0.55); }

button.primary {
  background: linear-gradient(135deg, rgba(70,120,200,0.95), rgba(100,150,230,0.95));
  border: none; border-radius: 10px;
  color: white;
  padding: 11px 28px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  letter-spacing: 1px;
}
button.primary:disabled { opacity: 0.6; cursor: wait; }
button.primary:hover:not(:disabled) { filter: brightness(1.1); }

button.ghost {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-muted);
  border-radius: 8px;
  padding: 8px 18px;
  cursor: pointer;
  margin-top: 12px;
}

.msg-err { color: #f99; margin-top: 12px; font-size: 13px; }
.msg-ok { color: #7af0a5; margin-top: 12px; font-size: 13px; }

.success p { color: var(--text); margin-bottom: 14px; }
.success strong { color: var(--accent); font-size: 18px; }
</style>
