import { request } from './index'
import type {
  ChatMessage,
  AddMessageRequest,
  UpdateMessageRequest,
  QAContextResponse,
  SessionListResponse,
  CreateSessionConfigRequest,
  SessionConfigCompressionUpdate,
  SessionConfigLlmUpdate,
  SessionConfigResponse,
  SessionConfigRagUpdate,
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

  // 更新压缩配置（支持反复修改，不影响知识库绑定）
  updateCompressionConfig(sessionId: string, data: SessionConfigCompressionUpdate) {
    return request.patch<SessionConfigResponse>(`/sessions/${sessionId}/config/compression-config`, data)
  },

  // 更新模型生成参数配置（max_tokens/temperature/top_p/system_prompt，支持反复修改）
  updateLlmConfig(sessionId: string, data: SessionConfigLlmUpdate) {
    return request.patch<SessionConfigResponse>(`/sessions/${sessionId}/config/llm-config`, data)
  },

  getConfig(sessionId: string) {
    return request.get<SessionConfigResponse>(`/sessions/${sessionId}/config`)
  },

  deleteConfig(sessionId: string) {
    return request.delete<void>(`/sessions/${sessionId}/config`)
  },

  // 会话级自动 RAG（知识库绑定，独立于压缩配置，可反复修改）
  updateRagConfig(sessionId: string, data: SessionConfigRagUpdate) {
    return request.patch<SessionConfigResponse>(`/sessions/${sessionId}/config/rag-config`, data)
  },
}
