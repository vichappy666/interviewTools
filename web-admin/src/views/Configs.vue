<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import AdminLayout from '@/components/AdminLayout.vue'
import { extractError } from '@/api/client'
import { listConfigs, updateConfig } from '@/api/configs'

interface ConfigEditEntry {
  key: string
  originalValue: unknown
  jsonText: string
  jsonError: string | null
  saving: boolean
  showSecrets: boolean
  isSecret: boolean
}

const SECRET_FIELDS = new Set(['api_key', 'access_key', 'app_key', 'secret_key', 'token'])

const entries = ref<ConfigEditEntry[]>([])
const loading = ref(false)

function detectSecretKey(key: string): boolean {
  return key.startsWith('llm.') || key.startsWith('asr.')
}

function maskSecrets(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(maskSecrets)
  }
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (SECRET_FIELDS.has(k)) {
        out[k] = typeof v === 'string' && v.length > 0 ? '***' : ''
      } else {
        out[k] = maskSecrets(v)
      }
    }
    return out
  }
  return value
}

function valueToJson(value: unknown, masked: boolean): string {
  const v = masked ? maskSecrets(value) : value
  return JSON.stringify(v, null, 2)
}

function mergeSecrets(original: unknown, edited: unknown): unknown {
  if (Array.isArray(original) && Array.isArray(edited)) {
    return edited.map((item, i) => mergeSecrets(original[i], item))
  }
  if (
    original && typeof original === 'object' &&
    edited && typeof edited === 'object'
  ) {
    const orig = original as Record<string, unknown>
    const edt = edited as Record<string, unknown>
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(edt)) {
      if (SECRET_FIELDS.has(k) && v === '***') {
        out[k] = orig[k]
      } else {
        out[k] = mergeSecrets(orig[k], v)
      }
    }
    return out
  }
  return edited
}

async function loadAll(): Promise<void> {
  loading.value = true
  try {
    const list = await listConfigs()
    entries.value = list.map((item) => {
      const isSecret = detectSecretKey(item.key)
      return {
        key: item.key,
        originalValue: item.value,
        jsonText: valueToJson(item.value, isSecret),
        jsonError: null,
        saving: false,
        showSecrets: false,
        isSecret,
      }
    })
  } catch (err) {
    ElMessage.error('加载配置失败：' + extractError(err).message)
  } finally {
    loading.value = false
  }
}

function toggleSecret(entry: ConfigEditEntry): void {
  entry.showSecrets = !entry.showSecrets
  entry.jsonText = valueToJson(entry.originalValue, !entry.showSecrets && entry.isSecret)
  entry.jsonError = null
}

async function save(entry: ConfigEditEntry): Promise<void> {
  let parsed: unknown
  try {
    const edited = JSON.parse(entry.jsonText)
    parsed = entry.isSecret && !entry.showSecrets
      ? mergeSecrets(entry.originalValue, edited)
      : edited
    entry.jsonError = null
  } catch (err) {
    entry.jsonError = (err as Error)?.message || 'JSON 解析失败'
    return
  }

  try {
    await ElMessageBox.confirm(
      `确认保存配置 ${entry.key}？后端会立即热加载，无需重启。`,
      '确认保存',
      { type: 'warning', confirmButtonText: '保存', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  entry.saving = true
  try {
    await updateConfig(entry.key, parsed)
    ElMessage.success(`已保存 ${entry.key}`)
    entry.originalValue = parsed
    entry.jsonText = valueToJson(parsed, !entry.showSecrets && entry.isSecret)
  } catch (err) {
    ElMessage.error('保存失败：' + extractError(err).message)
  } finally {
    entry.saving = false
  }
}

onMounted(loadAll)
</script>

<template>
  <AdminLayout>
    <div class="configs-page" v-loading="loading">
      <h2>系统配置</h2>
      <p class="hint">
        修改后保存即热加载，无需重启 backend。含 api_key / access_key 字段默认显示为 <code>***</code>，
        点击「显示明文」可查看原始值并编辑。
      </p>

      <el-empty v-if="!loading && entries.length === 0" description="暂无配置" />

      <el-card v-for="entry in entries" :key="entry.key" class="config-card" shadow="never">
        <template #header>
          <div class="card-head">
            <span class="key">{{ entry.key }}</span>
            <el-tag v-if="entry.isSecret" size="small" type="warning">含敏感字段</el-tag>
            <span class="spacer" />
            <el-button
              v-if="entry.isSecret"
              size="small"
              link
              type="primary"
              @click="toggleSecret(entry)"
            >
              {{ entry.showSecrets ? '隐藏明文' : '显示明文' }}
            </el-button>
          </div>
        </template>

        <el-input
          v-model="entry.jsonText"
          type="textarea"
          :autosize="{ minRows: 3, maxRows: 18 }"
          @input="entry.jsonError = null"
        />
        <div v-if="entry.jsonError" class="json-error">JSON 错误：{{ entry.jsonError }}</div>

        <div class="card-actions">
          <el-button
            type="primary"
            :loading="entry.saving"
            @click="save(entry)"
          >
            保存
          </el-button>
          <span v-if="entry.isSecret && !entry.showSecrets" class="secret-tip">
            提示：要修改 api_key / access_key 等敏感字段，请先点「显示明文」
          </span>
        </div>
      </el-card>
    </div>
  </AdminLayout>
</template>

<style scoped>
.configs-page h2 {
  margin: 0 0 6px;
  font-size: 18px;
}
.hint {
  color: #888;
  margin-bottom: 18px;
  font-size: 13px;
  line-height: 1.6;
}
.hint code {
  padding: 1px 6px;
  background: #f4f4f5;
  border-radius: 4px;
  font-size: 12px;
}
.config-card {
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.key {
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  font-weight: 600;
  font-size: 14px;
}
.spacer { flex: 1; }
.json-error {
  color: #c45656;
  font-size: 12px;
  margin-top: 6px;
}
.card-actions {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.secret-tip {
  color: #c08d1f;
  font-size: 12px;
}
:deep(.el-textarea__inner) {
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  font-size: 13px;
}
</style>
