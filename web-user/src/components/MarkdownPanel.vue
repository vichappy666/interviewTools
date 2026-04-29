<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  /** 原始 markdown 文本（流式累积值） */
  text: string
}>()

/**
 * 极简 markdown 渲染：抄 legacy/web/index.html 的实现。
 *  - 转义 HTML
 *  - 行首 "- " → <ul><li>...</li></ul>
 *  - **xxx** → <b>xxx</b>
 *  - 其他文字行包成 <div>...</div>，空行转 nbsp
 *
 * 直接 v-html，但因为先做了 escHtml，且回答文本来自后端 LLM（受控），可接受。
 * 不引入 marked 等大库，避免 bundle 膨胀。
 */
function escHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function renderInline(s: string): string {
  return escHtml(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
}

const html = computed<string>(() => {
  const lines = (props.text || '').split('\n')
  let out = ''
  let inUl = false
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '')
    if (line.startsWith('- ')) {
      if (!inUl) {
        out += '<ul>'
        inUl = true
      }
      out += '<li>' + renderInline(line.slice(2)) + '</li>'
    } else {
      if (inUl) {
        out += '</ul>'
        inUl = false
      }
      if (line.trim()) out += '<div>' + renderInline(line) + '</div>'
      else out += '<div>&nbsp;</div>'
    }
  }
  if (inUl) out += '</ul>'
  return out
})
</script>

<template>
  <!-- eslint-disable vue/no-v-html -->
  <div class="md-body" v-html="html"></div>
</template>

<style scoped>
.md-body {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(100, 140, 200, 0.18);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--text);
  line-height: 1.55;
  font-size: 13px;
  min-height: 36px;
  user-select: text;
  white-space: normal;
  word-break: break-word;
}
.md-body :deep(ul) {
  margin: 4px 0;
  padding-left: 20px;
}
.md-body :deep(li) {
  margin: 2px 0;
}
.md-body :deep(b) {
  color: #fff;
}
</style>
