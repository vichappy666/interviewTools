/** Admin: 充值订单管理 API（M3 T10）。 */
import { api } from './client'

export type OrderStatus =
  | 'pending'
  | 'submitted'
  | 'verifying'
  | 'succeeded'
  | 'failed'
  | 'expired'

export interface AdminOrderRow {
  id: number
  user_id: number
  username: string | null
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

export interface AdminOrderListPage {
  items: AdminOrderRow[]
  total: number
  page: number
  size: number
}

export async function listOrdersAdmin(params: {
  status?: OrderStatus
  user_id?: number
  page?: number
  size?: number
}): Promise<AdminOrderListPage> {
  const res = await api.get<AdminOrderListPage>('/api/admin/recharge/orders', {
    params,
  })
  return res.data
}

export async function forceSuccess(
  id: number,
  note: string
): Promise<AdminOrderRow> {
  const res = await api.post<AdminOrderRow>(
    `/api/admin/recharge/orders/${id}/force-success`,
    { note }
  )
  return res.data
}

export async function forceFail(
  id: number,
  note: string
): Promise<AdminOrderRow> {
  const res = await api.post<AdminOrderRow>(
    `/api/admin/recharge/orders/${id}/force-fail`,
    { note }
  )
  return res.data
}

export async function retryOrder(id: number): Promise<AdminOrderRow> {
  const res = await api.post<AdminOrderRow>(
    `/api/admin/recharge/orders/${id}/retry`
  )
  return res.data
}
