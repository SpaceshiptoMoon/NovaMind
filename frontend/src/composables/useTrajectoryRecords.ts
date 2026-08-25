/**
 * 轨迹视图 record 派生：把 agentStore.messages 平铺成 TrajectoryRecord[]。
 *
 * 对齐 dsh TrajectoryView 的可追溯性：
 * - 稳定 seq：基于全量 messages 顺序分配 1-based 序号，过滤/搜索后不变
 * - 稳定 recordId：msg.id > tool_call_id > seq，用于选中态/折叠集合/hierarchy 跳转
 * - parentAssistantRecordId：tool 行回溯父 assistant 决策（按 tool_call_id 匹配 extra.tool_calls[].id）
 * - turnIndex：按 user 消息切分，供 Turns/Calls 折叠
 */
import { computed, type ComputedRef } from 'vue'
import type {
  AgentMessage,
  OpenAICompatToolCall,
  ToolCallRecord,
} from '@/api/types'

// system 行不在 messages 里（按需拉全文），由 TrajectoryList 构造伪 record 传给 inspector
export type TrajectoryKind = 'user' | 'assistant' | 'tool' | 'compaction' | 'system' | 'plan' | 'notice'

export interface TrajectoryRecord {
  /** 稳定身份：msg.id > tool_call_id > 'system' > seq */
  recordId: string
  /** 原始 1-based 序号，过滤/搜索后不变（system 行固定 #0） */
  seq: number
  kind: TrajectoryKind
  msg: AgentMessage
  /** tool 行关联的工具记录（按 tool_call_id 匹配 toolCalls） */
  toolCall?: ToolCallRecord
  /** tool 行的父 assistant 决策 recordId（hierarchy 跳转） */
  parentAssistantRecordId?: string
  /** 所属 turn（按 user 消息切分，orphan 归 turn 0） */
  turnIndex: number
  /** 行预览文本 */
  summary: string
  /** 该 assistant 决策携带的 tool_calls（决策行用） */
  toolCalls?: OpenAICompatToolCall[]
  /** extra.usage（per-iteration token） */
  usage?: Record<string, number>
  /** extra.duration_ms（per-iteration LLM 耗时） */
  durationMs?: number
  /** assistant 决策但无 content/reasoning（tool call only） */
  isToolCallOnly?: boolean
  /** 该 assistant 决策下挂的 tool recordIds（Calls 折叠用） */
  childToolRecordIds?: string[]
}

/** 尝试把字符串解析成 JSON 容器（object/array），失败返回 null */
export function parseJsonContainer(raw: string | null | undefined): unknown {
  if (!raw) return null
  const trimmed = raw.trim()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return null
  try {
    const parsed = JSON.parse(trimmed)
    if (parsed !== null && typeof parsed === 'object') return parsed
    return null
  } catch {
    return null
  }
}

/** 取文本首行并截断，作行预览 */
function firstLine(text: string | null | undefined, max = 120): string {
  if (!text) return ''
  const line = text.split('\n').find((l) => l.trim()) || ''
  return line.length > max ? line.slice(0, max) + '…' : line
}

/** 压缩 JSON 参数为单行，作 tool 行预览的 argsRaw */
function compactArgs(args: Record<string, unknown> | undefined): string {
  if (!args || Object.keys(args).length === 0) return ''
  try {
    const s = JSON.stringify(args)
    return s.length > 80 ? s.slice(0, 80) + '…' : s
  } catch {
    return ''
  }
}

/** tool_calls 名列表（assistant 决策行预览） */
export function toolCallNames(tcs: OpenAICompatToolCall[] | undefined): string {
  if (!tcs?.length) return ''
  return tcs.map((t) => t.function.name).join(', ')
}

/**
 * 派生 TrajectoryRecord[]。
 * @param messages agentStore.messages（响应式）
 * @param toolCalls agentStore.toolCalls（响应式）
 */
export function useTrajectoryRecords(
  messages: ComputedRef<AgentMessage[]> | AgentMessage[],
  toolCalls: ComputedRef<ToolCallRecord[]> | ToolCallRecord[],
): ComputedRef<TrajectoryRecord[]> {
  const msgs = computed(() => ('value' in messages ? messages.value : messages))
  const calls = computed(() => ('value' in toolCalls ? toolCalls.value : toolCalls))

  return computed<TrajectoryRecord[]>(() => {
    const list = msgs.value
    const callList = calls.value
    const result: TrajectoryRecord[] = []
    let seq = 0
    let turnIndex = 0
    // 最近一条 assistant 决策的 recordId + 其 tool_call id 集合，供 tool 行回溯 parent
    let lastAssistantDecisionId: string | null = null
    let lastAssistantDecisionCallIds: Set<string> = new Set()
    // recordId -> 该决策下挂的 tool recordIds（第二次遍历填充）
    const decisionChildMap = new Map<string, string[]>()

    for (const msg of list) {
      seq += 1
      const recordId = String(msg.id)
      const extra = (msg.extra as Record<string, unknown> | null | undefined) ?? undefined
      const usage = extra?.usage as Record<string, number> | undefined
      const durationMsRaw = extra?.duration_ms
      const durationMs = typeof durationMsRaw === 'number' ? durationMsRaw : undefined
      const extraToolCalls = extra?.tool_calls as OpenAICompatToolCall[] | undefined

      // turn 切分：user 开新 turn（第一轮 turn=1，orphan 归 turn 0）
      if (msg.role === 'user') {
        turnIndex += 1
      }

      // assistant 决策判定：role=assistant 且带 tool_calls
      const isAssistantDecision = msg.role === 'assistant' && !!extraToolCalls?.length
      const isToolCallOnly =
        isAssistantDecision && !msg.content && !msg.reasoning

      if (isAssistantDecision) {
        lastAssistantDecisionId = recordId
        lastAssistantDecisionCallIds = new Set(extraToolCalls!.map((t) => t.id))
        decisionChildMap.set(recordId, [])
      }

      // tool 行：匹配 toolCall 记录 + 回溯父 assistant
      let toolCall: ToolCallRecord | undefined
      let parentAssistantRecordId: string | undefined
      if (msg.role === 'tool' && msg.tool_call_id) {
        toolCall = callList.find((c) => c.callId === msg.tool_call_id)
        if (lastAssistantDecisionCallIds.has(msg.tool_call_id)) {
          parentAssistantRecordId = lastAssistantDecisionId ?? undefined
          if (parentAssistantRecordId) {
            decisionChildMap.get(parentAssistantRecordId)?.push(recordId)
          }
        }
      }

      // kind 映射（messages 不含 system，system 行在 TrajectoryList 顶部单独处理）
      const kind = msg.role as TrajectoryKind

      // summary
      let summary = ''
      if (kind === 'user') {
        summary = firstLine(msg.content)
      } else if (kind === 'assistant') {
        if (isAssistantDecision) {
          summary =
            firstLine(msg.reasoning) ||
            firstLine(msg.content) ||
            '(tool call only)'
        } else {
          summary = firstLine(msg.content) || firstLine(msg.reasoning)
        }
      } else if (kind === 'tool') {
        const argsRaw = compactArgs(toolCall?.arguments)
        const resultPreview = firstLine(toolCall?.result, 80)
        const name = msg.tool_name || toolCall?.toolName || 'tool'
        summary = resultPreview
          ? `${name} ${argsRaw} → ${resultPreview}`.trim()
          : `${name} ${argsRaw}`.trim()
      } else if (kind === 'compaction') {
        const comp = extra?.compaction as { summarized_count?: number; summary?: string } | undefined
        summary = comp?.summarized_count
          ? `已压缩 ${comp.summarized_count} 条`
          : firstLine(comp?.summary) || '上下文已压缩'
      } else if (kind === 'plan') {
        const plan = extra?.plan as { title?: string; steps?: string[]; step_count?: number } | undefined
        const stepN = plan?.steps?.length ?? plan?.step_count ?? 0
        summary = plan?.title ? `计划: ${plan.title} (${stepN}步)` : `计划 (${stepN}步)`
      } else if (kind === 'notice') {
        summary = firstLine(msg.content) || '系统纠偏警告'
      }

      result.push({
        recordId,
        seq,
        kind,
        msg,
        toolCall,
        parentAssistantRecordId,
        turnIndex,
        summary,
        toolCalls: isAssistantDecision ? extraToolCalls : undefined,
        usage,
        durationMs,
        isToolCallOnly,
      })
    }

    // 第二次遍历：填充 childToolRecordIds
    for (const rec of result) {
      if (rec.toolCalls?.length) {
        rec.childToolRecordIds = decisionChildMap.get(rec.recordId) ?? []
      }
    }

    return result
  })
}

/** 格式化毫秒耗时为紧凑字符串 */
export function formatDurationMs(ms: number | undefined | null): string {
  if (!ms || ms < 0) return ''
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(s < 10 ? 2 : 1)}s`
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return `${m}m${sec}s`
}