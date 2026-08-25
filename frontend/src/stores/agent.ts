import { ref } from 'vue'
import { defineStore } from 'pinia'
import { agentApi } from '@/api/agent'
import type {
  Agent,
  CreateAgentRequest,
  UpdateAgentRequest,
  AgentConversation,
  AgentMessage,
  McpServer,
  ToolProvider,
  ToolCallRecord,
  ChatAttachment,
  SourceRef,
  OpenAICompatToolCall,
  AgentContextUsageData,
} from '@/api/types'

// 后端工具状态归并到前端 ToolCallRecord.status 四态
// pending/running → running；completed → completed；failed/timeout/其它 → failed
function normalizeToolStatus(status: string): ToolCallRecord['status'] {
  switch (status) {
    case 'completed':
      return 'completed'
    case 'pending':
    case 'running':
      return 'running'
    default:
      return 'failed'
  }
}

export const useAgentStore = defineStore('agent', () => {
  // Agent 列表
  const agents = ref<Agent[]>([])
  const agentsTotal = ref(0)
  const agentsLoading = ref(false)

  // 当前 Agent
  const currentAgent = ref<Agent | null>(null)

  // 对话列表
  const conversations = ref<AgentConversation[]>([])
  const conversationsTotal = ref(0)
  const conversationsLoading = ref(false)
  const currentSessionId = ref<string | null>(null)

  // 消息
  const messages = ref<AgentMessage[]>([])
  const messagesLoading = ref(false)

  // SSE 流式
  const isStreaming = ref(false)
  const streamingContent = ref('')
  const streamingReasoning = ref('')
  const streamingSources = ref<SourceRef[]>([])
  const toolCalls = ref<ToolCallRecord[]>([])
  const contextUsage = ref<AgentContextUsageData | null>(null)
  const abortController = ref<AbortController | null>(null)
  const loading = ref(false)
  const pendingAttachments = ref<ChatAttachment[]>([])

  // MCP & 工具（全局共享）
  const mcpServers = ref<McpServer[]>([])
  const tools = ref<ToolProvider[]>([])
  const error = ref<string | null>(null)

  // ===================== Agent CRUD =====================

  async function fetchAgents(params?: { limit?: number; offset?: number }) {
    agentsLoading.value = true
    try {
      const data = await agentApi.listAgents(params)
      agents.value = data.items || []
      agentsTotal.value = data.total || 0
    } catch {
      agents.value = []
    } finally {
      agentsLoading.value = false
    }
  }

  async function fetchAgent(agentId: number) {
    try {
      currentAgent.value = await agentApi.getAgent(agentId)
    } catch {
      currentAgent.value = null
    }
  }

  async function createAgent(data: CreateAgentRequest) {
    const agent = await agentApi.createAgent(data)
    agents.value.unshift(agent)
    agentsTotal.value += 1
    return agent
  }

  async function updateAgent(agentId: number, data: UpdateAgentRequest) {
    const updated = await agentApi.updateAgent(agentId, data)
    const idx = agents.value.findIndex((a) => a.id === agentId)
    if (idx !== -1) agents.value[idx] = updated
    if (currentAgent.value?.id === agentId) currentAgent.value = updated
    return updated
  }

  async function deleteAgent(agentId: number) {
    await agentApi.deleteAgent(agentId)
    agents.value = agents.value.filter((a) => a.id !== agentId)
    agentsTotal.value -= 1
    if (currentAgent.value?.id === agentId) {
      currentAgent.value = null
      clearChat()
    }
  }

  // ===================== 对话管理 =====================

  async function fetchConversations(agentId: number, params?: { limit?: number; offset?: number }) {
    conversationsLoading.value = true
    try {
      const data = await agentApi.listSessions(agentId, params)
      if (params?.offset && params.offset > 0) {
        conversations.value.push(...(data.items || []))
      } else {
        conversations.value = data.items || []
      }
      conversationsTotal.value = data.total || 0
    } catch {
      conversations.value = []
    } finally {
      conversationsLoading.value = false
    }
  }

  async function fetchMessages(sessionId: string) {
    messagesLoading.value = true
    error.value = null
    try {
      const data = await agentApi.getMessages(sessionId)
      messages.value = data.items || []
      currentSessionId.value = sessionId
      // 历史回放：用持久化的工具调用记录重建 toolCalls 状态，
      // 否则历史工具卡片因 getToolRecord 找不到记录而默认显示「执行中」
      toolCalls.value = (data.tool_calls || []).map((tc) => ({
        toolName: tc.tool_name,
        arguments: tc.arguments,
        callId: tc.call_id || '',
        status: normalizeToolStatus(tc.status),
        durationMs: tc.duration_ms ?? undefined,
        result: tc.result ?? undefined,
      }))
      // 历史回放 ContextMeter 初始值（全完整：切会话即显示仪表）
      try {
        contextUsage.value = await agentApi.getContextUsage(sessionId)
      } catch {
        contextUsage.value = null
      }
    } catch (e) {
      messages.value = []
      error.value = e instanceof Error ? e.message : '获取消息失败'
    } finally {
      messagesLoading.value = false
    }
  }

  async function deleteConversation(sessionId: string) {
    await agentApi.deleteSession(sessionId)
    conversations.value = conversations.value.filter((c) => c.session_id !== sessionId)
    if (currentSessionId.value === sessionId) {
      clearChat()
    }
  }

  // ===================== SSE 流式对话 =====================

  async function sendMessageStream(
    agentId: number,
    content: string,
    options?: { llm_model?: string; enable_thinking?: boolean; attachmentIds?: number[] },
  ) {
    if (!content.trim() && !options?.attachmentIds?.length) return

    // 添加用户消息
    const userMsg: AgentMessage = {
      id: Date.now(),
      conversation_id: 0,
      role: 'user',
      content,
      tool_call_id: null,
      tool_name: null,
      token_count: null,
      created_at: new Date().toISOString(),
      extra: options?.attachmentIds?.length
        ? {
            attachments: pendingAttachments.value.filter((a) =>
              options.attachmentIds!.includes(a.id),
            ),
          }
        : null,
    }
    messages.value.push(userMsg)
    if (options?.attachmentIds?.length) clearPendingAttachments()

    isStreaming.value = true
    streamingContent.value = ''
    streamingReasoning.value = ''
    streamingSources.value = []
    toolCalls.value = []
    error.value = null

    // 不预先 push assistant 占位消息，按事件顺序自然 push
    let assistantMsg: AgentMessage | null = null
    let assistantIndex = -1

    const controller = new AbortController()
    abortController.value = controller

    function ensureAssistant() {
      if (assistantMsg) return
      assistantMsg = {
        id: Date.now() + 1,
        conversation_id: 0,
        role: 'assistant',
        content: '',
        tool_call_id: null,
        tool_name: null,
        token_count: null,
        created_at: new Date().toISOString(),
      }
      messages.value.push(assistantMsg)
      assistantIndex = messages.value.length - 1
    }

    try {
      await agentApi.chatStream(
        agentId,
        {
          content,
          session_id: currentSessionId.value || null,
          llm_model: options?.llm_model || null,
          enable_thinking: options?.enable_thinking,
          stream: true,
          attachment_ids: options?.attachmentIds,
        },
        {
          signal: controller.signal,
          onSession(d) {
            if (!currentSessionId.value) {
              currentSessionId.value = d.session_id
              conversations.value.unshift({
                id: 0,
                user_id: 0,
                agent_id: agentId,
                session_id: d.session_id,
                title: content.slice(0, 30),
                status: 'active',
                message_count: 1,
                total_tokens_used: 0,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              })
            }
          },
          onToolCall(d) {
            const record: ToolCallRecord = {
              toolName: d.tool_name,
              arguments: d.arguments,
              callId: d.call_id,
              status: 'running',
            }
            toolCalls.value.push(record)

            const toolMsg: AgentMessage = {
              id: Date.now() + Math.random(),
              conversation_id: 0,
              role: 'tool',
              content: null,
              tool_call_id: d.call_id,
              tool_name: d.tool_name,
              token_count: null,
              created_at: new Date().toISOString(),
            }

            if (assistantIndex >= 0) {
              messages.value.splice(assistantIndex, 0, toolMsg)
              assistantIndex++
            } else {
              messages.value.push(toolMsg)
            }
          },
          onAssistantToolCalls(d) {
            // AI 决定调用工具：把当前轮已流式累积的 AI 文本（streamingContent）和思考
            // （streamingReasoning）归入该轮决策消息，再重置占位与累积器——下一轮进入新占位，
            // 最终回答只取最后一轮。还原 user → assistant(决策文本+think) → tool → ... → assistant(最终)。
            const decisionMsg: AgentMessage = {
              id: Date.now() + Math.random(),
              conversation_id: 0,
              role: 'assistant',
              content: streamingContent.value || null,
              reasoning: streamingReasoning.value || undefined,
              tool_call_id: null,
              tool_name: null,
              token_count: null,
              created_at: new Date().toISOString(),
              extra: { tool_calls: d.tool_calls as OpenAICompatToolCall[] },
            }
            if (assistantIndex >= 0) {
              messages.value.splice(assistantIndex, 0, decisionMsg)
              assistantIndex++
            } else {
              messages.value.push(decisionMsg)
            }
            // 重置：该轮文本+思考已归入决策消息，占位清空承载下一轮（最终回答）
            streamingContent.value = ''
            streamingReasoning.value = ''
            if (assistantMsg) {
              assistantMsg.content = ''
              assistantMsg.reasoning = ''
            }
          },
          onToolResult(d) {
            const call = toolCalls.value.find((c) => c.callId === d.call_id)
            if (call) {
              call.status = d.status === 'completed' ? 'completed' : 'failed'
              call.result = d.result
              call.durationMs = d.duration_ms
            }

            const toolMsg = messages.value.find(
              (m) => m.tool_call_id === d.call_id && m.role === 'tool',
            )
            if (toolMsg) {
              toolMsg.content = d.result
            }
          },
          onReasoning(text) {
            streamingReasoning.value += text || ''
            ensureAssistant()
            assistantMsg!.reasoning = streamingReasoning.value
          },
          onContent(text) {
            streamingContent.value += text || ''
            ensureAssistant()
            assistantMsg!.content = streamingContent.value
          },
          onSources(d) {
            streamingSources.value = d.sources as SourceRef[]
            ensureAssistant()
            assistantMsg!.sources = streamingSources.value
          },
          onDone(d) {
            ensureAssistant()
            if (d.message_id) assistantMsg!.id = d.message_id
            if (!assistantMsg!.content) {
              assistantMsg!.content = streamingContent.value
            }
            if (d.sources) {
              assistantMsg!.sources = d.sources
            }
            controller.abort()
          },
          onCompaction(d) {
            // 压缩标记行：dsh shadowed 语义，不移除历史消息，push 到末尾。
            // 后端历史回放 get_messages 也会返回 role='compaction' 消息，刷新后行为一致
            messages.value.push({
              id: Date.now() + Math.random(),
              conversation_id: 0,
              role: 'compaction',
              content: null,
              tool_call_id: null,
              tool_name: null,
              token_count: null,
              created_at: d.created_at || new Date().toISOString(),
              extra: { compaction: d },
            })
          },
          onContextUsage(d) {
            contextUsage.value = d
          },
          onError(err) {
            error.value = err.content
            ensureAssistant()
            if (!assistantMsg!.content) {
              assistantMsg!.content = `[错误] ${err.content}`
            }
          },
        },
      )
    } catch (e) {
      // 注意：assistantMsg 在闭包 ensureAssistant 中赋值，TS 在 catch 分支会将其
      // 收窄为 null，直接读 `assistantMsg.content` 会把真值分支判成 never；
      // 用 as 断言重置窄化类型绕过该陷阱。
      const pendingAssistant = assistantMsg as AgentMessage | null
      if (pendingAssistant && !pendingAssistant.content) {
        const idx = messages.value.indexOf(pendingAssistant)
        if (idx !== -1) messages.value.splice(idx, 1)
      }
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : '发送失败'
      throw e
    } finally {
      isStreaming.value = false
      streamingContent.value = ''
      streamingReasoning.value = ''
      streamingSources.value = []
      abortController.value = null
    }
  }

  // ===================== 非流式对话 =====================

  async function sendMessage(
    agentId: number,
    content: string,
    options?: { llm_model?: string; enable_thinking?: boolean; attachmentIds?: number[] },
  ) {
    if (!content.trim() && !options?.attachmentIds?.length) return

    const userMsg: AgentMessage = {
      id: Date.now(),
      conversation_id: 0,
      role: 'user',
      content,
      tool_call_id: null,
      tool_name: null,
      token_count: null,
      created_at: new Date().toISOString(),
      extra: options?.attachmentIds?.length
        ? {
            attachments: pendingAttachments.value.filter((a) =>
              options.attachmentIds!.includes(a.id),
            ),
          }
        : null,
    }
    messages.value.push(userMsg)
    if (options?.attachmentIds?.length) clearPendingAttachments()

    loading.value = true
    toolCalls.value = []
    error.value = null

    const controller2 = new AbortController()
    abortController.value = controller2

    try {
      let collectedContent = ''
      let collectedReasoning = ''
      let collectedSources: SourceRef[] = []
      const collectedToolCalls: ToolCallRecord[] = []
      // 决策消息按轮切片：记录每轮 tool_calls + 该轮 content/reasoning 切片，
      // 与流式路径 onAssistantToolCalls 语义对齐（流式用 streamingContent 累积重置，
      // 批量用 offset 切片，二者决策消息都带 content+reasoning 而非 content=null）
      const collectedDecisions: {
        tool_calls: OpenAICompatToolCall[]
        content: string | null
        reasoning: string | undefined
      }[] = []
      let decisionContentOffset = 0
      let decisionReasoningOffset = 0

      await agentApi.chatStream(
        agentId,
        {
          content,
          session_id: currentSessionId.value || null,
          llm_model: options?.llm_model || null,
          enable_thinking: options?.enable_thinking,
          stream: false,
          attachment_ids: options?.attachmentIds,
        },
        {
          signal: controller2.signal,
          onSession(d) {
            if (!currentSessionId.value) {
              currentSessionId.value = d.session_id
              conversations.value.unshift({
                id: 0,
                user_id: 0,
                agent_id: agentId,
                session_id: d.session_id,
                title: content.slice(0, 30),
                status: 'active',
                message_count: 1,
                total_tokens_used: 0,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              })
            }
          },
          onToolCall(d) {
            collectedToolCalls.push({
              toolName: d.tool_name,
              arguments: d.arguments,
              callId: d.call_id,
              status: 'running',
            })
          },
          onAssistantToolCalls(d) {
            // 按轮切片：该轮决策文本 = 自上次决策偏移以来的 content/reasoning
            const iterText = collectedContent.slice(decisionContentOffset)
            const iterReasoning = collectedReasoning.slice(decisionReasoningOffset)
            collectedDecisions.push({
              tool_calls: d.tool_calls as OpenAICompatToolCall[],
              content: iterText || null,
              reasoning: iterReasoning || undefined,
            })
            decisionContentOffset = collectedContent.length
            decisionReasoningOffset = collectedReasoning.length
          },
          onToolResult(d) {
            const call = collectedToolCalls.find((c) => c.callId === d.call_id)
            if (call) {
              call.status = d.status === 'completed' ? 'completed' : 'failed'
              call.result = d.result
              call.durationMs = d.duration_ms
            }
          },
          onReasoning(text) {
            collectedReasoning += text || ''
          },
          onContent(text) {
            collectedContent += text || ''
          },
          onSources(d) {
            collectedSources = d.sources as SourceRef[]
          },
          onDone(d) {
            // Apply collected data once
            toolCalls.value = collectedToolCalls

            // 先按序 push AI 决策消息（该轮 content + reasoning + extra.tool_calls），再 push 工具结果
            for (const dec of collectedDecisions) {
              const decisionMsg: AgentMessage = {
                id: Date.now() + Math.random(),
                conversation_id: 0,
                role: 'assistant',
                content: dec.content,
                tool_call_id: null,
                tool_name: null,
                token_count: null,
                created_at: new Date().toISOString(),
                reasoning: dec.reasoning,
                extra: { tool_calls: dec.tool_calls },
              }
              messages.value.push(decisionMsg)
            }

            for (const tc of collectedToolCalls) {
              const toolMsg: AgentMessage = {
                id: Date.now() + Math.random(),
                conversation_id: 0,
                role: 'tool',
                content: tc.result || null,
                tool_call_id: tc.callId,
                tool_name: tc.toolName,
                token_count: null,
                created_at: new Date().toISOString(),
              }
              messages.value.push(toolMsg)
            }

            // 最终回答 = 最后一轮（无工具调用）的 content/reasoning（自最后决策偏移切片）
            const finalText = collectedContent.slice(decisionContentOffset)
            const finalReasoning = collectedReasoning.slice(decisionReasoningOffset)
            const aiMsg: AgentMessage = {
              id: d.message_id || Date.now() + 1,
              conversation_id: 0,
              role: 'assistant',
              content: finalText,
              tool_call_id: null,
              tool_name: null,
              token_count: null,
              created_at: new Date().toISOString(),
              reasoning: finalReasoning || undefined,
              sources: d.sources || collectedSources,
            }
            messages.value.push(aiMsg)
            controller2.abort()
          },
          onCompaction(d) {
            messages.value.push({
              id: Date.now() + Math.random(),
              conversation_id: 0,
              role: 'compaction',
              content: null,
              tool_call_id: null,
              tool_name: null,
              token_count: null,
              created_at: d.created_at || new Date().toISOString(),
              extra: { compaction: d },
            })
          },
          onContextUsage(d) {
            contextUsage.value = d
          },
          onError(err) {
            error.value = err.content
          },
        },
      )
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : '发送失败'
      throw e
    } finally {
      loading.value = false
      abortController.value = null
    }
  }

  function cancelStream() {
    abortController.value?.abort()
  }

  function clearChat() {
    currentSessionId.value = null
    messages.value = []
    toolCalls.value = []
    streamingContent.value = ''
    streamingReasoning.value = ''
    streamingSources.value = []
    error.value = null
    pendingAttachments.value = []
    contextUsage.value = null
  }

  // ========== 附件管理 ==========

  async function uploadAttachment(
    file: File,
    onProgress?: (percent: number) => void,
  ): Promise<ChatAttachment> {
    const { chatApi } = await import('@/api/chat')
    const result = await chatApi.uploadAttachment(file, onProgress)
    const attachment: ChatAttachment = {
      id: result.attachment_id,
      filename: result.filename,
      file_type: result.file_type,
      file_size: result.file_size,
    }
    pendingAttachments.value.push(attachment)
    return attachment
  }

  function removePendingAttachment(attachmentId: number) {
    pendingAttachments.value = pendingAttachments.value.filter((a) => a.id !== attachmentId)
  }

  function clearPendingAttachments() {
    pendingAttachments.value = []
  }

  // ===================== MCP 服务器 =====================

  async function fetchMcpServers() {
    try {
      mcpServers.value = await agentApi.listMcpServers()
    } catch {
      mcpServers.value = []
    }
  }

  async function createMcpServer(data: Parameters<typeof agentApi.createMcpServer>[0]) {
    const server = await agentApi.createMcpServer(data)
    mcpServers.value.push(server)
    return server
  }

  async function updateMcpServer(
    serverId: number,
    data: Parameters<typeof agentApi.updateMcpServer>[1],
  ) {
    const updated = await agentApi.updateMcpServer(serverId, data)
    const idx = mcpServers.value.findIndex((s) => s.id === serverId)
    if (idx !== -1) mcpServers.value[idx] = updated
    return updated
  }

  async function deleteMcpServer(serverId: number) {
    await agentApi.deleteMcpServer(serverId)
    mcpServers.value = mcpServers.value.filter((s) => s.id !== serverId)
  }

  async function connectMcpServer(serverId: number) {
    const updated = await agentApi.connectMcpServer(serverId)
    const idx = mcpServers.value.findIndex((s) => s.id === serverId)
    if (idx !== -1) mcpServers.value[idx] = updated
  }

  async function disconnectMcpServer(serverId: number) {
    await agentApi.disconnectMcpServer(serverId)
    const server = mcpServers.value.find((s) => s.id === serverId)
    if (server) server.status = 'disconnected'
  }

  async function refreshMcpTools(serverId: number) {
    return await agentApi.refreshMcpTools(serverId)
  }

  // ===================== 工具 =====================

  async function fetchTools() {
    try {
      tools.value = await agentApi.listTools()
    } catch {
      tools.value = []
    }
  }

  // ===================== 初始化 =====================

  async function initForAgent(agentId: number) {
    await fetchAgent(agentId)
    await fetchConversations(agentId)
  }

  return {
    // State
    agents,
    agentsTotal,
    agentsLoading,
    currentAgent,
    conversations,
    conversationsTotal,
    conversationsLoading,
    currentSessionId,
    messages,
    messagesLoading,
    isStreaming,
    streamingContent,
    streamingReasoning,
    streamingSources,
    toolCalls,
    contextUsage,
    abortController,
    loading,
    mcpServers,
    tools,
    error,
    pendingAttachments,
    // Actions
    fetchAgents,
    fetchAgent,
    createAgent,
    updateAgent,
    deleteAgent,
    fetchConversations,
    fetchMessages,
    deleteConversation,
    sendMessage,
    sendMessageStream,
    cancelStream,
    clearChat,
    fetchMcpServers,
    createMcpServer,
    updateMcpServer,
    deleteMcpServer,
    connectMcpServer,
    disconnectMcpServer,
    refreshMcpTools,
    fetchTools,
    initForAgent,
    uploadAttachment,
    removePendingAttachment,
    clearPendingAttachments,
  }
})
