import { ref } from 'vue'
import { defineStore } from 'pinia'
import { agentGroupApi } from '@/api/agentGroup'
import type {
  AgentGroup,
  AgentGroupDetail,
  AgentMessage,
  GroupTimelineEntry,
  GroupSession,
  GroupSpeakerData,
  GroupToolStep,
} from '@/api/types'

/**
 * 群聊 store：群列表/当前群/群会话列表/时间线/一响运行态
 *
 * 与单聊 agent store 并列不合并（领域边界）；一群可开多个会话
 * （session），时间线按当前会话加载，切换会话即重放。WS 连接生命周期
 * 挂在 sendGroupMessage 的 await 区间内，run 结束（run_done/断连）自动收尾。
 */
export const useAgentGroupStore = defineStore('agentGroup', () => {
  const groups = ref<AgentGroup[]>([])
  const groupsLoading = ref(false)
  const currentGroup = ref<AgentGroupDetail | null>(null)
  // 当前群的会话列表与当前会话（时间线按会话隔离）
  const sessions = ref<GroupSession[]>([])
  const sessionsLoading = ref(false)
  const currentSessionId = ref<string | null>(null)
  const timeline = ref<GroupTimelineEntry[]>([])
  const timelineLoading = ref(false)

  // 一响运行态：running 期间输入禁用，currentSpeaker 驱动状态条与气泡 spinner
  const running = ref(false)
  const currentSpeaker = ref<GroupSpeakerData | null>(null)
  const abortController = ref<AbortController | null>(null)
  const error = ref<string | null>(null)

  async function fetchGroups() {
    groupsLoading.value = true
    try {
      const data = await agentGroupApi.listGroups()
      groups.value = data.items || []
    } finally {
      groupsLoading.value = false
    }
  }

  /** 进群入口：拉群详情 + 会话列表 + 回放默认（最新）会话时间线 */
  async function initForGroup(groupId: number) {
    timelineLoading.value = true
    error.value = null
    try {
      const detail = await agentGroupApi.getGroup(groupId)
      currentGroup.value = detail
      await fetchSessions(groupId)
      const latest = sessions.value[0]
      if (latest) {
        await selectSession(latest.session_id)
      } else {
        // 群还没有任何会话：先建一个（首次进群的引导路径）
        const conv = await agentGroupApi.createGroupSession(groupId)
        sessions.value = [conv]
        currentSessionId.value = conv.session_id
        timeline.value = []
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载群聊失败'
    } finally {
      timelineLoading.value = false
    }
  }

  /** 拉当前群的会话列表（id 倒序=最新在前） */
  async function fetchSessions(groupId: number) {
    sessionsLoading.value = true
    try {
      const data = await agentGroupApi.listGroupSessions(groupId)
      sessions.value = data.items || []
    } finally {
      sessionsLoading.value = false
    }
  }

  /** 切换会话：重放该会话时间线（切换前封口运行中的讨论） */
  async function selectSession(sessionId: string) {
    if (running.value) stopRun()
    currentSessionId.value = sessionId
    timelineLoading.value = true
    try {
      await replayTimeline(currentGroup.value!.id, sessionId)
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载会话失败'
    } finally {
      timelineLoading.value = false
    }
  }

  /** 新开会话：显式 POST（后端不复用不回退），并切换过去 */
  async function newSession() {
    const group = currentGroup.value
    if (!group) return
    const conv = await agentGroupApi.createGroupSession(group.id)
    sessions.value = [conv, ...sessions.value]
    await selectSession(conv.session_id)
  }

  /** 删除会话；删的是当前会话时切到列表首个（无会话则建新的） */
  async function deleteSession(sessionId: string) {
    const group = currentGroup.value
    if (!group) return
    await agentGroupApi.deleteGroupSession(group.id, sessionId)
    sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
      timeline.value = []
      const next = sessions.value[0]
      if (next) {
        await selectSession(next.session_id)
      } else {
        await newSession()
      }
    }
  }

  /** 历史回放：把群会话消息映射成时间线条目（成员发言按 extra.member_agent_id 分派） */
  async function replayTimeline(groupId: number, sessionId: string) {
    const data = await agentGroupApi.getGroupMessages(groupId, sessionId)
    timeline.value = (data.items || []).map((m: AgentMessage) => toEntry(m))
  }

  function toEntry(m: AgentMessage): GroupTimelineEntry {
    if (m.role === 'user') {
      return { kind: 'user', content: m.content || '', created_at: m.created_at }
    }
    const extra = (m.extra || {}) as Record<string, unknown>
    if (extra.error === true) {
      return {
        kind: 'notice',
        content: m.content || '',
        isError: true,
        created_at: m.created_at,
      }
    }
    // 历史回放过程档案（extra.process）：复原工具卡与思考折叠区，
    // 与实时流式路径的条目形状一致（streaming 不置位，卡片即终态）
    const process = (extra.process || {}) as {
      tools?: Array<{
        call_id?: string
        tool_name?: string
        arguments?: Record<string, unknown>
        result?: string
        status?: string
      }>
      reasoning?: string
    }
    return {
      kind: 'member',
      member_agent_id: Number(extra.member_agent_id ?? 0),
      name: String(extra.name ?? '成员'),
      content: m.content || '',
      reasoning: process.reasoning || undefined,
      toolCalls: (process.tools || []).map((t) => ({
        callId: t.call_id || '',
        name: t.tool_name || '',
        arguments: t.arguments,
        result: t.result,
        status: t.status === 'failed' ? 'failed' : 'completed',
      })),
      created_at: m.created_at,
    }
  }

  /**
   * 发起一响讨论：落用户消息 → WS 事件流增量渲染时间线
   *
   * 成员发言条目按 member_agent_id 复用（流式内容直拼）；头脑风暴为并行
   * 模式，多成员事件交错到达，发言中条目按 memberId 各持一个（Map 复用）；
   * run_done/断连统一收尾解锁输入。
   */
  async function sendGroupMessage(content: string) {
    const group = currentGroup.value
    if (!group || running.value || !content.trim()) return

    timeline.value.push({ kind: 'user', content, created_at: new Date().toISOString() })
    running.value = true
    currentSpeaker.value = null
    error.value = null

    // 发言中条目按 memberId 各持一个：并行成员事件交错，单变量会串条目
    const activeEntries = new Map<number, GroupTimelineEntry>()

    const controller = new AbortController()
    abortController.value = controller

    function ensureEntry(memberId: number, name: string): GroupTimelineEntry {
      const existing = activeEntries.get(memberId)
      if (existing) return existing
      timeline.value.push({
        kind: 'member',
        member_agent_id: memberId,
        name,
        content: '',
        reasoning: '',
        toolCalls: [],
        streaming: true,
        created_at: new Date().toISOString(),
      })
      // 从数组取回 reactive proxy 再持有：改原始对象绕过 proxy 不触发渲染，
      // 流式内容与 streaming 收尾都会静默失效（气泡空白+spinner 卡死）
      const entry = timeline.value[timeline.value.length - 1] as GroupTimelineEntry
      activeEntries.set(memberId, entry)
      return entry
    }

    /** 工具步骤按 (callId) 在当前发言条目内配对累积（callId 引擎内全局唯一） */
    function upsertToolStep(
      entry: GroupTimelineEntry,
      callId: string,
      patch: Partial<GroupToolStep>,
    ) {
      entry.toolCalls = entry.toolCalls || []
      let step = entry.toolCalls.find((t) => t.callId === callId)
      if (!step) {
        step = { callId, name: '', status: 'running' }
        entry.toolCalls.push(step)
      }
      Object.assign(step, patch)
    }

    try {
      await agentGroupApi.groupChatStream(
        group.id,
        { content, session_id: currentSessionId.value },
        {
          signal: controller.signal,
          onSession(d) {
            if (!currentSessionId.value) currentSessionId.value = d.session_id
          },
          onSpeaker(d) {
            currentSpeaker.value = d
          },
          onContent(text, memberId, name) {
            ensureEntry(memberId, name).content += text
          },
          onReasoning(text, memberId, name) {
            // 思考流独立累积（气泡内折叠区展示，不与正文混流）
            const entry = ensureEntry(memberId, name)
            entry.reasoning = (entry.reasoning || '') + text
          },
          onToolCall(d, memberId, name) {
            upsertToolStep(ensureEntry(memberId, name), d.call_id, {
              name: d.tool_name,
              arguments: d.arguments,
              status: 'running',
            })
          },
          onToolResult(d, memberId, name) {
            upsertToolStep(ensureEntry(memberId, name), d.call_id, {
              result: d.full_result ?? d.result,
              status: d.status === 'failed' ? 'failed' : 'completed',
            })
          },
          onNotice(d) {
            timeline.value.push({
              kind: 'notice',
              content: d.content,
              created_at: new Date().toISOString(),
            })
          },
          onRunDone() {
            controller.abort()
          },
          onError(err) {
            error.value = err.content
            controller.abort()
          },
          onReady() {
            // 运行中插话通道：P1 输入区禁用，不消费
          },
        },
      )
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) {
        error.value = e instanceof Error ? e.message : '发送失败'
      }
    } finally {
      // 收尾全部发言中条目（并行交错：可能多条同时在流式）
      for (const entry of activeEntries.values()) entry.streaming = false
      running.value = false
      currentSpeaker.value = null
      abortController.value = null
    }
  }

  /** 停止讨论：主动断 WS，服务端 aclose 把 run 置 cancelled */
  function stopRun() {
    abortController.value?.abort()
  }

  /** 切群/离开时清运行时状态（群列表数据保留） */
  function clearChat() {
    abortController.value?.abort()
    currentGroup.value = null
    sessions.value = []
    currentSessionId.value = null
    timeline.value = []
    running.value = false
    currentSpeaker.value = null
    error.value = null
  }

  async function deleteGroup(groupId: number) {
    await agentGroupApi.deleteGroup(groupId)
    groups.value = groups.value.filter((g) => g.id !== groupId)
    if (currentGroup.value?.id === groupId) {
      clearChat()
    }
  }

  /** CRUD 后刷新当前群详情（编辑/成员变更回显） */
  async function refreshCurrentGroup() {
    if (currentGroup.value) {
      currentGroup.value = await agentGroupApi.getGroup(currentGroup.value.id)
    }
  }

  return {
    groups,
    groupsLoading,
    currentGroup,
    sessions,
    sessionsLoading,
    currentSessionId,
    timeline,
    timelineLoading,
    running,
    currentSpeaker,
    error,
    fetchGroups,
    initForGroup,
    fetchSessions,
    selectSession,
    newSession,
    deleteSession,
    sendGroupMessage,
    stopRun,
    clearChat,
    deleteGroup,
    refreshCurrentGroup,
  }
})
