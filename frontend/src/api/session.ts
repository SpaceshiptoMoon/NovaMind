import { request } from './index'
import type {
  ChatMessage,
  AddMessageRequest,
  UpdateMessageRequest,
  QAContextResponse,
  SessionListResponse,
  CreateSessionConfigRequest,
  SessionConfigResponse,
} from './types'

const BASE_URL = '/qa'

export const sessionApi = {
  addMessage(data: AddMessageRequest) {
    return request.post<ChatMessage>(`${BASE_URL}/message`, data)
  },

  updateMessage(messageId: number, data: UpdateMessageRequest) {
    return request.put<ChatMessage>(`${BASE_URL}/message/${messageId}`, data)
  },

  deleteMessage(messageId: number) {
    return request.delete<void>(`${BASE_URL}/message/${messageId}`)
  },

  getContext(sessionId: string, limit?: number) {
    return request.get<QAContextResponse>(`${BASE_URL}/context/${sessionId}`, limit ? { limit } : undefined)
  },

  getSessionMessages(sessionId: string) {
    return request.get<ChatMessage[]>(`${BASE_URL}/session/${sessionId}`)
  },

  getSessions(params?: { limit?: number; offset?: number }) {
    return request.get<SessionListResponse>(`${BASE_URL}/sessions`, params)
  },

  deleteSession(sessionId: string) {
    return request.delete<void>(`${BASE_URL}/session/${sessionId}`)
  },

  // 会话压缩配置
  createConfig(sessionId: string, data: CreateSessionConfigRequest) {
    return request.post<SessionConfigResponse>(`/sessions/${sessionId}/config`, data)
  },

  getConfig(sessionId: string) {
    return request.get<SessionConfigResponse>(`/sessions/${sessionId}/config`)
  },

  deleteConfig(sessionId: string) {
    return request.delete<void>(`/sessions/${sessionId}/config`)
  },
}
