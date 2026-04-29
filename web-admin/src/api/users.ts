import { api } from './client'

export interface AdminUser {
  id: number
  username: string
  phone: string | null
  balance_seconds: number
  status: number
  created_at: string
}

export interface UserListPage {
  items: AdminUser[]
  total: number
  page: number
  size: number
}

export interface AdminLedgerItem {
  id: number
  delta_seconds: number
  reason: string
  balance_after: number
  note: string | null
  created_at: string
}

export interface UserDetail {
  user: AdminUser
  recent_ledger: AdminLedgerItem[]
  recent_sessions: unknown[]
}

export async function listUsers(params: { q?: string; page?: number; size?: number }): Promise<UserListPage> {
  const res = await api.get<UserListPage>('/api/admin/users', { params })
  return res.data
}

export async function getUserDetail(id: number): Promise<UserDetail> {
  const res = await api.get<UserDetail>(`/api/admin/users/${id}`)
  return res.data
}

export async function patchUser(id: number, payload: { status?: number }): Promise<AdminUser> {
  const res = await api.patch<AdminUser>(`/api/admin/users/${id}`, payload)
  return res.data
}

export async function grantBalance(
  id: number,
  payload: { delta_seconds: number; note: string },
): Promise<AdminUser> {
  const res = await api.post<AdminUser>(`/api/admin/users/${id}/grant`, payload)
  return res.data
}

export async function resetUserPassword(
  id: number,
  newPassword: string,
): Promise<AdminUser> {
  const res = await api.post<AdminUser>(`/api/admin/users/${id}/reset-password`, {
    new_password: newPassword,
  })
  return res.data
}
