import axios, { AxiosError, type AxiosResponse } from 'axios'
import { describeError } from './errorMap'

const TOKEN_KEY = 'auth_token'

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
      // Redirect via window.location to avoid circular import with router
      const here = window.location.pathname + window.location.search
      const onLogin = window.location.pathname.startsWith('/login')
      if (!onLogin) {
        window.location.href = `/login?redirect=${encodeURIComponent(here)}`
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
  // Best-effort extract our backend's {detail: {error: {code, message}}}
  const ax = err as AxiosError<{ detail?: { error?: ApiError } } | { error?: ApiError }>
  const data = ax?.response?.data as any
  let raw: ApiError
  if (data?.detail?.error) raw = data.detail.error as ApiError
  else if (data?.error) raw = data.error as ApiError
  else raw = { code: 'UNKNOWN', message: ax?.message || '请求失败' }
  // 后端没给 message 或 message 看起来不是给人看的（== code），用 errorMap 兜底
  if (!raw.message || raw.message === raw.code) {
    raw.message = describeError(raw.code, raw.message)
  }
  return raw
}
