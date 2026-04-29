<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { grantBalance } from '@/api/users'
import { extractError } from '@/api/client'

const props = defineProps<{
  modelValue: boolean
  userId: number
  username: string
}>()
const emit = defineEmits<{
  'update:modelValue': [v: boolean]
  granted: []
}>()

const delta = ref<number>(3600)
const note = ref<string>('')
const loading = ref(false)

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      delta.value = 3600
      note.value = ''
    }
  },
)

function preset(seconds: number): void {
  delta.value = seconds
}

async function submit(): Promise<void> {
  if (delta.value === 0) {
    ElMessage.warning('变更秒数不能为 0')
    return
  }
  if (!note.value.trim()) {
    ElMessage.warning('备注必填')
    return
  }
  loading.value = true
  try {
    await grantBalance(props.userId, { delta_seconds: delta.value, note: note.value.trim() })
    ElMessage.success(delta.value > 0 ? '已加余额' : '已扣余额')
    emit('granted')
    emit('update:modelValue', false)
  } catch (err) {
    ElMessage.error(extractError(err).message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    title="手动加减时长"
    width="460px"
  >
    <p class="target">用户：<strong>{{ username }}</strong> (ID {{ userId }})</p>
    <el-form label-position="top">
      <el-form-item label="变更秒数（正数加 / 负数减）">
        <el-input-number v-model="delta" :step="60" style="width: 100%" />
        <div class="presets">
          <el-button size="small" @click="preset(3600)">+1 小时</el-button>
          <el-button size="small" @click="preset(1800)">+30 分钟</el-button>
          <el-button size="small" @click="preset(-1800)">-30 分钟</el-button>
          <el-button size="small" @click="preset(-3600)">-1 小时</el-button>
        </div>
      </el-form-item>
      <el-form-item label="备注（必填）">
        <el-input
          v-model="note"
          type="textarea"
          :rows="2"
          placeholder="例如：M1 验收 / 客服补偿 / 测试调试 ..."
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="loading" @click="submit">提交</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.target {
  color: #606266;
  font-size: 13px;
  margin-bottom: 14px;
}
.presets {
  margin-top: 8px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
</style>
