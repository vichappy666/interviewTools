<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import AdminLayout from '@/components/AdminLayout.vue'
import { listUsers, type AdminUser } from '@/api/users'
import { extractError } from '@/api/client'

const router = useRouter()
const items = ref<AdminUser[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const q = ref('')
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await listUsers({ q: q.value || undefined, page: page.value, size: size.value })
    items.value = data.items
    total.value = data.total
  } catch (err) {
    ElMessage.error(extractError(err).message)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function search(): void {
  page.value = 1
  load()
}

function open(id: number): void {
  router.push({ name: 'user-detail', params: { id: String(id) } })
}

function formatBalance(s: number): string {
  if (s <= 0) return '0s'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return `${h}h${m}m${sec}s`
}

function formatTime(s: string): string {
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <AdminLayout>
    <div class="header">
      <h2>用户管理</h2>
      <el-input
        v-model="q"
        placeholder="搜索用户名或手机号"
        clearable
        style="width: 280px"
        @keyup.enter="search"
        @clear="search"
      />
      <el-button type="primary" @click="search">搜索</el-button>
    </div>

    <el-table :data="items" v-loading="loading" stripe>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="username" label="用户名" />
      <el-table-column prop="phone" label="手机号">
        <template #default="{ row }">{{ row.phone || '—' }}</template>
      </el-table-column>
      <el-table-column label="余额" width="160">
        <template #default="{ row }">{{ formatBalance(row.balance_seconds) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 1 ? 'success' : 'danger'">
            {{ row.status === 1 ? '正常' : '封禁' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="注册时间" width="180">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="open(row.id)">详情</el-button>
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
  gap: 12px;
  margin-bottom: 18px;
}
.header h2 {
  margin: 0;
  flex: 1;
  font-size: 18px;
}
</style>
