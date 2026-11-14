/**
 * Agent chat 纯函数助手（纯搬移自 stores/agent.ts）
 *
 * plan/research 事件的消息构造与状态推进，零 store 状态依赖——流式与
 * 非流式两路共用。
 */
import type {
  AgentMessage,
  PlanData,
  ResearchProgressData,
  ToolCallRecord,
} from '@/api/types'

// 后端工具状态归并到前端 ToolCallRecord.status 四态
// pending/running → running；completed → completed；failed/timeout/其它 → failed
/** 把后端工具状态字符串归并为前端三态（running/completed/failed） */
export function normalizeToolStatus(status: string): ToolCallRecord['status'] {
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

/** plan.created 时构造的 extra.plan 初始形状 */
export interface PlanExtra {
  title: string
  steps: string[]
  statuses: string[]
  summary?: string
  interrupted?: boolean
}

/**
 * plan.* 事件统一处理（流式/非流式两路共用）：
 * created 建 role='plan' 消息（statuses 初始化 not_started）；
 * step_started/step_completed/step_failed 推进 statuses；
 * completed 写 summary + interrupted。
 * 返回是否处理了 plan.created（调用方据此把 summary 写进最终气泡）。
 */
export function applyPlanEvent(
  planMsg: { value: AgentMessage | null },
  messages: AgentMessage[],
  type: string,
  d: PlanData,
): boolean {
  if (type === 'plan.created') {
    const steps = d.steps || []
    const msg: AgentMessage = {
      id: Date.now() + Math.random(),
      conversation_id: 0,
      role: 'plan',
      content: d.title || null,
      tool_call_id: null,
      tool_name: null,
      token_count: null,
      created_at: new Date().toISOString(),
      extra: {
        plan: {
          title: d.title || '',
          steps,
          statuses: steps.map(() => 'not_started'),
        } satisfies PlanExtra,
      },
    }
    messages.push(msg)
    planMsg.value = msg
    return true
  }
  if (!planMsg.value) return false
  const plan = (planMsg.value.extra as { plan?: PlanExtra } | null)?.plan
  if (!plan?.statuses) return false
  if (type === 'plan.step_started' && d.step_index != null) {
    plan.statuses[d.step_index] = 'in_progress'
  } else if (type === 'plan.step_completed' && d.step_index != null) {
    plan.statuses[d.step_index] = 'completed'
  } else if (type === 'plan.step_failed' && d.step_index != null) {
    plan.statuses[d.step_index] = 'blocked'
  } else if (type === 'plan.completed') {
    if (d.summary) plan.summary = d.summary
    plan.interrupted = !!d.interrupted
  }
  return false
}

/**
 * research_progress 事件统一处理（批3 深度研究工具化）：
 * 首个事件建 role='research' 消息（extra.research 存进度态），后续事件原地
 * 更新同一条消息——研究耗时数分钟，进度一条消息内推进而非刷屏。
 */
export function applyResearchProgress(
  researchMsg: { value: AgentMessage | null },
  messages: AgentMessage[],
  d: ResearchProgressData,
): void {
  if (!researchMsg.value) {
    const msg: AgentMessage = {
      id: Date.now() + Math.random(),
      conversation_id: 0,
      role: 'research',
      content: d.current_step || '深度研究进行中',
      tool_call_id: null,
      tool_name: null,
      token_count: null,
      created_at: new Date().toISOString(),
      extra: { research: d },
    }
    messages.push(msg)
    researchMsg.value = msg
    return
  }
  researchMsg.value.content = d.current_step || researchMsg.value.content
  researchMsg.value.extra = { research: d }
}
