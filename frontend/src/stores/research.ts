import { ref } from 'vue'
import { defineStore } from 'pinia'
import { researchApi } from '@/api/research'
import type { Research, ResearchRequest, ResearchStats } from '@/api/types'

export interface ResearchMessage {
  id: string
  role: 'user' | 'assistant' | 'progress'
  content: string
  progressPercent?: number
  stats?: ResearchStats | null
  sources?: string[]
  done?: boolean
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

    try {
      await researchApi.streamResearch(spaceId, data, {
        signal: controller.signal,
        onProgress(d) {
          progress.value = d.current_step || '处理中...'
          progressPercent.value = d.progress_percent ?? 0
          // mark previous progress as done
          if (lastProgressId) {
            for (let i = messages.value.length - 1; i >= 0; i--) {
              if (messages.value[i].id === lastProgressId) {
                messages.value[i].done = true
                break
              }
            }
          }
          // push new progress step
          const newProgress: ResearchMessage = {
            id: nextMsgId(),
            role: 'progress',
            content: d.current_step || '处理中...',
            progressPercent: d.progress_percent ?? 0,
            done: false,
          }
          messages.value.push(newProgress)
          lastProgressId = newProgress.id
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
          messages.value[assistantMsgIdx].content += chunk || ''
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
              if (messages.value[i].id === lastProgressId) {
                messages.value[i].done = true
                break
              }
            }
          }
          // update or create assistant message
          if (assistantMsgIdx !== -1) {
            const msg = messages.value[assistantMsgIdx]
            msg.content = finalContent || msg.content
            msg.stats = d.stats as ResearchStats || null
          } else {
            messages.value.push({
              id: nextMsgId(),
              role: 'assistant',
              content: finalContent,
              stats: d.stats as ResearchStats || null,
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
            stats: d.stats as Research['stats'] || null,
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
              if (messages.value[i].id === lastProgressId) {
                messages.value[i].content = `研究失败: ${d.message}`
                messages.value[i].done = true
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
          if (messages.value[i].id === lastProgressId) {
            messages.value[i].content = `研究失败: ${error.value}`
            messages.value[i].done = true
            break
          }
        }
      }
      throw e
    } finally {
      isResearching.value = false
      progress.value = ''
      abortController.value = null
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
    fetchHistory,
    deleteResearch,
    cancelResearch,
    clearMessages,
  }
})
