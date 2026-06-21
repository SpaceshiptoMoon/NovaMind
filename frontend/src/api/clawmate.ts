/**
 * ClawMate API 模块
 *
 * AI 对话（SSE 流式）
 */

import { createSSEStream } from './index'
import type {
  ClawMateChatRequest,
  ClawMateChatDoneData,
} from './types'

const BASE = '/clawmate'

export const clawmateApi = {
  // ==================== AI 对话（SSE 流式） ====================

  /** SSE 流式对话 */
  chatStream(
    data: ClawMateChatRequest,
    callbacks: {
      onContent?: (text: string) => void
      onReasoning?: (text: string) => void
      onToolCall?: (d: { name: string; arguments: Record<string, unknown>; call_id: string }) => void
      onToolResult?: (d: { name: string; result: string }) => void
      onWarning?: (message: string) => void
      onError?: (message: string) => void
      onDone?: (d: ClawMateChatDoneData) => void
      signal?: AbortSignal
    },
  ) {
    return createSSEStream(`${BASE}/chat`, data, {
      onMessage(event) {
        const e = event as { type: string; data: unknown }
        switch (e.type) {
          case 'content':
            callbacks.onContent?.((e.data as { text: string }).text)
            break
          case 'reasoning':
            callbacks.onReasoning?.((e.data as { text: string }).text)
            break
          case 'tool_call':
            callbacks.onToolCall?.(e.data as { name: string; arguments: Record<string, unknown>; call_id: string })
            break
          case 'tool_result':
            callbacks.onToolResult?.(e.data as { name: string; result: string })
            break
          case 'warning':
            callbacks.onWarning?.((e.data as { message: string }).message)
            break
          case 'error':
            callbacks.onError?.((e.data as { message: string }).message)
            break
          case 'done':
            callbacks.onDone?.(e.data as ClawMateChatDoneData)
            break
        }
      },
      onError: callbacks.onError ? (msg: string) => callbacks.onError!(msg) : undefined,
      signal: callbacks.signal,
    })
  },
}
