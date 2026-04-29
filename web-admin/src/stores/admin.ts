import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getToken, setToken } from '@/api/client'
import type { Admin } from '@/api/auth'

export const useAdminStore = defineStore('admin', () => {
  const token = ref<string | null>(getToken())
  const admin = ref<Admin | null>(null)

  function setAuth(newToken: string, newAdmin: Admin): void {
    token.value = newToken
    admin.value = newAdmin
    setToken(newToken)
  }

  function logout(): void {
    token.value = null
    admin.value = null
    setToken(null)
  }

  return { token, admin, setAuth, logout }
})
