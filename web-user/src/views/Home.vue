<script setup lang="ts">
import AppLayout from '@/components/AppLayout.vue'
import { useUserStore } from '@/stores/user'
import { useRouter } from 'vue-router'

const store = useUserStore()
const router = useRouter()

function startInterview(): void {
  alert('面试功能将在 M2 上线，敬请期待。')
}

function recharge(): void {
  alert('充值功能将在 M3 上线，敬请期待。')
}

function formatBalance(seconds: number): string {
  if (seconds <= 0) return '0s'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return `${h}h ${m}m ${s}s`
}
</script>

<template>
  <AppLayout>
    <section class="hero">
      <h1>欢迎回来{{ store.user ? '，' + store.user.username : '' }}</h1>
      <p class="hint">
        当前余额可用 <strong>{{ store.user ? formatBalance(store.user.balance_seconds) : '...' }}</strong>
      </p>
      <button class="big-cta" @click="startInterview">🎤 开始面试</button>
      <p class="footer-hint">点击按钮开始面试会话（M2 上线）</p>
    </section>

    <section class="actions">
      <button class="action" @click="recharge">
        🪙 充值
        <span>买面试时间（M3 上线）</span>
      </button>
      <button class="action" @click="router.push('/ledger')">
        📜 余额流水
        <span>查看充值 / 扣费记录</span>
      </button>
      <button class="action" @click="router.push('/profile')">
        👤 个人资料
        <span>改手机号 / 改密码</span>
      </button>
    </section>

    <section class="recent">
      <h2>最近面试</h2>
      <p class="empty">暂无（M2 完成后将在此展示历史）</p>
    </section>
  </AppLayout>
</template>

<style scoped>
.hero {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 50px 30px;
  text-align: center;
  margin-bottom: 24px;
}
.hero h1 { color: var(--accent); margin: 0 0 12px; font-size: 24px; }
.hint { color: var(--text-dim); margin: 0 0 30px; font-size: 14px; }
.hint strong { color: var(--text); }

.big-cta {
  background: linear-gradient(135deg, rgba(70,120,200,0.95), rgba(100,150,230,0.95));
  border: none;
  border-radius: 14px;
  color: white;
  padding: 22px 56px;
  font-size: 18px;
  font-weight: 700;
  cursor: pointer;
  letter-spacing: 1px;
  box-shadow: 0 8px 28px rgba(70, 120, 200, 0.35);
}
.big-cta:hover { filter: brightness(1.1); transform: translateY(-1px); }
.footer-hint { color: var(--text-muted); margin-top: 18px; font-size: 12px; }

.actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
  margin-bottom: 24px;
}

.action {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 20px;
  color: var(--text);
  cursor: pointer;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 14px;
  font-weight: 700;
}
.action span {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: normal;
}
.action:hover { border-color: rgba(126,184,240,0.55); }

.recent {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 22px 24px;
}
.recent h2 { color: var(--text-dim); font-size: 13px; font-weight: 700; letter-spacing: 2px; margin: 0 0 12px; text-transform: uppercase; }
.empty { color: var(--text-muted); font-size: 13px; }
</style>
