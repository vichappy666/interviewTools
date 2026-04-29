import { api } from './client'

export interface User {
  id: number
  username: string
  phone: string | null
  balance_seconds: number
}

export interface AuthOut {
  token: string
  user: User
}

export interface RegisterPayload {
  username: string
  password: string
  phone?: string
}

export interface LoginPayload {
  username: string
  password: string
}

export interface ResetPayload {
  username: string
  phone: string
  new_password: string
}

export async function register(payload: RegisterPayload): Promise<AuthOut> {
  const res = await api.post<AuthOut>('/api/auth/register', payload)
  return res.data
}

export async function login(payload: LoginPayload): Promise<AuthOut> {
  const res = await api.post<AuthOut>('/api/auth/login', payload)
  return res.data
}

export async function resetPassword(payload: ResetPayload): Promise<User> {
  const res = await api.post<User>('/api/auth/reset-password', payload)
  return res.data
}
