import { ref } from 'vue'
import { defineStore } from 'pinia'
import { researchApi } from '@/api/research'
import type { Research, ResearchRequest, ResearchStats, ResearchPlan } from '@/api/types'

export interface ResearchMessage {
  id: string
  role: 'user' | 'assistant' | 'progress' | 'plan'
  content: string
  progressPercent?: number
  stats?: ResearchStats | null
  sources?: string[]
  citations?: Array<{ title: string; url: string; source_type: string }>
  done?: boolean
  // plan 角色专用：计划数据与交互状态
  plan?: ResearchPlan
  planStatus?: 'awaiting' | 'accepted' | 'revising' | 'skipped'
}

let msgIdCounter = 0
function nextMsgId() {
  return `msg_${++msgIdCounter}_${Date.now()}`
}

export const useResearchStore = defineStore('research', () => {
  const currentResearch = ref<Research | null>(null)
  const isResearching = ref(false)
  const progress = ref('')
  const progressPercent = ref(0)
  const report = ref('')
  const history = ref<Research[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const abortController = ref<AbortController | null>(null)

  // 聊天式消息列表
  const messages = ref<ResearchMessage[]>([])
  // 当前研究流的计划反馈提交通道（onPlanGenerated 第二参注入，submitPlanFeedback 消费）
  const submitFeedbackRef = ref<
    ((decision: 'accepted' | 'edit_plan', feedback?: string) => void) | null
  >(null)

  function submitPlanFeedback(decision: 'accepted' | 'edit_plan', feedback?: string) {
    if (!submitFeedbackRef.value) return
    submitFeedbackRef.value(decision, feedback)
    submitFeedbackRef.value = null
    // 原位更新计划卡状态（accepted / revising）
    const planMsg = messages.value.find((m) => m.role === 'plan' && m.planStatus === 'awaiting')
    if (planMsg) {
      planMsg.planStatus = decision === 'accepted' ? 'accepted' : 'revising'
    }
  }

  async function startResearchStream(spaceId: number, data: ResearchRequest) {
    isResearching.value = true
    progress.value = '正在提交研究任务...'
    progressPercent.value = 0
    report.value = ''
    error.value = null

    // push user message
    messages.value.push({
      id: nextMsgId(),
      role: 'user',
      content: data.query,
    })

    const controller = new AbortController()
    abortController.value = controller

    let assistantMsgIdx = -1
    let lastProgressId = ''
    // 当前待反馈计划消息 id（onPlanGenerated 记录，submitPlanFeedback 原位更新状态）
    let planMsgId = ''

    try {
      await researchApi.streamResearch(spaceId, data, {
        signal: controller.signal,
        onProgress(d) {
          // deer-flow 对齐观察驱动模式：进度文案优先展示本轮实际 query（演化后）
          progress.value = d.current_query || d.current_step || '处理中...'
          progressPercent.value = d.progress_percent ?? 0
          // 计划已确认（首次检索进度到达时），计划卡置为已接受
          const planMsg = messages.value.find((m) => m.id === planMsgId)
          if (planMsg && planMsg.planStatus === 'awaiting') {
            planMsg.planStatus = 'accepted'
          }
          // mark previous progress as done
          if (lastProgressId) {
            for (let i = messages.value.length - 1; i >= 0; i--) {
              const prev = messages.value[i]
              if (prev && prev.id === lastProgressId) {
                prev.done = true
                break
              }
            }
          }
          // push new progress step
          const newProgress: ResearchMessage = {
            id: nextMsgId(),
            role: 'progress',
            content: d.current_query || d.current_step || '处理中...',
            progressPercent: d.progress_percent ?? 0,
            done: false,
          }
          messages.value.push(newProgress)
          lastProgressId = newProgress.id
        },
        onPlanGenerated(d, submitFeedback) {
          // 记录提交通道（submitPlanFeedback action 经此转发到 WS）
          submitFeedbackRef.value = submitFeedback
          // 已有计划卡（EDIT_PLAN 重规划）→ 原位更新；否则插入新计划卡
          const existing = messages.value.find((m) => m.id === planMsgId)
          if (existing) {
            existing.plan = d.plan
            existing.planStatus = 'awaiting'
            existing.content = d.plan.thought || existing.content
          } else {
            const planCard: ResearchMessage = {
              id: nextMsgId(),
              role: 'plan',
              content: d.plan.thought || `研究计划：${d.plan.title}`,
              plan: d.plan,
              planStatus: d.wait_feedback ? 'awaiting' : 'skipped',
            }
            messages.value.push(planCard)
            planMsgId = planCard.id
          }
          // wait_feedback=false：服务端不挂起（自动接受），卡片仅展示
          const card = messages.value.find((m) => m.id === planMsgId)
          if (card && !d.wait_feedback) {
            card.planStatus = 'skipped'
          }
        },
        onContent(chunk) {
          report.value += chunk || ''
          // create assistant message if not yet
          if (assistantMsgIdx === -1) {
            messages.value.push({
              id: nextMsgId(),
              role: 'assistant',
              content: '',
            })
            assistantMsgIdx = messages.value.length - 1
          }
          // modify through reactive array to trigger Vue reactivity
          const streamingMsg = messages.value[assistantMsgIdx]
          if (streamingMsg) {
            streamingMsg.content += chunk || ''
          }
        },
        onDone(d) {
          progress.value = '研究完成'
          progressPercent.value = 100
          // prefer final_report from done event, fall back to accumulated report
          const finalContent = d.final_report || report.value
          if (finalContent) {
            report.value = finalContent
          }
          // mark last progress as done
          if (lastProgressId) {
            for (let i = messages.value.length - 1; i >= 0; i--) {
              const prev = messages.value[i]
              if (prev && prev.id === lastProgressId) {
                prev.done = true
                break
              }
            }
          }
          // update or create assistant message
          if (assistantMsgIdx !== -1) {
            const msg = messages.value[assistantMsgIdx]
            if (msg) {
              msg.content = finalContent || msg.content
              msg.stats = d.stats || null
              msg.sources = d.sources || []
            }
          } else {
            messages.value.push({
              id: nextMsgId(),
              role: 'assistant',
              content: finalContent,
              stats: d.stats || null,
              sources: d.sources || [],
            })
          }
          // update sources from currentResearch
          currentResearch.value = {
            session_id: d.session_id || '',
            query: data.query,
            research_mode: data.research_mode || 'standard',
            search_source: data.search_source || 'hybrid',
            external_provider: null,
            status: 'completed',
            research_topic: null,
            research_tasks: null,
            final_report: report.value,
            search_summary: null,
            stats: d.stats || null,
            created_at: new Date().toISOString(),
            completed_at: new Date().toISOString(),
          }
          controller.abort()
        },
        onError(d) {
          error.value = d.message
          // mark last progress as done with error
          if (lastProgressId) {
            for (let i = messages.value.length - 1; i >= 0; i--) {
              const prev = messages.value[i]
              if (prev && prev.id === lastProgressId) {
                prev.content = `研究失败: ${d.message}`
                prev.done = true
                break
              }
            }
          }
        },
      })
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : '研究失败'
      // mark last progress as done with error
      if (lastProgressId) {
        for (let i = messages.value.length - 1; i >= 0; i--) {
          const prev = messages.value[i]
          if (prev && prev.id === lastProgressId) {
            prev.content = `研究失败: ${error.value}`
            prev.done = true
            break
          }
        }
      }
      throw e
    } finally {
      isResearching.value = false
      progress.value = ''
      abortController.value = null
      submitFeedbackRef.value = null
    }
  }

  async function fetchHistory(
    spaceId: number,
    params?: { limit?: number; offset?: number; status?: string },
  ) {
    loading.value = true
    try {
      const data = await researchApi.getResearchHistory(spaceId, params)
      history.value = data.items || []
      total.value = data.total || 0
      return { items: history.value, total: total.value }
    } finally {
      loading.value = false
    }
  }

  async function deleteResearch(spaceId: number, sessionId: string) {
    await researchApi.deleteResearch(spaceId, sessionId)
    history.value = history.value.filter((r) => r.session_id !== sessionId)
    if (currentResearch.value?.session_id === sessionId) {
      currentResearch.value = null
      report.value = ''
    }
  }

  function cancelResearch() {
    abortController.value?.abort()
    isResearching.value = false
    progress.value = ''
  }

  function clearMessages() {
    messages.value = []
    report.value = ''
    currentResearch.value = null
  }

  return {
    currentResearch,
    isResearching,
    progress,
    progressPercent,
    report,
    history,
    total,
    loading,
    error,
    messages,
    startResearchStream,
    submitPlanFeedback,
    fetchHistory,
    deleteResearch,
    cancelResearch,
    clearMessages,
  }
})
