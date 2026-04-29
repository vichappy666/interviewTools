import { api } from './client'

export interface LedgerItem {
  id: number
  delta_seconds: number
  reason: string
  ref_type: string | null
  ref_id: number | null
  balance_after: number
  note: string | null
  created_at: string
}

export interface LedgerPage {
  items: LedgerItem[]
  total: number
  page: number
  size: number
}

export async function listLedger(page = 1, size = 20): Promise<LedgerPage> {
  const res = await api.get<LedgerPage>('/api/balance/ledger', { params: { page, size } })
  return res.data
}
