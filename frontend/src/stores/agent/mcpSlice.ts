/**
 * MCP 服务器 & 工具注册表 slice（纯搬移自 stores/agent.ts）
 *
 * 状态完全独立（mcpServers/tools），不依赖聊天域——拆为自包含 slice。
 */
import { ref } from 'vue'
import { agentApi } from '@/api/agent'
import type { McpServer, ToolProvider } from '@/api/types'

/** 创建 MCP 域状态与操作（在 store setup 内调用一次） */
export function createMcpState() {
  // MCP & 工具（全局共享）
  const mcpServers = ref<McpServer[]>([])
  const tools = ref<ToolProvider[]>([])

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

  async function fetchTools() {
    try {
      tools.value = await agentApi.listTools()
    } catch {
      tools.value = []
    }
  }

  return {
    mcpServers,
    tools,
    fetchMcpServers,
    createMcpServer,
    updateMcpServer,
    deleteMcpServer,
    connectMcpServer,
    disconnectMcpServer,
    refreshMcpTools,
    fetchTools,
  }
}

export type McpState = ReturnType<typeof createMcpState>
