<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAdminStore } from '@/stores/admin'

const router = useRouter()
const store = useAdminStore()

function logout(): void {
  store.logout()
  router.push('/login')
}
</script>

<template>
  <el-container class="admin-layout">
    <el-aside width="220px" class="aside">
      <div class="brand">📊 面试助手·后台</div>
      <el-menu
        :default-active="router.currentRoute.value.path"
        router
        class="menu"
        background-color="#001529"
        text-color="#bfcbd9"
        active-text-color="#7eb8f0"
      >
        <el-menu-item index="/users">
          <el-icon><i class="el-icon-user" /></el-icon>
          <template #title>用户管理</template>
        </el-menu-item>
        <el-menu-item index="/recharge">
          <template #title>充值订单</template>
        </el-menu-item>
        <el-menu-item index="/configs">
          <template #title>系统配置</template>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <span class="spacer" />
        <span class="admin-name">{{ store.admin?.username || 'admin' }}</span>
        <el-button size="small" plain @click="logout">退出</el-button>
      </el-header>
      <el-main>
        <slot />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.admin-layout {
  min-height: 100vh;
}
.aside {
  background: #001529;
  color: #fff;
}
.brand {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  letter-spacing: 1px;
  color: #7eb8f0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
}
.menu {
  border-right: none;
}
.topbar {
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  gap: 12px;
}
.spacer { flex: 1; }
.admin-name {
  color: #606266;
  font-size: 14px;
}
</style>
