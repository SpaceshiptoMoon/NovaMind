import { request, createSSEStream, tokenManager } from './index'
import type { ChatRequest, ChatResponse, ChatHistoryResponse, HealthCheckResponse, ModelsResponse, UploadChatAttachmentResponse } from './types'

const BASE_URL = '/ai-chat'

export const chatApi = {
  chat(data: ChatRequest) {
    return request.post<ChatResponse>(`${BASE_URL}/chat`, data)
  },

  uploadAttachment(file: File, onProgress?: (percent: number) => void) {
    return request.upload<UploadChatAttachmentResponse>(`${BASE_URL}/chat-attachments`, file, onProgress)
  },

  downloadAttachment(attachmentId: number) {
    return `${BASE_URL}/chat-attachments/${attachmentId}/download`
  },

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

  chatStream(
    data: ChatRequest,
    callbacks: {
      onUserMessage?: (msg: { id: number; content: string; role: string; session_id: string }) => void
      onReasoning?: (text: string) => void
      onContent?: (content: string) => void
      onDone?: (msg: { id: number; content: string; role: string; session_id: string }) => void
      onError?: (err: { code: string; message: string }) => void
      signal?: AbortSignal
    },
  ) {
    return createSSEStream(`${BASE_URL}/chat-stream`, data, {
      onMessage(event) {
        const e = event as { type: string; data: unknown }
        switch (e.type) {
          case 'user_message':
            callbacks.onUserMessage?.(e.data as Parameters<typeof callbacks.onUserMessage>[0])
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
      onError: callbacks.onError ? (msg) => callbacks.onError!({ code: 'STREAM_ERROR', message: msg }) : undefined,
      signal: callbacks.signal,
    })
  },

  getChatHistory(sessionId: string) {
    return request.get<ChatHistoryResponse>(`${BASE_URL}/chat-history`, { session_id: sessionId })
  },

  clearChat(sessionId: string) {
    return request.delete<void>(`${BASE_URL}/clear-chat`, { session_id: sessionId })
  },

  healthCheck() {
    return request.get<HealthCheckResponse>(`${BASE_URL}/health`)
  },

  getModels() {
    return request.get<ModelsResponse>(`${BASE_URL}/models`)
  },
}
