/**
 * Agent CRUD slice（纯搬移自 stores/agent.ts）
 *
 * createAgentState() 自包含；initForAgent 跨聊天域（清聊天态 + 重拉会话列表），
 * 依赖经参数注入保持原句逐字。
 */
import { ref } from 'vue'
import { agentApi } from '@/api/agent'
import type { Agent, CreateAgentRequest, UpdateAgentRequest } from '@/api/types'
import type { ChatState } from './chatSlice'

/** 创建 Agent CRUD 域状态与操作（在 store setup 内调用一次） */
export function createAgentsState() {
  // Agent 列表
  const agents = ref<Agent[]>([])
  const agentsTotal = ref(0)
  const agentsLoading = ref(false)

  // 当前 Agent
  const currentAgent = ref<Agent | null>(null)

  /** 拉取 Agent 列表（支持分页），失败时清空列表 */
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

  /** 删除 Agent；若删的是当前 Agent，同步清空会话状态 */
  async function deleteAgent(agentId: number, clearChat: ChatState['clearChat']) {
    await agentApi.deleteAgent(agentId)
    agents.value = agents.value.filter((a) => a.id !== agentId)
    agentsTotal.value -= 1
    if (currentAgent.value?.id === agentId) {
      currentAgent.value = null
      clearChat()
    }
  }

  return {
    agents,
    agentsTotal,
    agentsLoading,
    currentAgent,
    fetchAgents,
    fetchAgent,
    createAgent,
    updateAgent,
    deleteAgent,
  }
}

/**
 * 初始化入口（纯搬移）：进入某 Agent 聊天页时拉 Agent 详情 + 会话列表。
 * 独立工厂函数——依赖 chat 域的 clearChat/fetchConversations 经参数注入。
 */
export function createInitForAgent(
  agents: ReturnType<typeof createAgentsState>,
  chat: Pick<ChatState, 'clearChat' | 'fetchConversations'>,
) {
  /** 进入某 Agent 聊天页的入口：拉 Agent 详情 + 会话列表 */
  async function initForAgent(agentId: number) {
    // 切换智能体必须先清聊天态：currentSessionId 归属上一个 agent，残留时发消息
    // 会把旧会话 ID 传给新 agent（后端 500「会话不存在」）；messages 残留则串台显示
    // 上一个 agent 的历史。同 agent 重进也只需重拉列表，清态无副作用。
    chat.clearChat()
    await agents.fetchAgent(agentId)
    await chat.fetchConversations(agentId)
  }
  return { initForAgent }
}

/** 包装 deleteAgent：注入 chat.clearChat 后的调用形态（store 内组合） */
export function bindDeleteAgent(
  agents: ReturnType<typeof createAgentsState>,
  clearChat: ChatState['clearChat'],
) {
  return (agentId: number) => agents.deleteAgent(agentId, clearChat)
}
