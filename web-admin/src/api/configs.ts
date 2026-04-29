import { api } from './client'

export type ConfigValue = unknown

export interface ConfigItem {
  key: string
  value: ConfigValue
  updated_at?: string
}

export async function listConfigs(): Promise<ConfigItem[]> {
  const res = await api.get('/api/admin/configs')
  if (Array.isArray(res.data)) return res.data as ConfigItem[]
  if (res.data && typeof res.data === 'object') {
    return Object.entries(res.data as Record<string, unknown>).map(([key, value]) => ({
      key,
      value: value as ConfigValue,
    }))
  }
  return []
}

export async function updateConfig(key: string, value: ConfigValue): Promise<void> {
  await api.put(`/api/admin/configs/${encodeURIComponent(key)}`, { value })
}
