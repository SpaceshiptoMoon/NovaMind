import type {
  AgentCompactionData,
  AgentMessage,
  ContentBlock,
  OpenAICompatToolCall,
  ResearchProgressData,
} from '@/api/types'

/**
 * 聊天流渲染的共享视图模型层（纯函数，零组件依赖）
 *
 * 单聊 AgentChatView 与群聊组件共用的两块：
 * 1. 按轮分组（groupTurns）——一条用户消息 + 其后的 tool/assistant 消息切一轮
 * 2. 消息解析 helpers（content blocks / 工具参数 / 附件 / compaction / plan / research）
 * 都是表示层视图模型，后端存储不变。
 */

// ===================== 类型 =====================

/** 一个 ReAct 步骤 = AI 一次响应（决策消息 content + tool_calls）+ 其调用的工具执行结果 */
export interface ReActStep {
  ai: AgentMessage | null
  tools: AgentMessage[]
}

export interface ChatTurn {
  key: string
  userMsg: AgentMessage | null
  items: AgentMessage[]
  compactionItems: AgentMessage[]
  planItems: AgentMessage[]
  noticeItems: AgentMessage[]
  researchItems: AgentMessage[]
  finalAssistant: AgentMessage | null
  workItems: AgentMessage[]
  steps: ReActStep[]
  startTime: number
  endTime: number | null
  isActive: boolean
}

/** 输入卡发送 payload：档位/研究/模型选择由 InputCard 收集，发送编排由壳完成 */
export interface ChatSendPayload {
  content: string
  enableThinking: boolean
  enableResearch: boolean
  model: string
}

// ===================== 时间格式化 =====================

export function tsOf(iso: string | null | undefined): number {
  if (!iso) return 0
  const t = new Date(iso).getTime()
  return Number.isNaN(t) ? 0 : t
}

export function formatDuration(ms: number): string {
  if (!ms || ms < 0) ms = 0
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const sec = s % 60
  if (m < 60) return `${m}m${sec.toString().padStart(2, '0')}s`
  const h = Math.floor(m / 60)
  return `${h}h${(m % 60).toString().padStart(2, '0')}m`
}

// ===================== 按轮分组 =====================

/**
 * 把扁平消息流按「一条用户消息 + 其后所有消息」切轮，并给每轮归类最终回复与 ReAct 步骤。
 *
 * 一轮 = 一条用户消息 + 其后的所有 tool/assistant/system 消息（直到下一条用户消息）。
 * 只展示该轮「最后一条 assistant」的最终回复；其前的 tool/中间 assistant/思考过程
 * 按序折叠在 avatar 折叠头下。
 */
export function groupTurns(messages: AgentMessage[], streamActive: boolean): ChatTurn[] {
  const result: ChatTurn[] = []
  let current: ChatTurn | null = null
  for (const msg of messages) {
    if (msg.role === 'user') {
      if (current) result.push(current)
      current = {
        key: `turn-${msg.id}`,
        userMsg: msg,
        items: [],
        compactionItems: [],
        planItems: [],
        noticeItems: [],
        researchItems: [],
        finalAssistant: null,
        workItems: [],
        steps: [],
        startTime: tsOf(msg.created_at),
        endTime: null,
        isActive: false,
      }
    } else if (current) {
      // compaction/plan/notice 标记行分流到专属列表，不计入 items/workItems/steps，
      // 也不参与 finalAssistant 检测（role!=='assistant' 天然排除）。
      // plan/notice 不分流会掉进 byIter（iteration ?? 0 建空步虚增 steps.length）
      if (msg.role === 'compaction') {
        current.compactionItems.push(msg)
      } else if (msg.role === 'plan') {
        current.planItems.push(msg)
      } else if (msg.role === 'research') {
        current.researchItems.push(msg)
      } else if (msg.role === 'notice') {
        current.noticeItems.push(msg)
      } else {
        current.items.push(msg)
      }
    } else {
      // 没有前置用户消息的孤立消息（如历史首条是 assistant 或 compaction）
      current = {
        key: `turn-orphan-${msg.id}`,
        userMsg: null,
        items:
          msg.role === 'compaction' || msg.role === 'plan' || msg.role === 'notice' ? [] : [msg],
        compactionItems: msg.role === 'compaction' ? [msg] : [],
        planItems: msg.role === 'plan' ? [msg] : [],
        noticeItems: msg.role === 'notice' ? [msg] : [],
        researchItems: msg.role === 'research' ? [msg] : [],
        finalAssistant: null,
        workItems: [],
        steps: [],
        startTime: tsOf(msg.created_at),
        endTime: null,
        isActive: false,
      }
    }
  }
  if (current) result.push(current)

  for (const t of result) {
    classifyTurnTail(t)
    t.steps = groupReActSteps(t.workItems)
  }

  // 当前正在流式/加载的最后一轮标记为 active
  if (result.length && streamActive) {
    const last = result[result.length - 1]
    if (last) last.isActive = true
  }
  return result
}

/** 找该轮最后一条有内容的 assistant 作为最终回复，其余归入 workItems */
function classifyTurnTail(t: ChatTurn): void {
  let lastIdx = -1
  for (let i = t.items.length - 1; i >= 0; i--) {
    const it = t.items[i]
    // 排除含 tool_call 块的决策消息：那是「AI 决定调用工具」的中间步骤，
    // content 是该轮决策文本而非最终回答；即便它是该轮最后一条 assistant 也不能当最终回复。
    // 判别基于 ContentBlock（不依赖 extra.tool_calls 字段存在性），空 content 的决策也能正确归类
    if (it && it.role === 'assistant' && it.content && !hasToolCallBlocks(it)) {
      lastIdx = i
      break
    }
  }
  if (lastIdx >= 0) {
    const final = t.items[lastIdx]
    if (final) {
      t.finalAssistant = final
      t.workItems = t.items.filter((_, i) => i !== lastIdx)
      t.endTime = tsOf(final.created_at)
    }
  } else {
    t.workItems = [...t.items]
    const lastItem = t.items[t.items.length - 1]
    if (lastItem) t.endTime = tsOf(lastItem.created_at)
  }
}

/**
 * 按 ReAct 步骤分组：优先用 iteration 字段（同一轮的 assistant 决策 + tool 归同一步），
 * 还原 LLM 一次响应（ai: content + tool_calls）+ 工具执行（tools）的原始结构。
 * 无 iteration（历史数据）fallback 到老的顺序推断（assistant 开新 step，tool 归入）。
 */
function groupReActSteps(workItems: AgentMessage[]): ReActStep[] {
  const steps: ReActStep[] = []
  const hasIter = workItems.some((it) => it.iteration != null)
  if (hasIter) {
    const byIter = new Map<number, ReActStep>()
    const order: number[] = []
    for (const item of workItems) {
      const iter = item.iteration ?? 0
      let step = byIter.get(iter)
      if (!step) {
        step = { ai: null, tools: [] }
        byIter.set(iter, step)
        order.push(iter)
      }
      if (item.role === 'assistant') {
        step.ai = item
      } else if (item.role === 'tool') {
        step.tools.push(item)
      }
    }
    for (const iter of order) {
      const step = byIter.get(iter)
      if (step) steps.push(step)
    }
  } else {
    let cur: ReActStep | null = null
    for (const item of workItems) {
      if (item.role === 'assistant') {
        if (cur) steps.push(cur)
        cur = { ai: item, tools: [] }
      } else if (item.role === 'tool') {
        if (!cur) cur = { ai: null, tools: [] }
        cur.tools.push(item)
      }
    }
    if (cur) steps.push(cur)
  }
  return steps
}

// ===================== Content blocks =====================

/**
 * 把 assistant 消息的 reasoning/content/extra.tool_calls 三字段统一成 block 数组，
 * 前端按 kind 分发渲染（reasoning → think, text → 回答, tool_call → 工具调用）。
 * 决策消息 blocks=[reasoning?,text?,tool_call*]，最终回答 blocks=[reasoning?,text?]，
 * 纯 tool 消息不走此路径。
 */
export function toContentBlocks(msg: AgentMessage | null): ContentBlock[] {
  if (!msg) return []
  const blocks: ContentBlock[] = []
  if (msg.reasoning) blocks.push({ kind: 'reasoning', text: msg.reasoning })
  if (msg.content) blocks.push({ kind: 'text', text: msg.content })
  const tcs = msg.extra?.tool_calls as OpenAICompatToolCall[] | undefined
  if (tcs?.length) {
    for (const tc of tcs) {
      blocks.push({
        kind: 'tool_call',
        id: tc.id,
        name: tc.function.name,
        arguments: tc.function.arguments,
      })
    }
  }
  return blocks
}

/** 判定 assistant 消息是否含工具调用块（决策消息），用于 finalAssistant 归类 */
export function hasToolCallBlocks(msg: AgentMessage | null): boolean {
  return toContentBlocks(msg).some((b) => b.kind === 'tool_call')
}

/** 步骤摘要行文案：思考取首行截断，纯回答取首行，工具调用列名（最多两个 + 省略） */
export function stepSummary(step: ReActStep): string {
  const blocks = toContentBlocks(step.ai)
  const toolCalls = blocks.filter((b) => b.kind === 'tool_call')
  const think = blocks.find((b) => b.kind === 'reasoning')
  const text = blocks.find((b) => b.kind === 'text')
  const parts: string[] = []
  if (toolCalls.length) {
    const names = toolCalls.map((b) => (b.kind === 'tool_call' ? b.name : ''))
    parts.push(
      names.length > 2
        ? `调用 ${names.slice(0, 2).join('、')} 等 ${names.length} 个工具`
        : `调用 ${names.join('、')}`,
    )
  }
  const firstLine = (source: string) => {
    const line =
      source
        .trim()
        .split('\n')
        .find((l) => l.trim()) || ''
    return line.length > 40 ? line.slice(0, 40) + '…' : line
  }
  if (think) parts.push(firstLine(think.text))
  else if (text && !toolCalls.length) parts.push(firstLine(text.text))
  return parts.join(' · ') || '思考中'
}

/** 工具参数格式化展示：单聊是 JSON 字符串（parse 后美化），群聊是已解析对象（直接美化） */
export function formatToolArgs(args: string | Record<string, unknown> | undefined | null): string {
  if (!args) return ''
  if (typeof args !== 'string') {
    try {
      return JSON.stringify(args, null, 2)
    } catch {
      return String(args)
    }
  }
  try {
    return JSON.stringify(JSON.parse(args), null, 2)
  } catch {
    return args
  }
}

// ===================== 工具记录查询 =====================

export function findToolRecord(
  toolCalls: Array<{ callId: string | null; durationMs?: number; status: string }>,
  callId: string | null,
): { durationMs?: number; status: string } | null {
  if (!callId) return null
  return toolCalls.find((c) => c.callId === callId) ?? null
}

/** 实时流期间 toolCalls 记录一定存在（onToolCall 同时建记录与消息）；
 *  走到默认值只可能是历史回放且未匹配到记录，持久化的 tool 消息必然已结束，故默认 completed */
export function toolStatusOf(
  toolCalls: Array<{ callId: string | null; status: string }>,
  callId: string | null,
): string {
  return findToolRecord(toolCalls, callId)?.status || 'completed'
}

export function toolStatusLabel(status: string): string {
  const map: Record<string, string> = {
    running: '执行中',
    completed: '完成',
    failed: '失败',
    pending: '等待中',
  }
  return map[status] || status
}

// ===================== 附件与标记行数据提取 =====================

export interface MessageAttachment {
  id?: number
  filename: string
  file_type?: string
  file_size?: number
  storage_path?: string
  preview_url?: string
}

export function getMessageAttachments(msg: AgentMessage): MessageAttachment[] {
  const extra = msg.extra as Record<string, unknown> | null | undefined
  return (
    (extra?.attachments as Array<Record<string, unknown>> | undefined)?.map((a) => ({
      id: typeof a.id === 'number' ? a.id : undefined,
      filename: typeof a.filename === 'string' ? a.filename : '',
      file_type: typeof a.file_type === 'string' ? a.file_type : undefined,
      file_size: typeof a.file_size === 'number' ? a.file_size : undefined,
      storage_path: typeof a.storage_path === 'string' ? a.storage_path : undefined,
    })) ?? []
  )
}

/** 压缩标记的 extra.compaction 提取（模板内不做复杂类型断言） */
export function getCompactionData(msg: AgentMessage): AgentCompactionData | undefined {
  return (msg.extra as Record<string, unknown> | null | undefined)?.compaction as
    | AgentCompactionData
    | undefined
}

/** 计划卡的 extra.plan 提取（字段缺省安全：历史数据无 statuses/summary） */
export function getPlanData(msg: AgentMessage): {
  title?: string
  steps: string[]
  statuses?: string[]
  summary?: string
  interrupted?: boolean
} {
  const plan = (msg.extra as { plan?: Record<string, unknown> } | null | undefined)?.plan
  return {
    title: typeof plan?.title === 'string' ? plan.title : undefined,
    steps: Array.isArray(plan?.steps) ? (plan?.steps as string[]) : [],
    statuses: Array.isArray(plan?.statuses) ? (plan?.statuses as string[]) : undefined,
    summary: typeof plan?.summary === 'string' ? plan.summary : undefined,
    interrupted: plan?.interrupted === true,
  }
}

/** 研究进度卡的 extra.research 提取（字段缺省安全：历史/异常数据兜底空态） */
export function getResearchData(msg: AgentMessage): ResearchProgressData {
  const r = (msg.extra as { research?: Record<string, unknown> } | null | undefined)?.research
  return {
    status: typeof r?.status === 'string' ? r.status : 'analyzing',
    current_step: typeof r?.current_step === 'string' ? r.current_step : undefined,
    progress_percent: typeof r?.progress_percent === 'number' ? r.progress_percent : 0,
    completed_tasks: typeof r?.completed_tasks === 'number' ? r.completed_tasks : 0,
    total_tasks: typeof r?.total_tasks === 'number' ? r.total_tasks : 0,
    plan: (r?.plan as ResearchProgressData['plan']) ?? null,
  }
}

// ===================== 文件类型 helpers =====================

const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'gif', 'webp'])

export function isImageFile(type?: string): boolean {
  return !!type && IMAGE_EXTENSIONS.has(type.toLowerCase())
}

export function getFileIconClass(type?: string): string {
  if (!type) return 'file-default'
  const t = type.toLowerCase()
  if (t === 'pdf') return 'file-pdf'
  if (t === 'docx' || t === 'doc') return 'file-doc'
  if (t === 'txt') return 'file-txt'
  if (t === 'md') return 'file-md'
  if (isImageFile(t)) return 'file-image'
  return 'file-default'
}

export function getFileExt(filename?: string): string {
  if (!filename) return 'FILE'
  return filename.split('.').pop()?.toUpperCase() || 'FILE'
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// ===================== 工具结果展示 =====================

export function truncateResult(text: string): string {
  if (text.length <= 2000) return text
  return text.slice(0, 2000) + '\n... (已截断)'
}

/** wiki 工具结果解析：items/pages 中带 url+title 的条目（后端 wiki_tools 拼好前端路径） */
export function wikiToolLinks(tool: {
  tool_name?: string | null
  content?: string | null
}): Array<{ url: string; title: string }> {
  if (!tool.content || !tool.tool_name?.startsWith('wiki_')) return []
  try {
    const data = JSON.parse(tool.content) as {
      items?: Array<{ url?: string; title?: string }>
      pages?: Array<{ url?: string; title?: string; found?: boolean }>
    }
    const entries = [...(data.items ?? []), ...(data.pages ?? [])]
    return entries.filter(
      (it): it is { url: string; title: string } =>
        typeof it?.url === 'string' && typeof it?.title === 'string',
    )
  } catch {
    return []
  }
}
