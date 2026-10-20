import { ref } from 'vue'
import { defineStore } from 'pinia'
import { agentGroupApi } from '@/api/agentGroup'
import type {
  AgentGroup,
  AgentGroupDetail,
  AgentMessage,
  GroupTimelineEntry,
  GroupSpeakerData,
} from '@/api/types'

/**
 * 群聊 store：群列表/当前群/时间线/一响运行态
 *
 * 与单聊 agent store 并列不合并（领域边界）；WS 连接生命周期挂在
 * sendGroupMessage 的 await 区间内，run 结束（run_done/断连）自动收尾。
 */
export const useAgentGroupStore = defineStore('agentGroup', () => {
  const groups = ref<AgentGroup[]>([])
  const groupsLoading = ref(false)
  const currentGroup = ref<AgentGroupDetail | null>(null)
  // 每群单会话（get_or_create 语义）：时间线载体
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

  /** 进群入口：拉详情 + 取/建群会话 + 回放时间线 */
  async function initForGroup(groupId: number) {
    timelineLoading.value = true
    error.value = null
    try {
      const [detail, conv] = await Promise.all([
        agentGroupApi.getGroup(groupId),
        agentGroupApi.createGroupSession(groupId),
      ])
      currentGroup.value = detail
      currentSessionId.value = conv.session_id
      await replayTimeline(groupId, conv.session_id)
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载群聊失败'
    } finally {
      timelineLoading.value = false
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
    return {
      kind: 'member',
      member_agent_id: Number(extra.member_agent_id ?? 0),
      name: String(extra.name ?? '成员'),
      content: m.content || '',
      created_at: m.created_at,
    }
  }

  /**
   * 发起一响讨论：落用户消息 → WS 事件流增量渲染时间线
   *
   * 成员发言条目按 member_agent_id 复用（流式内容直拼）；group.speaker 切换
   * currentSpeaker；run_done/断连统一收尾解锁输入。
   */
  async function sendGroupMessage(content: string) {
    const group = currentGroup.value
    if (!group || running.value || !content.trim()) return

    timeline.value.push({ kind: 'user', content, created_at: new Date().toISOString() })
    running.value = true
    currentSpeaker.value = null
    error.value = null

    // 发言中条目：首个 content 事件到达时建（member 条目按 agent_id 复用）
    let activeEntry: GroupTimelineEntry | null = null

    const controller = new AbortController()
    abortController.value = controller

    function ensureEntry(memberId: number, name: string) {
      if (activeEntry && activeEntry.member_agent_id === memberId) return
      timeline.value.push({
        kind: 'member',
        member_agent_id: memberId,
        name,
        content: '',
        streaming: true,
        created_at: new Date().toISOString(),
      })
      // 从数组取回 reactive proxy 再持有：改原始对象绕过 proxy 不触发渲染，
      // 流式内容与 streaming 收尾都会静默失效（气泡空白+spinner 卡死）
      activeEntry = timeline.value[timeline.value.length - 1] as GroupTimelineEntry
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
            // 封口上一条流式条目再切换：只置 null 会让旧条目永远「正在发言」
            if (activeEntry) activeEntry.streaming = false
            currentSpeaker.value = d
            activeEntry = null
            ensureEntry(d.member_agent_id, d.name)
          },
          onContent(text, memberId, name) {
            ensureEntry(memberId, name)
            activeEntry!.content += text
          },
          onNotice(d) {
            if (activeEntry) activeEntry.streaming = false
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
      // activeEntry 在闭包 ensureEntry 中赋值，TS 在 finally 分支窄化为 never；
      // 用 as 断言重置窄化类型（与单聊 store 的 assistantMsg 同坑）
      const pendingEntry = activeEntry as GroupTimelineEntry | null
      if (pendingEntry) pendingEntry.streaming = false
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
    currentSessionId,
    timeline,
    timelineLoading,
    running,
    currentSpeaker,
    error,
    fetchGroups,
    initForGroup,
    sendGroupMessage,
    stopRun,
    clearChat,
    deleteGroup,
    refreshCurrentGroup,
  }
})
