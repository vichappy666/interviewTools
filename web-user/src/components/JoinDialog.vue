<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  visible: boolean
  startedAt: string  // ISO 时间串
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'join'): void
  (e: 'new'): void
  (e: 'cancel'): void
}>()

const elapsed = computed(() => {
  const start = new Date(props.startedAt).getTime()
  const now = Date.now()
  const sec = Math.max(0, Math.floor((now - start) / 1000))
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
})
</script>

<template>
  <div v-if="visible" class="dialog-mask" @click.self="emit('cancel')">
    <div class="dialog">
      <h3>正在进行的面试</h3>
      <p>您当前已有一场面试在进行（已计 <strong>{{ elapsed }}</strong>）。</p>
      <p>多端协同：选"加入"会让两台设备同步同一份面试。</p>
      <div class="actions">
        <button class="btn btn-primary" @click="emit('join')">加入</button>
        <button class="btn btn-secondary" @click="emit('new')">新开一场</button>
        <button class="btn btn-ghost" @click="emit('cancel')">取消</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dialog-mask {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.55);
  backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.dialog {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 28px 30px;
  max-width: 440px;
  width: 90%;
  box-shadow: 0 20px 60px rgba(0,0,0,0.6);
}
.dialog h3 { margin: 0 0 14px; color: var(--accent); font-size: 18px; }
.dialog p { color: var(--text); margin: 6px 0; font-size: 14px; line-height: 1.5; }
.dialog p strong { color: var(--accent); }
.actions {
  display: flex; gap: 10px; margin-top: 20px; justify-content: flex-end; flex-wrap: wrap;
}
.btn {
  border: none; border-radius: 8px; padding: 10px 18px;
  font-size: 14px; cursor: pointer; font-weight: 600;
}
.btn-primary { background: var(--accent); color: #0a0a14; }
.btn-secondary { background: rgba(126,184,240,0.18); color: var(--accent); border: 1px solid var(--border); }
.btn-ghost { background: transparent; color: var(--text-muted); }
.btn:hover { filter: brightness(1.1); }
</style>
