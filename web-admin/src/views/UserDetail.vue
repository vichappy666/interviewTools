<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import AdminLayout from '@/components/AdminLayout.vue'
import GrantDialog from '@/components/GrantDialog.vue'
import { getUserDetail, patchUser, resetUserPassword, type AdminUser, type AdminLedgerItem } from '@/api/users'
import { extractError } from '@/api/client'

const props = defineProps<{ id: number }>()
const router = useRouter()

const user = ref<AdminUser | null>(null)
const ledger = ref<AdminLedgerItem[]>([])
const loading = ref(false)
const grantOpen = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await getUserDetail(props.id)
    user.value = data.user
    ledger.value = data.recent_ledger
  } catch (err) {
    ElMessage.error(extractError(err).message)
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function toggleStatus(): Promise<void> {
  if (!user.value) return
  const targetStatus = user.value.status === 1 ? 0 : 1
  const action = targetStatus === 0 ? '封禁' : '启用'
  try {
    await ElMessageBox.confirm(`确定要${action}此用户？`, '确认操作', { type: 'warning' })
  } catch {
    return
  }
  try {
    const updated = await patchUser(props.id, { status: targetStatus })
    user.value = updated
    ElMessage.success(`已${action}`)
  } catch (err) {
    ElMessage.error(extractError(err).message)
  }
}

function openGrant(): void {
  grantOpen.value = true
}

async function resetPassword(): Promise<void> {
  if (!user.value) return
  let newPwd: string
  try {
    const res = await ElMessageBox.prompt(
      `为用户 ${user.value.username} 设置新密码（至少 8 位，含字母+数字）`,
      '重置密码',
      {
        confirmButtonText: '保存',
        cancelButtonText: '取消',
        inputType: 'password',
        inputValidator: (v) => {
          if (!v || v.length < 8) return '密码至少 8 位'
          const hasAlpha = /[a-zA-Z]/.test(v)
          const hasDigit = /\d/.test(v)
          if (!hasAlpha || !hasDigit) return '密码必须同时包含字母和数字'
          return true
        },
      },
    )
    newPwd = res.value
  } catch {
    return
  }
  try {
    await resetUserPassword(props.id, newPwd)
    ElMessage.success('密码已重置')
  } catch (err) {
    ElMessage.error(extractError(err).message)
  }
}

function onGranted(): void {
  load()
}

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

function formatTime(s: string): string {
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN', { hour12: false })
}

function formatBalance(s: number): string {
  if (s <= 0) return '0s'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return `${h}h${m}m${sec}s`
}
</script>

<template>
  <AdminLayout>
    <el-button @click="router.push('/users')" plain size="small" style="margin-bottom: 16px">
      ← 返回用户列表
    </el-button>

    <el-card v-loading="loading" v-if="user" class="user-card">
      <template #header>
        <div class="card-header">
          <span class="title">用户 #{{ user.id }} · {{ user.username }}</span>
          <div class="actions">
            <el-button type="primary" @click="openGrant">手动加减时长</el-button>
            <el-button type="warning" plain @click="resetPassword">重置密码</el-button>
            <el-button :type="user.status === 1 ? 'danger' : 'success'" plain @click="toggleStatus">
              {{ user.status === 1 ? '封禁' : '启用' }}
            </el-button>
          </div>
        </div>
      </template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="用户名">{{ user.username }}</el-descriptions-item>
        <el-descriptions-item label="手机号">{{ user.phone || '—' }}</el-descriptions-item>
        <el-descriptions-item label="当前余额">{{ formatBalance(user.balance_seconds) }} ({{ user.balance_seconds }} 秒)</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="user.status === 1 ? 'success' : 'danger'">
            {{ user.status === 1 ? '正常' : '封禁' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="注册时间">{{ formatTime(user.created_at) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card style="margin-top: 18px" v-if="user">
      <template #header>
        <span class="title">最近余额流水（{{ ledger.length }}）</span>
      </template>
      <el-table :data="ledger" stripe>
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="140">
          <template #default="{ row }">{{ reasonLabel(row.reason) }}</template>
        </el-table-column>
        <el-table-column label="变动" width="120">
          <template #default="{ row }">
            <span :class="{ pos: row.delta_seconds > 0, neg: row.delta_seconds < 0 }">
              {{ row.delta_seconds > 0 ? '+' : '' }}{{ row.delta_seconds }}s
            </span>
          </template>
        </el-table-column>
        <el-table-column label="变更后余额" width="120">
          <template #default="{ row }">{{ row.balance_after }}s</template>
        </el-table-column>
        <el-table-column label="备注" prop="note">
          <template #default="{ row }">{{ row.note || '—' }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <GrantDialog
      v-if="user"
      v-model="grantOpen"
      :user-id="user.id"
      :username="user.username"
      @granted="onGranted"
    />
  </AdminLayout>
</template>

<style scoped>
.user-card .card-header {
  display: flex;
  align-items: center;
}
.title {
  flex: 1;
  font-size: 16px;
  font-weight: 600;
}
.actions {
  display: flex;
  gap: 8px;
}
.pos { color: #67c23a; font-family: "SF Mono", Menlo, monospace; }
.neg { color: #f56c6c; font-family: "SF Mono", Menlo, monospace; }
</style>
