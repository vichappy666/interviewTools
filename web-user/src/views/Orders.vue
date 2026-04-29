<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import {
  listOrders,
  type OrderRow,
  type OrderStatus,
} from '@/api/recharge'
import { extractError } from '@/api/client'

const router = useRouter()

const items = ref<OrderRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(true)
const error = ref('')

const statusLabel: Record<OrderStatus, string> = {
  pending: '待支付',
  submitted: '已提交',
  verifying: '核验中',
  succeeded: '成功',
  failed: '失败',
  expired: '已过期',
}

function formatTime(iso: string): string {
  const d = new Date(iso + 'Z')
  const Y = d.getFullYear()
  const M = String(d.getMonth() + 1).padStart(2, '0')
  const D = String(d.getDate()).padStart(2, '0')
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  return `${Y}-${M}-${D} ${h}:${m}`
}

async function load(p = page.value): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const r = await listOrders(p, size.value)
    items.value = r.items
    total.value = r.total
    page.value = r.page
  } catch (e) {
    error.value = extractError(e).message
  } finally {
    loading.value = false
  }
}

function goPay(o: OrderRow): void {
  router.push(`/recharge/${o.id}`)
}

onMounted(load)
</script>

<template>
  <AppLayout>
    <div class="page-head">
      <h1 class="page-title">充值历史</h1>
      <button class="primary" @click="router.push('/recharge')">+ 新充值</button>
    </div>

    <p v-if="loading" class="empty">加载中…</p>
    <p v-else-if="error" class="msg-err">{{ error }}</p>
    <p v-else-if="items.length === 0" class="empty">还没有充值记录。</p>

    <section v-else class="card">
      <ul class="orders">
        <li v-for="o in items" :key="o.id" class="order-row">
          <div class="col-time">{{ formatTime(o.created_at) }}</div>
          <div class="col-amount">{{ o.amount_usdt }} <span>USDT</span></div>
          <div class="col-status">
            <span class="status" :class="o.status">{{ statusLabel[o.status] }}</span>
          </div>
          <div class="col-detail">
            <span v-if="o.status === 'succeeded'">+{{ o.granted_seconds }}s</span>
            <span v-else-if="o.status === 'failed'" class="fail" :title="o.fail_reason || ''">
              {{ o.fail_reason || '失败' }}
            </span>
            <span v-else class="muted">—</span>
          </div>
          <div class="col-action">
            <button
              v-if="o.status === 'pending' || o.status === 'failed'"
              class="ghost"
              @click="goPay(o)"
            >
              {{ o.status === 'failed' ? '重试' : '继续支付' }}
            </button>
            <button v-else class="ghost" @click="goPay(o)">查看</button>
          </div>
        </li>
      </ul>

      <div v-if="total > size" class="pager">
        <button class="ghost" :disabled="page <= 1" @click="load(page - 1)">上一页</button>
        <span class="page-num">第 {{ page }} 页 / 共 {{ Math.ceil(total / size) }} 页</span>
        <button class="ghost" :disabled="page * size >= total" @click="load(page + 1)">下一页</button>
      </div>
    </section>
  </AppLayout>
</template>

<style scoped>
.page-head {
  display: flex; align-items: center; justify-content: space-between;
  margin: 0 0 18px;
}
.page-title { color: var(--accent); margin: 0; font-size: 22px; }

.empty { color: var(--text-muted); font-size: 14px; }

.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 20px;
}

.orders { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
.order-row {
  display: grid;
  grid-template-columns: 140px 110px 90px 1fr 110px;
  align-items: center;
  gap: 12px;
  background: rgba(126,184,240,0.04);
  padding: 12px 14px;
  border-radius: 10px;
  font-size: 13px;
}
.col-time { color: var(--text); font-variant-numeric: tabular-nums; }
.col-amount { color: var(--text); font-weight: 700; }
.col-amount span { color: var(--text-muted); font-weight: normal; font-size: 12px; }

.status { padding: 4px 10px; border-radius: 6px; font-size: 12px; background: rgba(255,255,255,0.04); color: var(--text-muted); }
.status.pending { color: #7eb8f0; background: rgba(126,184,240,0.12); }
.status.submitted, .status.verifying { color: #f0c87e; background: rgba(240,200,126,0.12); }
.status.succeeded { color: #7af0a5; background: rgba(122,240,165,0.12); }
.status.failed { color: #f99; background: rgba(255,153,153,0.12); }
.status.expired { color: var(--text-muted); }

.col-detail { color: var(--text-dim); }
.col-detail .fail {
  color: #f99;
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.col-detail .muted { color: var(--text-muted); }

.col-action { text-align: right; }

button.primary {
  background: linear-gradient(135deg, rgba(70,120,200,0.95), rgba(100,150,230,0.95));
  border: none; border-radius: 8px;
  color: white;
  padding: 9px 18px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  letter-spacing: 0.5px;
}
button.primary:hover { filter: brightness(1.1); }

button.ghost {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-muted);
  border-radius: 6px;
  padding: 6px 14px;
  cursor: pointer;
  font-size: 12px;
}
button.ghost:hover:not(:disabled) { color: var(--text); border-color: rgba(126,184,240,0.55); }
button.ghost:disabled { opacity: 0.4; cursor: not-allowed; }

.pager {
  display: flex; align-items: center; gap: 14px;
  justify-content: center;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
.page-num { color: var(--text-muted); font-size: 12px; }

.msg-err { color: #f99; font-size: 13px; }
</style>
