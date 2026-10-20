import request from './request'
import type { ColumnType } from '../utils/chartSelector'

/** 对话帧协议（与后端 services/chat.py 一致） */
export interface ChatFrame {
  type: 'delta' | 'answer' | 'view' | 'error' | 'done'
  content?: string
  thoughts?: string
  sql?: string | null
  chart_type?: string | null
  columns?: string[]
  column_types?: Record<string, ColumnType>
  rows?: Record<string, unknown>[]
  row_count?: number
  message?: string
  message_id?: number
  success?: boolean
  execution_time_ms?: number
  trace_id?: string
}

export interface TraceSpanItem {
  span_type: string
  name: string
  status: 'ok' | 'error'
  duration_ms: number
  attributes: Record<string, unknown> | null
  created_at: string
}

export interface ConversationItem {
  id: string
  chat_mode: 'chat_file' | 'chat_db'
  dataset_id: string | null
  dataset_name: string | null
  source_id: string | null
  source_name: string | null
  source_db_type: string | null
  title: string
  created_at: string
  updated_at: string
}

export interface ChatMessageItem {
  id: number
  round_index: number
  role: 'user' | 'assistant'
  content: string
  extra: {
    sql?: string | null
    chart_type?: string | null
  columns?: string[]
  column_types?: Record<string, ColumnType>
  rows?: Record<string, unknown>[]
    row_count?: number
    success?: boolean
    error?: string
  } | null
  created_at: string
}

export const chatApi = {
  listConversations() {
    return request.get<{ results: ConversationItem[] }>('/api/query/chat/conversations/')
  },

  createConversation(payload: { chat_mode: string; dataset_id?: string; source_id?: string }) {
    return request.post<ConversationItem>('/api/query/chat/conversations/', payload)
  },

  getConversation(id: string) {
    return request.get<{ conversation: ConversationItem; messages: ChatMessageItem[] }>(
      `/api/query/chat/conversations/${id}/`)
  },

  removeConversation(id: string) {
    return request.delete(`/api/query/chat/conversations/${id}/`)
  },

  /** 回答过程追溯（按 assistant 消息 id 拉取 span 时间线） */
  getTrace(messageId: number) {
    return request.get<{ trace_id: string | null; spans: TraceSpanItem[] }>(
      `/api/query/chat/messages/${messageId}/trace/`)
  },

  /**
   * SSE 流式问答。axios 不支持流式读取，走原生 fetch + ReadableStream。
   * 事件按空行分帧，data: [DONE] 结束。
   */
  async streamChat(
    conversationId: string,
    question: string,
    handlers: {
      onDelta?: (text: string) => void
      onAnswer?: (frame: ChatFrame) => void
      onView?: (frame: ChatFrame) => void
      onError?: (message: string) => void
      onDone?: (frame: ChatFrame) => void
    },
  ) {
    const resp = await fetch(`/api/query/chat/conversations/${conversationId}/messages/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ question }),
    })
    if (!resp.ok || !resp.body) {
      const detail = await resp.json().catch(() => null)
      throw new Error(detail?.error || `请求失败（${resp.status}）`)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const dispatch = (frame: ChatFrame) => {
      if (frame.type === 'delta') handlers.onDelta?.(frame.content || '')
      else if (frame.type === 'answer') handlers.onAnswer?.(frame)
      else if (frame.type === 'view') handlers.onView?.(frame)
      else if (frame.type === 'error') handlers.onError?.(frame.message || '未知错误')
      else if (frame.type === 'done') handlers.onDone?.(frame)
    }

    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let sep: number
      while ((sep = buffer.indexOf('\n\n')) >= 0) {
        const event = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        for (const line of event.split('\n')) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6)
          if (payload === '[DONE]') return
          try {
            dispatch(JSON.parse(payload))
          } catch {
            // 半帧/坏帧丢弃，等下一事件
          }
        }
      }
    }
  },
}
