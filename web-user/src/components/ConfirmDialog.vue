<script setup lang="ts">
interface Props {
  visible: boolean
  title?: string
  message: string
  confirmText?: string
  cancelText?: string
  /** 'danger' 红色 / 'primary' 主色调 */
  tone?: 'danger' | 'primary'
}

const props = withDefaults(defineProps<Props>(), {
  title: '请确认',
  confirmText: '确定',
  cancelText: '取消',
  tone: 'primary',
})

const emit = defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()
</script>

<template>
  <div v-if="props.visible" class="dialog-mask" @click.self="emit('cancel')">
    <div class="dialog" @keydown.esc="emit('cancel')">
      <h3>{{ props.title }}</h3>
      <p class="msg">{{ props.message }}</p>
      <div class="actions">
        <button class="btn btn-ghost" @click="emit('cancel')">
          {{ props.cancelText }}
        </button>
        <button
          class="btn"
          :class="props.tone === 'danger' ? 'btn-danger' : 'btn-primary'"
          @click="emit('confirm')"
        >
          {{ props.confirmText }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dialog-mask {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  z-index: 2000;
}
.dialog {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 26px 28px 22px;
  max-width: 420px;
  width: 90%;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
  animation: pop-in 0.18s ease-out;
}
@keyframes pop-in {
  from { transform: scale(0.94); opacity: 0; }
  to   { transform: scale(1);    opacity: 1; }
}
.dialog h3 {
  margin: 0 0 12px;
  color: var(--accent);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.dialog .msg {
  color: var(--text);
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
}
.actions {
  display: flex;
  gap: 10px;
  margin-top: 22px;
  justify-content: flex-end;
}
.btn {
  border: none;
  border-radius: 8px;
  padding: 9px 18px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: filter 0.15s, transform 0.05s;
}
.btn:hover { filter: brightness(1.12); }
.btn:active { transform: translateY(1px); }
.btn-primary { background: var(--accent); color: #0a0a14; }
.btn-danger {
  background: linear-gradient(135deg, #f87171, #ef4444);
  color: #fff;
  box-shadow: 0 6px 18px rgba(239, 68, 68, 0.3);
}
.btn-ghost {
  background: transparent;
  color: var(--text-muted);
  border: 1px solid var(--border);
}
.btn-ghost:hover {
  color: var(--text);
}
</style>
