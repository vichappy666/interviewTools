<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { login as loginApi } from '@/api/auth'
import { extractError } from '@/api/client'
import { useAdminStore } from '@/stores/admin'

const router = useRouter()
const store = useAdminStore()

const username = ref('')
const password = ref('')
const loading = ref(false)

async function submit(): Promise<void> {
  if (!username.value || !password.value) {
    ElMessage.warning('请填写用户名和密码')
    return
  }
  loading.value = true
  try {
    const { token, admin } = await loginApi(username.value.trim(), password.value)
    store.setAuth(token, admin)
    router.push('/users')
  } catch (err) {
    ElMessage.error(extractError(err).message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="card">
      <h1>📊 面试助手·后台</h1>
      <p class="hint">默认账号：admin / admin（首次登录后请立刻在 SQL 里改密）</p>
      <el-form @submit.prevent="submit" label-position="top">
        <el-form-item label="用户名">
          <el-input v-model="username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-button type="primary" :loading="loading" @click="submit" class="submit">
          登录
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: linear-gradient(135deg, #001529 0%, #003a5c 100%);
}
.card {
  width: 420px;
  padding: 12px;
}
h1 {
  margin: 0 0 8px;
  font-size: 20px;
  color: #303133;
  text-align: center;
}
.hint {
  text-align: center;
  color: #909399;
  font-size: 12px;
  margin: 0 0 18px;
}
.submit {
  width: 100%;
  margin-top: 4px;
}
</style>
