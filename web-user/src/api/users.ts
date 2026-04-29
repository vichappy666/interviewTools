import { api } from './client'
import type { User } from './auth'

export async function getMe(): Promise<User> {
  const res = await api.get<User>('/api/users/me')
  return res.data
}

export async function updateMe(payload: { phone: string | null }): Promise<User> {
  const res = await api.patch<User>('/api/users/me', payload)
  return res.data
}

export async function changePassword(payload: {
  old_password: string
  new_password: string
}): Promise<void> {
  await api.post('/api/users/me/change-password', payload)
}
