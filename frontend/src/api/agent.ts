import { request, createSSEStream, tokenManager } from './index'
import type {
  Agent,
  CreateAgentRequest,
  UpdateAgentRequest,
  AgentListResponse,
  AgentChatDoneData,
  AgentConversation,
  AgentConversationListResponse,
  AgentMessage,
  AgentMessageListResponse,
  McpServer,
  McpTool,
  CreateMcpServerRequest,
  UpdateMcpServerRequest,
  ToolProvider,
  ToolCallRecord,
} from './types'

// ===================== Agent 管理 =====================

export const agentApi = {
  listAgents(params?: { limit?: number; offset?: number }) {
    return request.get<AgentListResponse>('/agent/agents', params as Record<string, unknown>)
  },

  getAgent(agentId: number) {
    return request.get<Agent>(`/agent/agents/${agentId}`)
  },

  createAgent(data: CreateAgentRequest) {
    return request.post<Agent>('/agent/agents', data)
  },

  updateAgent(agentId: number, data: UpdateAgentRequest) {
    return request.put<Agent>(`/agent/agents/${agentId}`, data)
  },

  deleteAgent(agentId: number) {
    return request.delete<{ success: boolean; message: string }>(`/agent/agents/${agentId}`)
  },

  // ===================== Agent 对话 =====================

  chatStream(
    agentId: number,
    data: { content: string; session_id?: string | null; llm_model?: string | null; enable_thinking?: boolean; stream?: boolean; attachment_ids?: number[] },
    callbacks: {
      onSession?: (d: { session_id: string; agent_id: number }) => void
      onToolCall?: (d: { tool_name: string; arguments: Record<string, unknown>; call_id: string }) => void
      onToolResult?: (d: { tool_name: string; result: string; duration_ms: number; status: string; call_id: string }) => void
      onReasoning?: (text: string) => void
      onContent?: (content: string) => void
      onDone?: (d: AgentChatDoneData) => void
      onError?: (err: { content: string }) => void
      signal?: AbortSignal
    },
  ) {
    return createSSEStream(`/agent/agents/${agentId}/chat-stream`, data, {
      onMessage(event) {
        const e = event
        switch (e.type) {
          case 'session':
            callbacks.onSession?.(e.data as Parameters<typeof callbacks.onSession>[0])
            break
          case 'tool_call':
            callbacks.onToolCall?.(e.data as Parameters<typeof callbacks.onToolCall>[0])
            break
          case 'tool_result':
            callbacks.onToolResult?.(e.data as Parameters<typeof callbacks.onToolResult>[0])
            break
          case 'reasoning':
            callbacks.onReasoning?.((e.data as { content: string }).content)
            break
          case 'content':
            callbacks.onContent?.((e.data as { content: string }).content)
            break
          case 'done':
            callbacks.onDone?.(e.data as AgentChatDoneData)
            break
          case 'error':
            callbacks.onError?.(e.data as { content: string })
            break
        }
      },
      onError: callbacks.onError ? (msg) => callbacks.onError!({ content: msg }) : undefined,
      signal: callbacks.signal,
    })
  },

  listSessions(agentId: number, params?: { limit?: number; offset?: number }) {
    return request.get<AgentConversationListResponse>(`/agent/agents/${agentId}/sessions`, params as Record<string, unknown>)
  },

  getSession(sessionId: string) {
    return request.get<AgentConversation>(`/agent/sessions/${sessionId}`)
  },

  getMessages(sessionId: string, params?: { limit?: number; offset?: number }) {
    return request.get<AgentMessageListResponse>(`/agent/sessions/${sessionId}/messages`, params as Record<string, unknown>)
  },

  deleteSession(sessionId: string) {
    return request.delete<{ success: boolean; message: string }>(`/agent/sessions/${sessionId}`)
  },

  // ===================== MCP 服务器 =====================

  listMcpServers() {
    return request.get<McpServer[]>('/agent/mcp-servers')
  },

  createMcpServer(data: CreateMcpServerRequest) {
    return request.post<McpServer>('/agent/mcp-servers', data)
  },

  updateMcpServer(serverId: number, data: UpdateMcpServerRequest) {
    return request.put<McpServer>(`/agent/mcp-servers/${serverId}`, data)
  },

  deleteMcpServer(serverId: number) {
    return request.delete<{ success: boolean; message: string }>(`/agent/mcp-servers/${serverId}`)
  },

  connectMcpServer(serverId: number) {
    return request.post<McpServer>(`/agent/mcp-servers/${serverId}/connect`)
  },

  disconnectMcpServer(serverId: number) {
    return request.post<McpServer>(`/agent/mcp-servers/${serverId}/disconnect`)
  },

  refreshMcpTools(serverId: number) {
    return request.post<{ success: boolean; tools: McpTool[] }>(`/agent/mcp-servers/${serverId}/refresh-tools`)
  },

  testMcpConnection(data: CreateMcpServerRequest) {
    return request.post<{ success: boolean; tools: McpTool[] }>('/agent/mcp-servers/test-connection', data)
  },

  // ===================== 工具 =====================

  listTools() {
    return request.get<ToolProvider[]>('/agent/tools')
  },

  getTool(toolName: string) {
    return request.get<ToolProvider>(`/agent/tools/${toolName}`)
  },

  downloadAttachment(attachmentId: number) {
    return `/ai-chat/chat-attachments/${attachmentId}/download`
  },

  async downloadAttachmentFile(attachmentId: number, filename: string) {
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const token = tokenManager.getToken()
    const res = await fetch(`${baseURL}/ai-chat/chat-attachments/${attachmentId}/download`, {
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
}
