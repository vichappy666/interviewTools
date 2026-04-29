import axios, { AxiosError, type AxiosResponse } from 'axios'

const TOKEN_KEY = 'admin_token'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 15000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      const onLogin = window.location.pathname.startsWith('/login')
      if (!onLogin) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export interface ApiError {
  code: string
  message: string
}

export function extractError(err: unknown): ApiError {
  const ax = err as AxiosError<{ detail?: { error?: ApiError } } | { error?: ApiError }>
  const data = ax?.response?.data as any
  if (data?.detail?.error) return data.detail.error as ApiError
  if (data?.error) return data.error as ApiError
  return { code: 'UNKNOWN', message: ax?.message || '请求失败' }
}
