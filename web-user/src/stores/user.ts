import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getToken, setToken } from '@/api/client'
import { getMe } from '@/api/users'
import type { User } from '@/api/auth'

export const useUserStore = defineStore('user', () => {
  const token = ref<string | null>(getToken())
  const user = ref<User | null>(null)

  function setAuth(newToken: string, newUser: User): void {
    token.value = newToken
    user.value = newUser
    setToken(newToken)
  }

  function logout(): void {
    token.value = null
    user.value = null
    setToken(null)
  }

  async function fetchMe(): Promise<User> {
    const u = await getMe()
    user.value = u
    return u
  }

  return { token, user, setAuth, logout, fetchMe }
})
