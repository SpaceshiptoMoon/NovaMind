import { request } from './index'
import type {
  ChatMessage,
  AddMessageRequest,
  UpdateMessageRequest,
  MessageFeedbackRequest,
  MessageFeedbackResponse,
  QAContextResponse,
  SessionListResponse,
  CreateSessionConfigRequest,
  SessionConfigCompressionUpdate,
  SessionConfigLlmUpdate,
  SessionConfigResponse,
  SessionConfigRagUpdate,
  SessionConfigWebSearchUpdate,
} from './types'

const BASE_URL = '/qa'

/**
 * session API
 *
 * 答疑会话：消息 CRUD 与反馈、上下文与历史、会话级配置（压缩/模型参数/RAG/联网搜索）
 */
export const sessionApi = {
  /** 追加一条消息到会话（可指定角色与 space/kb 绑定） */
  addMessage(data: AddMessageRequest) {
    return request.post<ChatMessage>(`${BASE_URL}/message`, data)
  },

  /** 修改消息内容 */
  updateMessage(messageId: number, data: UpdateMessageRequest) {
    return request.put<ChatMessage>(`${BASE_URL}/message/${messageId}`, data)
  },

  /** 删除单条消息 */
  deleteMessage(messageId: number) {
    return request.delete<void>(`${BASE_URL}/message/${messageId}`)
  },

  /** 设置/撤销消息反馈（rating: up/down/null=撤销） */
  setMessageFeedback(messageId: number, data: MessageFeedbackRequest) {
    return request.put<MessageFeedbackResponse>(
      `${BASE_URL}/message/${messageId}/feedback`,
      data,
    )
  },

  /** 会话上下文窗口（最近 N 条拼成 role/content 数组，供前端预览） */
  getContext(sessionId: string, limit?: number) {
    return request.get<QAContextResponse>(
      `${BASE_URL}/context/${sessionId}`,
      limit ? { limit } : undefined,
    )
  },

  /** 会话全部消息 */
  getSessionMessages(sessionId: string) {
    return request.get<ChatMessage[]>(`${BASE_URL}/session/${sessionId}`)
  },

  /** 当前用户的会话列表（分页） */
  getSessions(params?: { limit?: number; offset?: number }) {
    return request.get<SessionListResponse>(`${BASE_URL}/sessions`, params)
  },

  /** 删除整个会话 */
  deleteSession(sessionId: string) {
    return request.delete<void>(`${BASE_URL}/session/${sessionId}`)
  },

  // 会话压缩配置
  /** 创建会话配置（初始为压缩配置；每会话一份） */
  createConfig(sessionId: string, data: CreateSessionConfigRequest) {
    return request.post<SessionConfigResponse>(`/sessions/${sessionId}/config`, data)
  },

  // 更新压缩配置（支持反复修改，不影响知识库绑定）
  /** 更新压缩策略与阈值（enable_compression/strategy/threshold 等） */
  updateCompressionConfig(sessionId: string, data: SessionConfigCompressionUpdate) {
    return request.patch<SessionConfigResponse>(
      `/sessions/${sessionId}/config/compression-config`,
      data,
    )
  },

  // 更新模型生成参数配置（max_tokens/temperature/top_p/system_prompt，支持反复修改）
  /** 更新模型生成参数与会话级 system_prompt */
  updateLlmConfig(sessionId: string, data: SessionConfigLlmUpdate) {
    return request.patch<SessionConfigResponse>(`/sessions/${sessionId}/config/llm-config`, data)
  },

  /** 读取会话完整配置（压缩/RAG 绑定/模型参数/联网搜索） */
  getConfig(sessionId: string) {
    return request.get<SessionConfigResponse>(`/sessions/${sessionId}/config`)
  },

  /** 删除会话配置（各子配置一并清除） */
  deleteConfig(sessionId: string) {
    return request.delete<void>(`/sessions/${sessionId}/config`)
  },

  // 会话级自动 RAG（知识库绑定，独立于压缩配置，可反复修改）
  /** 更新会话级知识库绑定（发问自动触发 RAG 检索） */
  updateRagConfig(sessionId: string, data: SessionConfigRagUpdate) {
    return request.patch<SessionConfigResponse>(`/sessions/${sessionId}/config/rag-config`, data)
  },

  // 更新联网搜索引擎配置（provider/max_results，启用开关由请求级 enable_web_search 控制）
  /** 更新联网搜索 provider 与结果数（每次提问是否启用由请求级开关决定） */
  updateWebSearchConfig(sessionId: string, data: SessionConfigWebSearchUpdate) {
    return request.patch<SessionConfigResponse>(
      `/sessions/${sessionId}/config/web-search-config`,
      data,
    )
  },
}
