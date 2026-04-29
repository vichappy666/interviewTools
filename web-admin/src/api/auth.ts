import { api } from './client'

export interface Admin {
  id: number
  username: string
}

export interface AdminAuthOut {
  token: string
  admin: Admin
}

export async function login(username: string, password: string): Promise<AdminAuthOut> {
  const res = await api.post<AdminAuthOut>('/api/admin/auth/login', { username, password })
  return res.data
}
