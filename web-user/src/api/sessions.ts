import { api } from './client'

export interface Session {
  id: number
  user_id: number
  started_at: string
  ended_at: string | null
  total_seconds: number
  end_reason: string | null
  status: string
}

export interface SessionStartResponse {
  session_id: number
  ws_url: string
}

export interface SessionQA {
  id: number
  session_id: number
  question: string
  answer_key_points: string | null
  answer_script: string | null
  answer_full: string | null
  asked_at: string
  finished_at: string | null
  source: string
}

/** 新开会话；后端返回 session_id + ws_url。 */
export async function startSession(): Promise<SessionStartResponse> {
  const res = await api.post<SessionStartResponse>('/api/sessions/start')
  return res.data
}

/** 主动结束会话（也可以走 ws stop，REST 兜底用）。 */
export async function stopSession(sessionId: number): Promise<Session> {
  const res = await api.post<Session>(`/api/sessions/${sessionId}/stop`)
  return res.data
}

/** 当前用户活跃会话列表（用于"加入正在进行的会话"）。 */
export async function getActiveSessions(): Promise<Session[]> {
  const res = await api.get<Session[]>('/api/sessions/active')
  return res.data
}

/** 历史 QA（M4 完整支持，M2 后端返回空数组）。 */
export async function getSessionQA(sessionId: number): Promise<SessionQA[]> {
  const res = await api.get<SessionQA[]>(`/api/sessions/${sessionId}/qa`)
  return res.data
}

export interface SessionRow {
  id: number
  user_id: number
  started_at: string
  ended_at: string | null
  total_seconds: number
  end_reason: string | null
  status: 'active' | 'ended'
}

export interface ListResponse {
  items: SessionRow[]
  total: number
  page: number
  size: number
}

/** 分页查询当前用户的会话列表（首页"最近面试"用）。 */
export async function listSessions(page = 1, size = 20): Promise<ListResponse> {
  const res = await api.get<ListResponse>('/api/sessions/', { params: { page, size } })
  return res.data
}
