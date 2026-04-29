<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { AudioSourceMode } from '@/composables/useAudioCapture'

interface Props {
  visible: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'confirm', mode: AudioSourceMode): void
  (e: 'cancel'): void
}>()

const selected = ref<AudioSourceMode>('mic')

// 浏览器是否支持 getDisplayMedia（拿系统音频用）
const displayMediaSupported = computed(
  () => typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getDisplayMedia,
)

// 每次重新打开 dialog，把选中重置回默认（mic）；如不支持 displayMedia 强制 mic
watch(
  () => props.visible,
  (v) => {
    if (v) {
      selected.value = 'mic'
    }
  },
)

function pick(mode: AudioSourceMode): void {
  if ((mode === 'tab' || mode === 'mixed') && !displayMediaSupported.value) return
  selected.value = mode
}

function onConfirm(): void {
  emit('confirm', selected.value)
}
</script>

<template>
  <div v-if="visible" class="dialog-mask" @click.self="emit('cancel')">
    <div class="dialog">
      <h3>选择音频源</h3>
      <p class="hint">选哪一路音频送去转写。开始后无法切换，结束面试重开即可。</p>

      <div class="options">
        <label
          class="option"
          :class="{ active: selected === 'mic' }"
          @click="pick('mic')"
        >
          <span class="radio">{{ selected === 'mic' ? '●' : '○' }}</span>
          <div class="text">
            <div class="title">仅麦克风<span class="tag">默认</span></div>
            <div class="desc">只转写你自己说的话。所有浏览器可用。</div>
          </div>
        </label>

        <label
          class="option"
          :class="{ active: selected === 'tab', disabled: !displayMediaSupported }"
          :title="!displayMediaSupported ? '当前浏览器不支持，请改用 Chrome' : ''"
          @click="pick('tab')"
        >
          <span class="radio">{{ selected === 'tab' ? '●' : '○' }}</span>
          <div class="text">
            <div class="title">仅系统音频（共享浏览器标签页）</div>
            <div class="desc">
              转写对方在 Zoom / 腾讯会议 / Google Meet 网页版里说的话。
              <span class="warn">⚠️ Chrome 限定；分享时需勾"同时分享标签页音频"。</span>
            </div>
          </div>
        </label>

        <label
          class="option"
          :class="{ active: selected === 'mixed', disabled: !displayMediaSupported }"
          :title="!displayMediaSupported ? '当前浏览器不支持，请改用 Chrome' : ''"
          @click="pick('mixed')"
        >
          <span class="radio">{{ selected === 'mixed' ? '●' : '○' }}</span>
          <div class="text">
            <div class="title">麦克风 + 系统音频（混合）</div>
            <div class="desc">
              两路一起转写，无法区分说话人；适合一人一机的场景。
              <span class="warn">⚠️ Chrome 限定。</span>
            </div>
          </div>
        </label>
      </div>

      <div class="actions">
        <button class="btn btn-ghost" @click="emit('cancel')">取消</button>
        <button class="btn btn-primary" @click="onConfirm">开始面试</button>
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
  z-index: 1000;
}
.dialog {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 26px 28px;
  max-width: 520px;
  width: 92%;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
}
.dialog h3 {
  margin: 0 0 8px;
  color: var(--accent);
  font-size: 18px;
}
.hint {
  color: var(--text-dim);
  font-size: 13px;
  margin: 0 0 16px;
}

.options {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.option {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  background: rgba(126, 184, 240, 0.04);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.option:hover:not(.disabled) {
  border-color: rgba(126, 184, 240, 0.45);
}
.option.active {
  border-color: var(--accent);
  background: rgba(126, 184, 240, 0.1);
}
.option.disabled {
  cursor: not-allowed;
  opacity: 0.45;
}
.radio {
  color: var(--accent);
  font-size: 16px;
  line-height: 1;
  margin-top: 1px;
  width: 14px;
}
.text {
  flex: 1;
  min-width: 0;
}
.title {
  color: var(--text);
  font-weight: 600;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.tag {
  background: rgba(126, 184, 240, 0.18);
  color: var(--accent);
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 700;
  letter-spacing: 1px;
}
.desc {
  color: var(--text-dim);
  font-size: 12px;
  margin-top: 4px;
  line-height: 1.5;
}
.warn {
  display: inline-block;
  color: #fbbf24;
}

.actions {
  display: flex; gap: 10px; margin-top: 22px; justify-content: flex-end;
}
.btn {
  border: none;
  border-radius: 8px;
  padding: 10px 20px;
  font-size: 14px;
  cursor: pointer;
  font-weight: 600;
}
.btn-primary {
  background: var(--accent);
  color: #0a0a14;
}
.btn-ghost {
  background: transparent;
  color: var(--text-muted);
}
.btn:hover {
  filter: brightness(1.1);
}
</style>
