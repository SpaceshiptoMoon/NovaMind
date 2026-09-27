import { request, createWebSocketStream, tokenManager } from './index'
import type {
  ChatRequest,
  ChatResponse,
  ChatHistoryResponse,
  HealthCheckResponse,
  ModelsResponse,
  UploadChatAttachmentResponse,
  ChatSource,
  ChatAttachment,
} from './types'

const BASE_URL = '/ai-chat'

/**
 * chat API
 *
 * 智能答疑：普通问答、WebSocket 流式问答、附件上传下载、历史与清理
 */
export const chatApi = {
  /** 一次性问答（非流式，等待完整回答返回） */
  chat(data: ChatRequest) {
    return request.post<ChatResponse>(`${BASE_URL}/chat`, data)
  },

  /** 上传对话附件（带上传进度回调） */
  uploadAttachment(file: File, onProgress?: (percent: number) => void) {
    return request.upload<UploadChatAttachmentResponse>(
      `${BASE_URL}/chat-attachments`,
      file,
      onProgress,
    )
  },

  /** 拼接附件下载 URL（不带鉴权头，直接给 <a href> 用） */
  downloadAttachment(attachmentId: number) {
    return `${BASE_URL}/chat-attachments/${attachmentId}/download`
  },

  /** 带鉴权头 fetch 附件并以浏览器下载方式保存（下载失败抛错） */
  async downloadAttachmentFile(attachmentId: number, filename: string) {
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const token = tokenManager.getToken()
    const res = await fetch(`${baseURL}${BASE_URL}/chat-attachments/${attachmentId}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) throw new Error('下载失败')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  },

  /**
   * WebSocket 流式问答
   *
   * 事件回调：user_message 回显用户消息、sources 检索引用、trace 检索链路、
   * reasoning/content 增量、done 终稿（含来源与置信度）；AbortSignal 可中断。
   */
  chatStream(
    data: ChatRequest,
    callbacks: {
      // 与后端 ai_chat_service 的 user_message 事件载荷对齐（含 created_at / attachments）
      onUserMessage?: (msg: {
        id: number
        content: string
        role: string
        session_id: string
        created_at: string
        attachments?: ChatAttachment[]
      }) => void
      onSources?: (sources: ChatSource[]) => void
      onTrace?: (trace: Record<string, unknown>) => void
      onReasoning?: (text: string) => void
      onContent?: (content: string) => void
      onDone?: (msg: {
        id: number
        content: string
        role: string
        session_id: string
        sources?: ChatSource[]
        answer_status?: string
        confidence?: number | null
      }) => void
      onError?: (err: { code: string; message: string }) => void
      signal?: AbortSignal
    },
  ) {
    return createWebSocketStream(`${BASE_URL}/ws`, data, {
      onMessage(event) {
        const e = event as { type: string; data: unknown }
        switch (e.type) {
          case 'user_message':
            callbacks.onUserMessage?.(e.data as Parameters<typeof callbacks.onUserMessage>[0])
            break
          case 'sources':
            callbacks.onSources?.(e.data as ChatSource[])
            break
          case 'trace':
            callbacks.onTrace?.(e.data as Record<string, unknown>)
            break
          case 'reasoning':
            callbacks.onReasoning?.((e.data as { content: string }).content)
            break
          case 'content':
            callbacks.onContent?.((e.data as { content: string }).content)
            break
          case 'done':
            callbacks.onDone?.(e.data as Parameters<typeof callbacks.onDone>[0])
            break
          case 'error': {
            const err = e.data as Record<string, unknown>
            callbacks.onError?.({
              code: (err.code as string) || 'ERROR',
              message: (err.message as string) || (err.content as string) || '未知错误',
            })
            break
          }
        }
      },
      onError: callbacks.onError
        ? (msg) => callbacks.onError!({ code: 'STREAM_ERROR', message: msg })
        : undefined,
      signal: callbacks.signal,
    })
  },

  /** 会话历史消息 */
  getChatHistory(sessionId: string) {
    return request.get<ChatHistoryResponse>(`${BASE_URL}/chat-history`, { session_id: sessionId })
  },

  /** 清空会话消息（会话本身保留） */
  clearChat(sessionId: string) {
    return request.delete<void>(`${BASE_URL}/clear-chat`, { session_id: sessionId })
  },

  /** 服务健康探活 */
  healthCheck() {
    return request.get<HealthCheckResponse>(`${BASE_URL}/health`)
  },

  /** 可用 LLM 模型清单 */
  getModels() {
    return request.get<ModelsResponse>(`${BASE_URL}/models`)
  },
}
