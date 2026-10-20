import { request, createWebSocketStream } from './index'
import type {
  AgentGroupDetail,
  AgentGroupListResponse,
  AgentGroupRun,
  CreateAgentGroupRequest,
  UpdateAgentGroupRequest,
  AgentMessageListResponse,
  GroupSpeakerData,
  GroupRunDoneData,
} from './types'

// ===================== 多智能体群聊 =====================

/**
 * 群聊 API
 *
 * 群 CRUD、群会话（每群单会话 get_or_create 语义）、时间线消息、
 * WS 一响对话流（bearer.<jwt> subprotocol 认证，协议与单聊一致）
 */
export const agentGroupApi = {
  /** 创建群聊（成员 ≥2；consult 模式 host_agent_id 必填且须在成员内） */
  createGroup(data: CreateAgentGroupRequest) {
    return request.post<AgentGroupDetail>('/agent/groups', data)
  },

  /** 我的群列表（created_at 倒序） */
  listGroups(params?: { limit?: number; offset?: number }) {
    return request.get<AgentGroupListResponse>('/agent/groups', params as Record<string, unknown>)
  },

  /** 群详情（含成员清单与编排参数） */
  getGroup(groupId: number) {
    return request.get<AgentGroupDetail>(`/agent/groups/${groupId}`)
  },

  /** 更新群（member_ids 传则全量替换成员） */
  updateGroup(groupId: number, data: UpdateAgentGroupRequest) {
    return request.put<AgentGroupDetail>(`/agent/groups/${groupId}`, data)
  },

  /** 解散群（成员私有会话保留） */
  deleteGroup(groupId: number) {
    return request.delete<{ success: boolean; message: string }>(`/agent/groups/${groupId}`)
  },

  /** 取/建群会话（每群单会话），返回时间线载体 session_id */
  createGroupSession(groupId: number) {
    return request.post<{ session_id: string }>(`/agent/groups/${groupId}/sessions`)
  },

  /** 群时间线消息（时间线投影：用户消息 + 成员公开发言） */
  getGroupMessages(groupId: number, sessionId: string) {
    return request.get<AgentMessageListResponse>(
      `/agent/groups/${groupId}/sessions/${sessionId}/messages`,
    )
  },

  /** 群运行历史（started_at 倒序） */
  listGroupRuns(groupId: number, params?: { limit?: number }) {
    return request.get<AgentGroupRun[]>(
      `/agent/groups/${groupId}/runs`,
      params as Record<string, unknown>,
    )
  },

  /**
   * 群 WS 一响对话流
   *
   * 事件在单聊事件集上扩展 group.speaker / group.run_done / notice；
   * content/reasoning/tool_* 等 data 带 member_agent_id/name 标记发言成员。
   * 停止讨论 = abort signal（WS 主动关闭），服务端 aclose 生成器把 run 置 cancelled。
   */
  groupChatStream(
    groupId: number,
    data: { content: string; session_id?: string | null },
    callbacks: {
      onSession?: (d: { session_id: string }) => void
      onSpeaker?: (d: GroupSpeakerData) => void
      onContent?: (text: string, memberId: number, name: string) => void
      onReasoning?: (text: string, memberId: number, name: string) => void
      onNotice?: (d: { content: string }) => void
      onRunDone?: (d: GroupRunDoneData) => void
      onError?: (err: { content: string }) => void
      signal?: AbortSignal
      /** 握手完成后的发送通道（运行中插话，P1 输入区禁用即不用） */
      onReady?: (send: (msg: unknown) => void) => void
    },
  ) {
    return createWebSocketStream(
      `/agent/groups/${groupId}/ws`,
      data,
      {
        onMessage(event) {
          const e = event as { type: string; data: Record<string, unknown> }
          const memberId = () => Number(e.data?.member_agent_id)
          const memberName = () => String(e.data?.name ?? '')
          switch (e.type) {
            case 'session':
              callbacks.onSession?.(e.data as { session_id: string })
              break
            case 'group.speaker':
              callbacks.onSpeaker?.(e.data as unknown as GroupSpeakerData)
              break
            case 'content':
              callbacks.onContent?.(
                String((e.data as { content?: string }).content ?? ''),
                memberId(),
                memberName(),
              )
              break
            case 'reasoning':
              callbacks.onReasoning?.(
                String((e.data as { content?: string }).content ?? ''),
                memberId(),
                memberName(),
              )
              break
            case 'notice':
              callbacks.onNotice?.(e.data as { content: string })
              break
            case 'group.run_done':
              callbacks.onRunDone?.(e.data as unknown as GroupRunDoneData)
              break
            case 'error':
              callbacks.onError?.(e.data as { content: string })
              break
          }
        },
        onError: callbacks.onError ? (msg) => callbacks.onError!({ content: msg }) : undefined,
        signal: callbacks.signal,
        onReady: callbacks.onReady,
      },
      'chat',
    )
  },
}
