<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import AdminLayout from '@/components/AdminLayout.vue'
import {
  listOrdersAdmin,
  forceSuccess,
  forceFail,
  retryOrder,
  type AdminOrderRow,
  type OrderStatus,
} from '@/api/recharge'
import { extractError } from '@/api/client'

const items = ref<AdminOrderRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const filterStatus = ref<OrderStatus | ''>('')
const filterUserId = ref('')
const loading = ref(false)

const STATUS_OPTIONS: { value: OrderStatus; label: string; tag: string }[] = [
  { value: 'pending', label: '待支付', tag: 'info' },
  { value: 'submitted', label: '已提交', tag: 'warning' },
  { value: 'verifying', label: '核验中', tag: 'warning' },
  { value: 'succeeded', label: '成功', tag: 'success' },
  { value: 'failed', label: '失败', tag: 'danger' },
  { value: 'expired', label: '过期', tag: '' },
]

function statusLabel(s: OrderStatus): string {
  return STATUS_OPTIONS.find(o => o.value === s)?.label ?? s
}
function statusTag(s: OrderStatus): string {
  return STATUS_OPTIONS.find(o => o.value === s)?.tag ?? ''
}

const FORCE_SUCCESS_ALLOWED: OrderStatus[] = [
  'pending', 'submitted', 'verifying', 'failed', 'expired',
]
const FORCE_FAIL_ALLOWED: OrderStatus[] = ['pending', 'submitted', 'verifying']

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await listOrdersAdmin({
      status: filterStatus.value || undefined,
      user_id: filterUserId.value ? Number(filterUserId.value) : undefined,
      page: page.value,
      size: size.value,
    })
    items.value = data.items
    total.value = data.total
  } catch (err) {
    ElMessage.error(extractError(err).message)
  } finally {
    loading.value = false
  }
}

function search(): void {
  page.value = 1
  load()
}

function reset(): void {
  filterStatus.value = ''
  filterUserId.value = ''
  search()
}

async function promptNote(title: string, dangerous = false): Promise<string | null> {
  try {
    const res = await ElMessageBox.prompt('请填写操作备注（必填，写入审计日志）', title, {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputPlaceholder: '例：用户已提供链上转账截图，金额匹配',
      inputValidator: (v: string) => (v && v.trim().length > 0) || '备注不能为空',
      type: dangerous ? 'warning' : 'info',
    })
    return (res.value ?? '').trim()
  } catch {
    return null
  }
}

async function onForceSuccess(o: AdminOrderRow): Promise<void> {
  const note = await promptNote(`强制核销 #${o.id} 成功？`, true)
  if (!note) return
  try {
    await forceSuccess(o.id, note)
    ElMessage.success('已核销成功')
    load()
  } catch (err) {
    ElMessage.error(extractError(err).message)
  }
}

async function onForceFail(o: AdminOrderRow): Promise<void> {
  const note = await promptNote(`强制标记 #${o.id} 为失败？`, true)
  if (!note) return
  try {
    await forceFail(o.id, note)
    ElMessage.success('已标记失败')
    load()
  } catch (err) {
    ElMessage.error(extractError(err).message)
  }
}

async function onRetry(o: AdminOrderRow): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `把 #${o.id} 重置为 pending 并清掉旧 tx_hash？用户可重新提交。`,
      '重置订单',
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
    )
  } catch { return }
  try {
    await retryOrder(o.id)
    ElMessage.success('已重置为 pending')
    load()
  } catch (err) {
    ElMessage.error(extractError(err).message)
  }
}

function formatTime(s: string): string {
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN', { hour12: false })
}

onMounted(load)
</script>

<template>
  <AdminLayout>
    <div class="header">
      <h2>充值订单</h2>
      <el-select
        v-model="filterStatus"
        placeholder="全部状态"
        clearable
        style="width: 140px"
        @change="search"
      >
        <el-option
          v-for="o in STATUS_OPTIONS"
          :key="o.value"
          :value="o.value"
          :label="o.label"
        />
      </el-select>
      <el-input
        v-model="filterUserId"
        placeholder="按用户 ID 过滤"
        clearable
        style="width: 160px"
        @keyup.enter="search"
        @clear="search"
      />
      <el-button type="primary" @click="search">查询</el-button>
      <el-button @click="reset">重置</el-button>
    </div>

    <el-table :data="items" v-loading="loading" stripe>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column label="用户" width="160">
        <template #default="{ row }">
          {{ row.username || '—' }}
          <span class="uid">#{{ row.user_id }}</span>
        </template>
      </el-table-column>
      <el-table-column label="金额" width="140">
        <template #default="{ row }">
          <strong>{{ row.amount_usdt }}</strong> USDT
          <div v-if="row.tx_amount_usdt && row.tx_amount_usdt !== row.amount_usdt" class="sub">
            实付 {{ row.tx_amount_usdt }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status) as any">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="入账秒数" width="110">
        <template #default="{ row }">{{ row.granted_seconds ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="tx_hash" min-width="240">
        <template #default="{ row }">
          <code v-if="row.tx_hash" class="hash">{{ row.tx_hash }}</code>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="失败原因" min-width="180">
        <template #default="{ row }">
          <span v-if="row.fail_reason" class="fail">{{ row.fail_reason }}</span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="FORCE_SUCCESS_ALLOWED.includes(row.status)"
            size="small"
            type="success"
            @click="onForceSuccess(row)"
          >强制成功</el-button>
          <el-button
            v-if="FORCE_FAIL_ALLOWED.includes(row.status)"
            size="small"
            type="danger"
            @click="onForceFail(row)"
          >强制失败</el-button>
          <el-button
            v-if="row.status === 'failed'"
            size="small"
            @click="onRetry(row)"
          >重置</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="total > size"
      v-model:current-page="page"
      v-model:page-size="size"
      :page-sizes="[10, 20, 50, 100]"
      :total="total"
      layout="prev, pager, next, sizes, total"
      style="margin-top: 18px; justify-content: flex-end"
      @current-change="load"
      @size-change="load"
    />
  </AdminLayout>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
}
.header h2 { margin: 0; flex: 1; font-size: 18px; }

.uid { color: #909399; font-size: 12px; margin-left: 4px; }
.hash {
  background: #f4f4f5;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 12px;
  word-break: break-all;
}
.fail { color: #f56c6c; font-size: 13px; }
.muted { color: #c0c4cc; }
.sub { color: #909399; font-size: 12px; margin-top: 2px; }
</style>
