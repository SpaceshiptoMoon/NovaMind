/**
 * Agent 会话 store（2026-11-15 slice 化重组，对外接口不变）
 *
 * 组合各域 slice（纯搬移自原单文件）：Agent CRUD / 聊天域（会话+消息+流式+
 * 断连续跑轮询+审批）/ 附件待发队列 / MCP 与工具注册表。
 * `@/stores/agent` import 路径解析到本 index.ts，全仓调用方零改动。
 */
import { defineStore } from 'pinia'
import { createAttachmentState } from './attachmentSlice'
import { createChatState } from './chatSlice'
import { bindDeleteAgent, createAgentsState, createInitForAgent } from './crudSlice'
import { createMcpState } from './mcpSlice'

export const useAgentStore = defineStore('agent', () => {
  const mcp = createMcpState()
  const attachments = createAttachmentState()
  const chat = createChatState({
    pendingAttachments: attachments.pendingAttachments,
    clearPendingAttachments: attachments.clearPendingAttachments,
  })
  const agents = createAgentsState()
  const init = createInitForAgent(agents, chat)

  return {
    // State（聚合各 slice）
    ...agents,
    ...chat,
    ...attachments,
    ...mcp,
    // Actions
    ...init,
    deleteAgent: bindDeleteAgent(agents, chat.clearChat),
  }
})
