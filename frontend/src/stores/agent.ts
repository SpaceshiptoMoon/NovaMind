import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { agentApi } from '@/api/agent'
import type {
  Agent,
  CreateAgentRequest,
  UpdateAgentRequest,
  AgentConversation,
  AgentMessage,
  McpServer,
  Skill,
  ToolCallRecord,
} from '@/api/types'

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
  const toolCalls = ref<ToolCallRecord[]>([])
  const abortController = ref<AbortController | null>(null)
  const loading = ref(false)

  // MCP & 技能（全局共享）
  const mcpServers = ref<McpServer[]>([])
  const skills = ref<Skill[]>([])
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

  async function sendMessageStream(agentId: number, content: string, options?: { llm_model?: string }) {
    if (!content.trim()) return

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
    }
    messages.value.push(userMsg)

    isStreaming.value = true
    streamingContent.value = ''
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
      await agentApi.chatStream(agentId, {
        content,
        session_id: currentSessionId.value || null,
        llm_model: options?.llm_model || null,
      }, {
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
            // assistant 已存在，插入到它前面
            messages.value.splice(assistantIndex, 0, toolMsg)
            assistantIndex++
          } else {
            // assistant 还没创建，直接追加
            messages.value.push(toolMsg)
          }
        },
        onToolResult(d) {
          const call = toolCalls.value.find((c) => c.callId === d.call_id)
          if (call) {
            call.status = d.status === 'completed' ? 'completed' : 'failed'
            call.result = d.result
            call.durationMs = d.duration_ms
          }

          const toolMsg = messages.value.find((m) => m.tool_call_id === d.call_id && m.role === 'tool')
          if (toolMsg) {
            toolMsg.content = d.result
          }
        },
        onContent(text) {
          streamingContent.value += text || ''
          ensureAssistant()
          assistantMsg!.content = streamingContent.value
        },
        onDone(d) {
          ensureAssistant()
          if (d.message_id) assistantMsg!.id = d.message_id
          if (!assistantMsg!.content) {
            assistantMsg!.content = streamingContent.value
          }
          controller.abort()
        },
        onError(err) {
          error.value = err.content
          ensureAssistant()
          if (!assistantMsg!.content) {
            assistantMsg!.content = `[错误] ${err.content}`
          }
        },
      })
    } catch (e) {
      if (assistantMsg && !assistantMsg.content) {
        const idx = messages.value.indexOf(assistantMsg)
        if (idx !== -1) messages.value.splice(idx, 1)
      }
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : '发送失败'
      throw e
    } finally {
      isStreaming.value = false
      streamingContent.value = ''
      abortController.value = null
    }
  }

  // ===================== 非流式对话 =====================

  async function sendMessage(agentId: number, content: string, options?: { llm_model?: string }) {
    if (!content.trim()) return

    const userMsg: AgentMessage = {
      id: Date.now(),
      conversation_id: 0,
      role: 'user',
      content,
      tool_call_id: null,
      tool_name: null,
      token_count: null,
      created_at: new Date().toISOString(),
    }
    messages.value.push(userMsg)

    loading.value = true
    toolCalls.value = []
    error.value = null

    const controller2 = new AbortController()
    abortController.value = controller2

    try {
      let collectedContent = ''
      const collectedToolCalls: ToolCallRecord[] = []

      await agentApi.chatStream(agentId, {
        content,
        session_id: currentSessionId.value || null,
        llm_model: options?.llm_model || null,
      }, {
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
        onToolResult(d) {
          const call = collectedToolCalls.find((c) => c.callId === d.call_id)
          if (call) {
            call.status = d.status === 'completed' ? 'completed' : 'failed'
            call.result = d.result
            call.durationMs = d.duration_ms
          }
        },
        onContent(text) {
          collectedContent += text || ''
        },
        onDone(d) {
          // Apply collected data once
          toolCalls.value = collectedToolCalls

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

          const aiMsg: AgentMessage = {
            id: d.message_id || Date.now() + 1,
            conversation_id: 0,
            role: 'assistant',
            content: collectedContent,
            tool_call_id: null,
            tool_name: null,
            token_count: null,
            created_at: new Date().toISOString(),
          }
          messages.value.push(aiMsg)
          controller2.abort()
        },
        onError(err) {
          error.value = err.content
        },
      })
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
    error.value = null
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

  async function updateMcpServer(serverId: number, data: Parameters<typeof agentApi.updateMcpServer>[1]) {
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

  // ===================== 技能 =====================

  async function fetchSkills() {
    try {
      skills.value = await agentApi.listSkills()
    } catch {
      skills.value = []
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
    toolCalls,
    abortController,
    loading,
    mcpServers,
    skills,
    error,
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
    fetchSkills,
    initForAgent,
  }
})
