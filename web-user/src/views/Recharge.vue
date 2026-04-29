<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { createOrder } from '@/api/recharge'
import { extractError } from '@/api/client'

const router = useRouter()

const amount = ref('50')
const fromAddress = ref('')
const submitting = ref(false)
const error = ref('')

async function submit(): Promise<void> {
  error.value = ''
  const a = amount.value.trim()
  const f = fromAddress.value.trim()
  if (!a) { error.value = '请输入充值金额'; return }
  if (!f) { error.value = '请填写转出钱包地址'; return }
  if (!(f.length === 34 && f.startsWith('T'))) {
    error.value = 'TRC20 钱包地址应该以 T 开头，共 34 位'
    return
  }
  submitting.value = true
  try {
    const order = await createOrder({ amount_usdt: a, from_address: f })
    router.push(`/recharge/${order.id}`)
  } catch (e) {
    error.value = extractError(e).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AppLayout>
    <h1 class="page-title">USDT-TRC20 充值</h1>

    <section class="card">
      <h2>步骤 1：填写充值信息</h2>
      <p class="hint">
        创建订单后，会显示平台收款地址。<strong>请用你下面填写的"转出钱包"</strong>转账，
        平台会校验链上 from 地址必须与此一致，否则不入账。
      </p>

      <form @submit.prevent="submit">
        <div class="field">
          <label>充值金额（USDT）</label>
          <input
            v-model="amount"
            type="text"
            inputmode="decimal"
            placeholder="例如 50"
          />
        </div>
        <div class="field">
          <label>转出钱包地址（TRC20）</label>
          <input
            v-model="fromAddress"
            type="text"
            placeholder="T 开头，共 34 位"
            spellcheck="false"
          />
          <p class="sub">这必须是你接下来转账要用的钱包地址。</p>
        </div>
        <button class="primary" type="submit" :disabled="submitting">
          {{ submitting ? '创建中…' : '下一步：查看收款地址' }}
        </button>
      </form>
      <p v-if="error" class="msg-err">{{ error }}</p>
    </section>

    <section class="card tips">
      <h2>充值说明</h2>
      <ul>
        <li>仅支持 USDT-TRC20（Tron 网络）；其他链转入将无法识别。</li>
        <li>每 1 USDT 兑换 60 秒面试时长（实际汇率以创建订单时为准）。</li>
        <li>订单 24 小时有效。链上转账后到提交 hash 前请等待约 1 分钟（19 个块确认）。</li>
        <li>如果转账后核销失败，请在订单详情页查看原因，或联系管理员人工处理。</li>
      </ul>
    </section>
  </AppLayout>
</template>

<style scoped>
.page-title { color: var(--accent); margin: 0 0 18px; font-size: 22px; }
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 22px 24px;
  margin-bottom: 16px;
}
.card h2 {
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 2px;
  text-transform: uppercase;
  margin: 0 0 14px;
}
.hint {
  color: var(--text-muted);
  font-size: 13px;
  margin: 0 0 16px;
  line-height: 1.6;
}
.hint strong { color: var(--text); }

.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
.field label { color: var(--text-dim); font-size: 12px; letter-spacing: 1px; text-transform: uppercase; }
.field input {
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--text);
  font-size: 14px;
  font-family: inherit;
}
.field input:focus { outline: none; border-color: rgba(126,184,240,0.55); }
.sub { color: var(--text-muted); font-size: 12px; margin: 4px 0 0; }

button.primary {
  background: linear-gradient(135deg, rgba(70,120,200,0.95), rgba(100,150,230,0.95));
  border: none; border-radius: 10px;
  color: white;
  padding: 11px 28px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  letter-spacing: 1px;
}
button.primary:disabled { opacity: 0.6; cursor: wait; }
button.primary:hover:not(:disabled) { filter: brightness(1.1); }

.msg-err { color: #f99; margin-top: 12px; font-size: 13px; }

.tips ul {
  margin: 0; padding-left: 20px;
  color: var(--text-muted); font-size: 13px; line-height: 1.8;
}
.tips li::marker { color: var(--text-dim); }
</style>
