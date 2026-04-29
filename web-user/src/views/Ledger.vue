<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { listLedger, type LedgerItem } from '@/api/balance'
import { extractError } from '@/api/client'

const items = ref<LedgerItem[]>([])
const total = ref(0)
const page = ref(1)
const size = 20
const loading = ref(false)
const error = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await listLedger(page.value, size)
    items.value = data.items
    total.value = data.total
  } catch (err) {
    error.value = extractError(err).message
  } finally {
    loading.value = false
  }
}

onMounted(load)

function reasonLabel(r: string): string {
  const m: Record<string, string> = {
    recharge: '充值',
    session: '会话扣费',
    admin_grant: '管理员发放',
    admin_revoke: '管理员扣减',
    refund: '退款',
  }
  return m[r] || r
}

function formatDelta(s: number): string {
  const sign = s >= 0 ? '+' : ''
  return `${sign}${s}s`
}

function formatTime(s: string): string {
  const d = new Date(s)
  if (isNaN(d.getTime())) return s
  return d.toLocaleString('zh-CN', { hour12: false })
}

function prev(): void { if (page.value > 1) { page.value--; load() } }
function next(): void {
  const maxPage = Math.max(1, Math.ceil(total.value / size))
  if (page.value < maxPage) { page.value++; load() }
}
</script>

<template>
  <AppLayout>
    <h1 class="page-title">余额流水</h1>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading" class="loading">加载中…</p>

    <table v-if="items.length > 0" class="ledger">
      <thead>
        <tr>
          <th>时间</th>
          <th>类型</th>
          <th class="num">变动</th>
          <th class="num">余额</th>
          <th>备注</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item.id">
          <td>{{ formatTime(item.created_at) }}</td>
          <td>{{ reasonLabel(item.reason) }}</td>
          <td class="num" :class="{ pos: item.delta_seconds > 0, neg: item.delta_seconds < 0 }">
            {{ formatDelta(item.delta_seconds) }}
          </td>
          <td class="num">{{ item.balance_after }}s</td>
          <td>{{ item.note || '—' }}</td>
        </tr>
      </tbody>
    </table>

    <p v-else-if="!loading && !error" class="empty">暂无流水</p>

    <div class="pager" v-if="total > size">
      <button :disabled="page === 1" @click="prev">上一页</button>
      <span>第 {{ page }} / {{ Math.max(1, Math.ceil(total / size)) }} 页（共 {{ total }} 条）</span>
      <button :disabled="page >= Math.ceil(total / size)" @click="next">下一页</button>
    </div>
  </AppLayout>
</template>

<style scoped>
.page-title { color: var(--accent); margin: 0 0 18px; font-size: 22px; }
.error { color: var(--red); }
.loading { color: var(--text-muted); }
.empty {
  color: var(--text-muted);
  text-align: center;
  padding: 40px;
  background: var(--panel);
  border: 1px dashed var(--border);
  border-radius: 12px;
}

.ledger {
  width: 100%;
  border-collapse: collapse;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
}
.ledger th, .ledger td {
  padding: 10px 14px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}
.ledger th {
  background: rgba(0,0,0,0.3);
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.ledger td { font-size: 13px; color: var(--text); }
.ledger tr:last-child td { border-bottom: none; }
.num { text-align: right; font-family: "SF Mono", Menlo, monospace; }
.num.pos { color: var(--green); }
.num.neg { color: var(--red); }

.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-top: 18px;
  font-size: 13px;
  color: var(--text-dim);
}
.pager button {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-dim);
  padding: 5px 14px;
  border-radius: 6px;
  cursor: pointer;
}
.pager button:disabled { opacity: 0.4; cursor: not-allowed; }
.pager button:hover:not(:disabled) { color: var(--accent); border-color: var(--accent); }
</style>
