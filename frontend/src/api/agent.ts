import { request, createWebSocketStream, tokenManager } from './index'
import type {
  Agent,
  CreateAgentRequest,
  UpdateAgentRequest,
  AgentListResponse,
  AgentChatDoneData,
  AgentCompactionData,
  AgentContextUsageData,
  PlanData,
  LoopWarningData,
  SystemPromptResponse,
  AgentConversation,
  AgentConversationListResponse,
  KnowledgeBindings,
  ResearchProgressData,
  AgentMessageListResponse,
  OpenAICompatToolCall,
  McpServer,
  McpTool,
  CreateMcpServerRequest,
  UpdateMcpServerRequest,
  ToolProvider,
  ApiKeyListResponse,
  ApiKeyCreatedResponse,
  ApiKeyRevokeResponse,
} from './types'

// ===================== Agent 管理 =====================

/**
 * Agent API
 *
 * Agent CRUD、WebSocket 流式对话与会话历史、MCP 服务器管理、内置工具查询
 */
export const agentApi = {
  /** 默认助手（不存在时后端自动创建，幂等） */
  getDefaultAgent() {
    return request.get<Agent>('/agent/agents/default')
  },

  /** Agent 列表（分页） */
  listAgents(params?: { limit?: number; offset?: number }) {
    return request.get<AgentListResponse>('/agent/agents', params as Record<string, unknown>)
  },

  /** Agent 详情 */
  getAgent(agentId: number) {
    return request.get<Agent>(`/agent/agents/${agentId}`)
  },

  /** 创建 Agent（system_prompt 必填，模型与生成参数可选） */
  createAgent(data: CreateAgentRequest) {
    return request.post<Agent>('/agent/agents', data)
  },

  /** 更新 Agent 配置（提示词/模型/生成参数） */
  updateAgent(agentId: number, data: UpdateAgentRequest) {
    return request.put<Agent>(`/agent/agents/${agentId}`, data)
  },

  /** 删除 Agent */
  deleteAgent(agentId: number) {
    return request.delete<{ success: boolean; message: string }>(`/agent/agents/${agentId}`)
  },

  // ===================== Agent 对话 =====================

  /**
   * Agent WebSocket 流式对话
   *
   * 按事件类型分发回调：reasoning/content 增量、tool_call/tool_result、
   * sources 引用、plan.* 计划事件、compaction 上下文压缩、done 收尾；
   * 事件里会带 session_id（onSession），首条消息后可用于续接会话。
   */
  chatStream(
    agentId: number,
    data: {
      content: string
      session_id?: string | null
      llm_model?: string | null
      enable_thinking?: boolean
      deep_research?: boolean
      stream?: boolean
      attachment_ids?: number[]
    },
    callbacks: {
      onSession?: (d: { session_id: string; agent_id: number }) => void
      onToolCall?: (d: {
        tool_name: string
        arguments: Record<string, unknown>
        call_id: string
      }) => void
      onToolResult?: (d: {
        tool_name: string
        result: string
        duration_ms: number
        status: string
        call_id: string
      }) => void
      onReasoning?: (text: string) => void
      onAssistantToolCalls?: (d: { tool_calls: OpenAICompatToolCall[] }) => void
      onContent?: (content: string) => void
      onSources?: (d: {
        sources: {
          index: number
          kind: string
          document_name?: string | null
          url?: string | null
          snippet?: string | null
          score?: number | null
          document_id?: number | null
          chunk_id?: string | null
        }[]
      }) => void
      onDone?: (d: AgentChatDoneData) => void
      onCompaction?: (d: AgentCompactionData) => void
      onContextUsage?: (d: AgentContextUsageData) => void
      onPlan?: (type: string, d: PlanData) => void
      onLoopWarning?: (d: LoopWarningData) => void
      onResearchProgress?: (d: ResearchProgressData) => void
      onSteering?: (d: { content: string; iteration: number }) => void
      onError?: (err: { content: string }) => void
      signal?: AbortSignal
      /** 握手完成后的发送通道（双向）：store 可发 {action:'message', content} 运行中插话 */
      onReady?: (send: (msg: unknown) => void) => void
    },
  ) {
    return createWebSocketStream(`/agent/agents/${agentId}/ws`, data, {
      onMessage(event) {
        const e = event
        switch (e.type) {
          case 'session':
            callbacks.onSession?.(e.data as Parameters<typeof callbacks.onSession>[0])
            break
          case 'tool_call':
            callbacks.onToolCall?.(e.data as Parameters<typeof callbacks.onToolCall>[0])
            break
          case 'assistant_tool_calls':
            callbacks.onAssistantToolCalls?.(
              e.data as Parameters<typeof callbacks.onAssistantToolCalls>[0],
            )
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
          case 'sources':
            callbacks.onSources?.(e.data as Parameters<typeof callbacks.onSources>[0])
            break
          case 'done':
            callbacks.onDone?.(e.data as AgentChatDoneData)
            break
          case 'compaction':
            callbacks.onCompaction?.(e.data as AgentCompactionData)
            break
          case 'context_usage':
            callbacks.onContextUsage?.(e.data as AgentContextUsageData)
            break
          case 'plan.created':
          case 'plan.step_started':
          case 'plan.step_completed':
          case 'plan.step_failed':
          case 'plan.completed':
            callbacks.onPlan?.(e.type, e.data as PlanData)
            break
          case 'loop_warning':
            callbacks.onLoopWarning?.(e.data as LoopWarningData)
            break
          case 'research_progress':
            callbacks.onResearchProgress?.(e.data as ResearchProgressData)
            break
          case 'steering':
            callbacks.onSteering?.(e.data as { content: string; iteration: number })
            break
          case 'error':
            callbacks.onError?.(e.data as { content: string })
            break
        }
      },
      onError: callbacks.onError ? (msg) => callbacks.onError!({ content: msg }) : undefined,
      signal: callbacks.signal,
      // 运行中插话通道：chatStream 不直接用，store 拿到 send 后可随时发
      // {action: 'message', content: '...'}（agent 执行期间在 ReAct 轮边界注入）
      onReady: callbacks.onReady,
    })
  },

  /** 跨全部 Agent 的会话列表（分页，created_at 倒序） */
  listAllSessions(params?: { limit?: number; offset?: number }) {
    return request.get<AgentConversationListResponse>(
      '/agent/sessions',
      params as Record<string, unknown>,
    )
  },

  /** 指定 Agent 的会话列表（分页） */
  listSessions(agentId: number, params?: { limit?: number; offset?: number }) {
    return request.get<AgentConversationListResponse>(
      `/agent/agents/${agentId}/sessions`,
      params as Record<string, unknown>,
    )
  },

  /** 会话详情（标题/状态/消息数/累计 token） */
  getSession(sessionId: string) {
    return request.get<AgentConversation>(`/agent/sessions/${sessionId}`)
  },

  /** 更新会话知识绑定（整体替换；传 null 清除恢复不限定） */
  updateKnowledgeBindings(sessionId: string, bindings: KnowledgeBindings | null) {
    return request.put<AgentConversation>(
      `/agent/sessions/${sessionId}/knowledge-bindings`,
      { knowledge_bindings: bindings },
    )
  },

  /** 会话消息历史（分页） */
  getMessages(sessionId: string, params?: { limit?: number; offset?: number }) {
    return request.get<AgentMessageListResponse>(
      `/agent/sessions/${sessionId}/messages`,
      params as Record<string, unknown>,
    )
  },

  /** 会话上下文占用（used/window 分项 token，含是否已压缩） */
  getContextUsage(sessionId: string) {
    return request.get<AgentContextUsageData>(`/agent/sessions/${sessionId}/context-usage`)
  },

  /** 会话实际生效的 system prompt 全文（含 token 数，调试轨迹用） */
  getSystemPrompt(sessionId: string) {
    return request.get<SystemPromptResponse>(`/agent/sessions/${sessionId}/system-prompt`)
  },

  /** 删除会话（连同消息历史） */
  deleteSession(sessionId: string) {
    return request.delete<{ success: boolean; message: string }>(`/agent/sessions/${sessionId}`)
  },

  // ===================== MCP 服务器 =====================

  /** 已配置的 MCP 服务器列表 */
  listMcpServers() {
    return request.get<McpServer[]>('/agent/mcp-servers')
  },

  /** 新增 MCP 服务器配置 */
  createMcpServer(data: CreateMcpServerRequest) {
    return request.post<McpServer>('/agent/mcp-servers', data)
  },

  /** 更新 MCP 服务器配置 */
  updateMcpServer(serverId: number, data: UpdateMcpServerRequest) {
    return request.put<McpServer>(`/agent/mcp-servers/${serverId}`, data)
  },

  /** 删除 MCP 服务器配置 */
  deleteMcpServer(serverId: number) {
    return request.delete<{ success: boolean; message: string }>(`/agent/mcp-servers/${serverId}`)
  },

  /** 建立与 MCP 服务器的连接 */
  connectMcpServer(serverId: number) {
    return request.post<McpServer>(`/agent/mcp-servers/${serverId}/connect`)
  },

  /** 断开与 MCP 服务器的连接 */
  disconnectMcpServer(serverId: number) {
    return request.post<McpServer>(`/agent/mcp-servers/${serverId}/disconnect`)
  },

  /** 重连并重新拉取该服务器的工具清单 */
  refreshMcpTools(serverId: number) {
    return request.post<{ success: boolean; tools: McpTool[] }>(
      `/agent/mcp-servers/${serverId}/refresh-tools`,
    )
  },

  /** 保存前连通性测试：按提交的配置真实握手一次，返回可达工具列表 */
  testMcpConnection(data: CreateMcpServerRequest) {
    return request.post<{ success: boolean; tools: McpTool[] }>(
      '/agent/mcp-servers/test-connection',
      data,
    )
  },

  // ===================== 工具 =====================

  /** 内置工具 provider 列表（每个 provider 含其下工具函数与提示词片段） */
  listTools() {
    return request.get<ToolProvider[]>('/agent/tools')
  },

  /** 单个工具 provider 详情 */
  getTool(toolName: string) {
    return request.get<ToolProvider>(`/agent/tools/${toolName}`)
  },

  /** 可用模型清单（/agent/models 共享端点，附件下载同源） */
  getModels() {
    return request.get<{
      models: Record<string, { max_tokens: number; temperature: number; top_p: number; model_type: string }>
    }>('/agent/models')
  },

  /** 上传对话附件（共享 /agent/attachments 端点，带上传进度回调） */
  uploadAttachment(file: File, onProgress?: (percent: number) => void) {
    return request.upload<{
      attachment_id: number
      filename: string
      file_type: string
      file_size: number
    }>(
      '/agent/attachments',
      file,
      onProgress,
    )
  },

  /** 拼接附件下载 URL（不带鉴权头，直接给 <a href> 用） */
  downloadAttachment(attachmentId: number) {
    return `/agent/attachments/${attachmentId}/download`
  },

  /** 带鉴权头 fetch 附件并以浏览器下载方式保存（下载失败抛错） */
  async downloadAttachmentFile(attachmentId: number, filename: string) {
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const token = tokenManager.getToken()
    const res = await fetch(`${baseURL}/agent/attachments/${attachmentId}/download`, {
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

// ===================== Agent API 密钥（MCP 访问凭证） =====================

/**
 * API 密钥管理
 *
 * 外部 agent（Claude Code MCP 等）访问 NovaMind 的凭证生命周期：
 * 创建（明文仅此一次返回）/ 列表（脱敏）/ 吊销（即时失效）。
 * 后端契约：backend/src/features/agent_api/api/key_routes.py
 */
export const apiKeyApi = {
  /** 我的 key 列表（含已吊销历史，无明文字段） */
  listKeys() {
    return request.get<ApiKeyListResponse>('/agent-api/keys')
  },

  /** 创建 key——响应里的 api_key 明文仅此一次，展示后不可再查 */
  createKey(name: string) {
    return request.post<ApiKeyCreatedResponse>('/agent-api/keys', { name })
  },

  /** 吊销 key（即时失效；幂等，已吊销再次吊销返回原状态） */
  revokeKey(keyId: number) {
    return request.delete<ApiKeyRevokeResponse>(`/agent-api/keys/${keyId}`)
  },
}
