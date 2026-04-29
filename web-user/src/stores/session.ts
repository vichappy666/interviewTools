import { defineStore } from 'pinia'

export type AnswerSegment = 'key_points' | 'script' | 'full'

export interface QA {
  qa_id: number
  text: string
  asked_at: number
  /** 前端本地：是否已点击发问（乐观更新；后端目前不广播 question_asked，沿用 legacy 行为） */
  asked: boolean
}

export interface Answer {
  qa_id: number
  question?: string
  key_points: string
  script: string
  full: string
  loading: Record<AnswerSegment, boolean>
  errors: Partial<Record<AnswerSegment, string>>
}

export type ConnectionState = 'idle' | 'connecting' | 'connected' | 'disconnected'

interface SnapshotMsg {
  transcript_finals?: { text: string; ts: number }[] | string[]
  transcript_partial?: string
  questions?: { qa_id: number; text: string; asked_at: number; asked?: boolean }[]
  current_answer?: {
    qa_id: number
    question?: string
    sections?: Partial<Record<AnswerSegment, { text?: string; state?: 'streaming' | 'done' }>>
  } | null
}

interface State {
  sessionId: number | null
  transcriptFinals: { text: string; ts: number }[]
  transcriptPartial: string
  questions: QA[]
  currentAnswer: Answer | null
  balanceSeconds: number
  balanceLow: boolean
  sessionEnded: boolean
  endReason: string | null
  connectionState: ConnectionState
  error: string | null
}

function emptyAnswer(qa_id: number, question?: string): Answer {
  return {
    qa_id,
    question,
    key_points: '',
    script: '',
    full: '',
    loading: { key_points: false, script: false, full: false },
    errors: {},
  }
}

export const useSessionStore = defineStore('session', {
  state: (): State => ({
    sessionId: null,
    transcriptFinals: [],
    transcriptPartial: '',
    questions: [],
    currentAnswer: null,
    balanceSeconds: 0,
    balanceLow: false,
    sessionEnded: false,
    endReason: null,
    connectionState: 'idle',
    error: null,
  }),
  actions: {
    reset(): void {
      this.sessionId = null
      this.transcriptFinals = []
      this.transcriptPartial = ''
      this.questions = []
      this.currentAnswer = null
      this.balanceSeconds = 0
      this.balanceLow = false
      this.sessionEnded = false
      this.endReason = null
      this.connectionState = 'idle'
      this.error = null
    },
    handleSnapshot(msg: SnapshotMsg): void {
      const finals = msg.transcript_finals ?? []
      this.transcriptFinals = finals.map((f) => {
        if (typeof f === 'string') return { text: f, ts: 0 }
        return { text: f.text, ts: f.ts ?? 0 }
      })
      this.transcriptPartial = msg.transcript_partial ?? ''
      this.questions = (msg.questions ?? []).map((q) => ({
        qa_id: q.qa_id,
        text: q.text,
        asked_at: q.asked_at,
        asked: !!q.asked,
      }))
      const ca = msg.current_answer
      if (!ca) {
        this.currentAnswer = null
      } else {
        const ans = emptyAnswer(ca.qa_id, ca.question)
        const segs = ca.sections ?? {}
        for (const seg of ['key_points', 'script', 'full'] as AnswerSegment[]) {
          const s = segs[seg]
          if (!s) continue
          ans[seg] = s.text ?? ''
          if (s.state === 'streaming') ans.loading[seg] = true
        }
        this.currentAnswer = ans
      }
    },
    handleTranscriptPartial(text: string): void {
      this.transcriptPartial = text
    },
    handleTranscriptFinal(text: string, ts: number): void {
      this.transcriptFinals.push({ text, ts })
      this.transcriptPartial = ''
    },
    handleQuestionAdded(qa_id: number, text: string, asked_at: number): void {
      // 去重：同一 qa_id 不要重复（snapshot 之后又收到 question_added 的边界）
      if (this.questions.some((q) => q.qa_id === qa_id)) return
      this.questions.push({ qa_id, text, asked_at, asked: false })
    },
    markQuestionAsked(qa_id: number): void {
      const q = this.questions.find((x) => x.qa_id === qa_id)
      if (q) q.asked = true
    },
    handleAnswerStart(qa_id: number, segment: AnswerSegment, question?: string): void {
      if (!this.currentAnswer || this.currentAnswer.qa_id !== qa_id) {
        this.currentAnswer = emptyAnswer(qa_id, question)
      }
      this.currentAnswer.loading[segment] = true
      this.currentAnswer.errors[segment] = undefined
    },
    handleAnswerChunk(qa_id: number, segment: AnswerSegment, text: string): void {
      if (!this.currentAnswer || this.currentAnswer.qa_id !== qa_id) {
        this.currentAnswer = emptyAnswer(qa_id)
      }
      this.currentAnswer[segment] += text
    },
    handleAnswerEnd(qa_id: number, segment: AnswerSegment): void {
      if (this.currentAnswer && this.currentAnswer.qa_id === qa_id) {
        this.currentAnswer.loading[segment] = false
      }
    },
    handleAnswerError(qa_id: number, segment: AnswerSegment, error: string): void {
      if (this.currentAnswer && this.currentAnswer.qa_id === qa_id) {
        this.currentAnswer.loading[segment] = false
        this.currentAnswer.errors[segment] = error
      }
    },
  },
})
