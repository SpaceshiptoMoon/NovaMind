/**
 * 聊天域 slice（纯搬移自 stores/agent.ts）：会话列表 + 消息 + SSE 流式 +
 * 断连续跑轮询（turn-state）+ 审批卡 + 运行中插话。
 *
 * 这是一个内聚状态机（流式回调/轮询/审批通道互相引用），整体拆出；
 * 跨域依赖仅 clearPendingAttachments（发消息成功后清待发队列）。
 */
import { ref } from 'vue'
import { agentApi } from '@/api/agent'
import type {
  AgentConversation,
  AgentMessage,
  OpenAICompatToolCall,
  SourceRef,
  ToolCallRecord,
} from '@/api/types'
import {
  applyPlanEvent,
  applyResearchProgress,
  normalizeToolStatus,
} from './pureHelpers'
import type { AttachmentState } from './attachmentSlice'

/**
 * 创建聊天域状态与操作（在 store setup 内调用一次）。
 *
 * Args:
 *   pendingAttachments: 附件待发队列 ref（attachment slice 提供；消息 extra
 *     快照与 clearChat 清队列直接读写它，保持原句逐字）。
 *   clearPendingAttachments: 发送成功后清空附件待发队列（同上）。
 */
export function createChatState({
  pendingAttachments,
  clearPendingAttachments,
}: Pick<AttachmentState, 'pendingAttachments' | 'clearPendingAttachments'>) {
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
  const contextUsage = ref<import('@/api/types').AgentContextUsageData | null>(null)
  const abortController = ref<AbortController | null>(null)
  // 当前 plan 消息引用（Plan-and-Execute 模式，onPlan 聚合 step 状态用）
  const planMsg = ref<AgentMessage | null>(null)
  // 当前深度研究进度消息引用（批3 research 工具，onResearchProgress 原地推进用）
  const researchMsg = ref<AgentMessage | null>(null)
  // E5 异步审批请求（危险代码执行前等用户决策）：瞬时态，120s 后端超时按 deny
  // fail-closed；不入消息流（不落库无回放语义），会话结束/清理时一并置空
  const pendingApproval = ref<import('@/api/types').ApprovalRequestData | null>(null)
  const error = ref<string | null>(null)

  // 运行中插话发送通道（sendMessageStream 的 onReady 注入；连接结束在 finally 置空）
  let wsSendRef: ((msg: unknown) => void) | null = null
  // 审批附着通道（action=attach）：无在途流时向后台续跑轮次回传审批决策
  let attachChannel: { close: () => void } | null = null
  let attachSendRef: ((msg: unknown) => void) | null = null
  // 断连后台续跑状态（turn-state 轮询驱动）
  const backgroundRunning = ref(false)
  let turnPollTimer: number | null = null

  // ===================== 对话管理 =====================

  /** 拉取 Agent 的会话列表；带 offset 时追加（翻页），否则整体替换 */
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

  /** 拉取某会话的历史消息，并从持久化工具调用重建 toolCalls 与上下文用量仪表 */
  async function fetchMessages(sessionId: string) {
    messagesLoading.value = true
    error.value = null
    try {
      const data = await agentApi.getMessages(sessionId)
      // extra.sources → sources 展开：落库形态把引用挂在 extra 里，运行中 SSE
      // 则写顶层 sources（sendMessageStream），两态统一成顶层字段供引用面板聚合
      messages.value = (data.items || []).map((m) => ({
        ...m,
        sources: m.extra?.sources as SourceRef[] | undefined,
      }))
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

  /** 删除会话；若删的是当前会话，清空聊天区 */
  async function deleteConversation(sessionId: string) {
    await agentApi.deleteSession(sessionId)
    conversations.value = conversations.value.filter((c) => c.session_id !== sessionId)
    if (currentSessionId.value === sessionId) {
      clearChat()
    }
  }

  // ===================== SSE 流式对话 =====================

  /**
   * 流式发送消息并按事件增量渲染：正文/思考流式累积、工具卡片插到当前决策消息之后、
   * 计划卡按 plan.* 事件原位更新状态。多轮工具调用时每轮决策文本单独成消息，最终回答取最后一轮。
   */
  async function sendMessageStream(
    agentId: number,
    content: string,
    options?: { llm_model?: string; enable_thinking?: boolean; deep_research?: boolean; attachmentIds?: number[] },
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
    planMsg.value = null
    researchMsg.value = null

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
          deep_research: options?.deep_research,
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
          onResearchProgress(d) {
            applyResearchProgress(researchMsg, messages.value, d)
          },
          onPlan(type, d) {
            const created = applyPlanEvent(planMsg, messages.value, type, d)
            if (created) return
            // plan.completed：最终气泡显示总结（与后端落库口径一致——外层 done 的
            // full_response 即 summary，而非最后一步的结论文本）
            if (type === 'plan.completed' && d.summary) {
              ensureAssistant()
              assistantMsg!.content = d.summary
            }
          },
          onLoopWarning(d) {
            messages.value.push({
              id: Date.now() + Math.random(),
              conversation_id: 0,
              role: 'notice',
              content: d.content,
              tool_call_id: null,
              tool_name: null,
              token_count: null,
              created_at: new Date().toISOString(),
              extra: { notice: true, iteration: d.iteration },
            })
          },
          onSteering(d) {
            // 运行中插话已被引擎注入：本地同步 push user 气泡（后端已落库，
            // 刷新后历史回放同样可见）
            messages.value.push({
              id: Date.now() + Math.random(),
              conversation_id: 0,
              role: 'user',
              content: d.content,
              tool_call_id: null,
              tool_name: null,
              token_count: null,
              created_at: new Date().toISOString(),
              extra: { steering: true, iteration: d.iteration },
            })
          },
          onError(err) {
            error.value = err.content
            ensureAssistant()
            if (!assistantMsg!.content) {
              assistantMsg!.content = `[错误] ${err.content}`
            }
          },
          // E5 审批请求：危险代码执行前等用户决策（卡片由视图层渲染）
          onApprovalRequest(d) {
            pendingApproval.value = d
          },
          // 握手完成后保存发送通道，供 steer()/respondApproval() 回传决策与插话
          onReady(send) {
            wsSendRef = send
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
      wsSendRef = null
      pendingApproval.value = null
      // 本轮结束：后台续跑状态与附着通道一并清理（新流自带审批通道）
      backgroundRunning.value = false
      stopTurnPoll()
      attachChannel?.close()
      attachChannel = null
      attachSendRef = null
    }
  }

  /**
   * 运行中插话（steering）：agent 流式执行期间把用户消息发给后端，
   * 在下一轮 ReAct 迭代顶部注入上下文。仅流式路径可用（wsSendRef 由
   * sendMessageStream 的 onReady 注入）；非流式或空闲时返回 false。
   */
  function steer(content: string): boolean {
    const text = content.trim()
    if (!text || !wsSendRef) return false
    wsSendRef({ action: 'message', content: text })
    return true
  }

  /**
   * E5 审批决策回传：批准/拒绝危险代码执行。仅流式路径可用（wsSendRef 约束同
   * steer）；决策发出即清卡片（后端 120s 超时按 deny 兜底，无需前端计时清理状态）。
   */
  function respondApproval(approvalId: string, decision: 'approve' | 'deny'): boolean {
    // 在途流用其发送通道；否则走审批附着通道（detach 轮次的重连恢复场景）
    const send = wsSendRef || attachSendRef
    if (!send || !pendingApproval.value) return false
    send({ action: 'approval', approval_id: approvalId, decision })
    pendingApproval.value = null
    return true
  }

  /** 中止当前流式请求：显式停止（先发 action=stop，后端按取消回滚而非后台续跑） */
  function cancelStream() {
    wsSendRef?.({ action: 'stop' })
    abortController.value?.abort()
  }

  /**
   * 静默断开（切会话等场景）：不发 stop——异常断连触发后端 detach 转后台续跑，
   * 轮次继续执行落库，切回会话时经 turn-state 轮询恢复进度。
   */
  function abortStreamSilently() {
    abortController.value?.abort()
  }

  function stopTurnPoll() {
    if (turnPollTimer !== null) {
      window.clearInterval(turnPollTimer)
      turnPollTimer = null
    }
  }

  /** 审批附着通道：无在途流时打开 action=attach 连接，决策经此回传后台轮次 */
  function openAttachForApproval(agentId: number) {
    if (attachChannel) return
    attachChannel = agentApi.openApprovalChannel(agentId, (send) => {
      attachSendRef = send
    })
  }

  /**
   * 查询当前会话轮次状态（进入会话/切换会话时调用）：后台运行中 → 启动轮询
   * （3s 周期刷新消息回放直至终态）；待审批 → 恢复审批卡并打开附着通道。
   */
  async function checkTurnState(agentId: number) {
    const sid = currentSessionId.value
    if (!sid || isStreaming.value) return
    try {
      const state = await agentApi.fetchTurnState(sid)
      backgroundRunning.value = state.running_turn
      if (state.pending_approval && !pendingApproval.value) {
        pendingApproval.value = state.pending_approval
        openAttachForApproval(agentId)
      }
      if (state.running_turn) {
        stopTurnPoll()
        turnPollTimer = window.setInterval(async () => {
          const pollSid = currentSessionId.value
          if (!pollSid) {
            stopTurnPoll()
            return
          }
          try {
            const poll = await agentApi.fetchTurnState(pollSid)
            if (poll.pending_approval && !pendingApproval.value && !isStreaming.value) {
              pendingApproval.value = poll.pending_approval
              openAttachForApproval(agentId)
            }
            if (!poll.running_turn) {
              stopTurnPoll()
              backgroundRunning.value = false
              await fetchMessages(pollSid)
            }
          } catch {
            /* 网络抖动忽略，下轮再试 */
          }
        }, 3000)
      }
    } catch {
      /* 会话不存在/网络失败静默 */
    }
  }

  /** 清空整个聊天状态（会话 ID、消息、工具卡、流式累积、附件、计划卡），切会话/删 Agent 时调用 */
  function clearChat() {
    // 在途流静默断开（不发 stop）：断连触发后端 detach 转后台续跑；流回调停止
    // 后旧会话增量不再写进 store（切会话语义），切回时经 turn-state 轮询恢复
    if (isStreaming.value) abortStreamSilently()
    stopTurnPoll()
    backgroundRunning.value = false
    attachChannel?.close()
    attachChannel = null
    attachSendRef = null
    currentSessionId.value = null
    messages.value = []
    toolCalls.value = []
    streamingContent.value = ''
    streamingReasoning.value = ''
    streamingSources.value = []
    error.value = null
    pendingAttachments.value = []
    contextUsage.value = null
    planMsg.value = null
    researchMsg.value = null
    pendingApproval.value = null
  }

  return {
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
    planMsg,
    researchMsg,
    pendingApproval,
    error,
    backgroundRunning,
    fetchConversations,
    fetchMessages,
    deleteConversation,
    sendMessageStream,
    steer,
    respondApproval,
    cancelStream,
    abortStreamSilently,
    checkTurnState,
    clearChat,
  }
}

export type ChatState = ReturnType<typeof createChatState>
