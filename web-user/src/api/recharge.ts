/** TRC20 充值订单 API（M3 T6）。
 *
 * 后端：
 *   POST /api/recharge/orders                创建订单
 *   GET  /api/recharge/orders                历史分页
 *   GET  /api/recharge/orders/{id}           详情
 *   POST /api/recharge/orders/{id}/submit    提交 tx_hash 同步核销
 */
import { api } from './client'

export type OrderStatus =
  | 'pending'
  | 'submitted'
  | 'verifying'
  | 'succeeded'
  | 'failed'
  | 'expired'

export interface OrderRow {
  id: number
  user_id: number
  amount_usdt: string
  from_address: string
  to_address: string
  tx_hash: string | null
  tx_amount_usdt: string | null
  granted_seconds: number | null
  rate_per_usdt: number
  status: OrderStatus
  fail_reason: string | null
  expires_at: string
  created_at: string
  succeeded_at: string | null
}

export interface OrderListResponse {
  items: OrderRow[]
  total: number
  page: number
  size: number
}

export async function createOrder(body: {
  amount_usdt: string
  from_address: string
}): Promise<OrderRow> {
  const res = await api.post<OrderRow>('/api/recharge/orders', body)
  return res.data
}

export async function getOrder(id: number): Promise<OrderRow> {
  const res = await api.get<OrderRow>(`/api/recharge/orders/${id}`)
  return res.data
}

export async function submitHash(
  id: number,
  tx_hash: string
): Promise<OrderRow> {
  const res = await api.post<OrderRow>(
    `/api/recharge/orders/${id}/submit`,
    { tx_hash }
  )
  return res.data
}

export async function listOrders(
  page = 1,
  size = 20
): Promise<OrderListResponse> {
  const res = await api.get<OrderListResponse>('/api/recharge/orders', {
    params: { page, size },
  })
  return res.data
}
