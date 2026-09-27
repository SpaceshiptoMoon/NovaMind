import { request, createWebSocketStream } from './index'
import type {
  ResearchRequest,
  Research,
  ResearchListResponse,
  ResearchStats,
  ResearchPlan,
  SearchSourceInfo,
} from './types'

/**
 * 深度研究 API
 *
 * 会话式深研究：数据源发现、WS 流式执行（进度/计划确认/报告产出）、
 * 历史记录管理。
 */
export const researchApi = {
  /** 源发现：返回注册表全部数据源（新源注册后自动出现，前端零改动） */
  listSearchSources(spaceId: number) {
    return request.get<{ sources: SearchSourceInfo[] }>(`/spaces/${spaceId}/deep-research/sources`)
  },

  /** 发起一次深研究（入队执行，返回会话；实时进展走 streamResearch 流） */
  startResearch(spaceId: number, data: ResearchRequest) {
    return request.post<Research>(`/spaces/${spaceId}/deep-research`, data)
  },

  /**
   * WS 流式执行深研究，按事件类型分发回调。
   *
   * Promise 在连接正常关闭（done 后）时 resolve；认证失败（4401/4403）或
   * 异常断连时 reject；signal 中止则静默结束。
   *
   * @param callbacks.onProgress 执行进度（状态/当前步骤/百分比/本轮检索 query）
   * @param callbacks.onPlanGenerated 计划生成回调；wait_feedback=true 时服务端已挂起，
   *   须在超时前调第二参 submitFeedback 提交决策（'accepted' 直接收紧，
   *   'edit_plan' 附反馈文本由模型修订计划后继续）
   * @param callbacks.onContent 报告正文增量 chunk（流式渲染）
   * @param callbacks.onDone 研究完成：最终报告全文 + 检索统计 + 引用来源
   * @param callbacks.onError 执行/连接错误
   * @param callbacks.signal 传入 AbortSignal 可随时取消（关闭 WS，静默结束）
   */
  streamResearch(
    spaceId: number,
    data: ResearchRequest,
    callbacks: {
      onProgress?: (d: {
        status: string
        current_step: string
        progress_percent: number
        completed_tasks: number
        total_tasks: number
        // deer-flow 对齐观察驱动模式：本轮实际使用的检索 query（演化后）
        current_query?: string
      }) => void
      // 计划已生成（deer-flow human_feedback 对齐）：wait_feedback=true 时
      // 服务端已挂起；第二参 submitFeedback 用于提交决策：
      //   submitFeedback('accepted') 或 submitFeedback('edit_plan', '反馈文本')
      onPlanGenerated?: (
        d: {
          session_id: string
          plan: ResearchPlan
          wait_feedback: boolean
          feedback_timeout_seconds: number
        },
        submitFeedback: (decision: 'accepted' | 'edit_plan', feedback?: string) => void,
      ) => void
      onContent?: (chunk: string) => void
      // 与后端 deep_research_service 的 done 事件载荷对齐：
      // stats 为 ResearchStats 形状（elapsed_seconds/internal_searches/external_searches/total_results 等）
      onDone?: (d: {
        session_id: string
        final_report: string
        stats: ResearchStats
        sources?: string[]
        citations?: Array<{ title: string; url: string; source_type: string }>
      }) => void
      onError?: (d: { message: string; session_id: string }) => void
      signal?: AbortSignal
    },
  ) {
    return createWebSocketStream(
      `/spaces/${spaceId}/deep-research/ws`,
      data,
      {
        onMessage(event) {
          const e = event
          switch (e.type) {
            case 'progress':
              callbacks.onProgress?.(e.data as Parameters<typeof callbacks.onProgress>[0])
              break
            case 'plan_generated': {
              const planData = e.data as {
                session_id: string
                plan: ResearchPlan
                wait_feedback: boolean
                feedback_timeout_seconds: number
              }
              callbacks.onPlanGenerated?.(planData, (decision, feedback) => {
                sendRef.value?.({
                  action: 'plan_feedback',
                  decision,
                  feedback: feedback ?? '',
                })
              })
              break
            }
            case 'content':
              callbacks.onContent?.((e.data as { chunk: string }).chunk)
              break
            case 'done':
              callbacks.onDone?.(e.data as Parameters<typeof callbacks.onDone>[0])
              break
            case 'error':
              callbacks.onError?.(e.data as { message: string; session_id: string })
              break
            default:
              break
          }
        },
        onError: callbacks.onError
          ? (msg) => callbacks.onError!({ message: msg, session_id: '' })
          : undefined,
        signal: callbacks.signal,
        onReady: (send) => {
          sendRef.value = send
        },
      },
      'research',
    )
  },

  /** 研究历史列表（分页；可按状态过滤） */
  getResearchHistory(
    spaceId: number,
    params?: { limit?: number; offset?: number; status?: string },
  ) {
    return request.get<ResearchListResponse>(`/spaces/${spaceId}/deep-research`, params)
  },

  /** 研究会话详情（任务分解/最终报告/统计） */
  getResearchDetail(spaceId: number, sessionId: string) {
    return request.get<Research>(`/spaces/${spaceId}/deep-research/${sessionId}`)
  },

  /** 删除研究会话记录 */
  deleteResearch(spaceId: number, sessionId: string) {
    return request.delete<{ message: string }>(`/spaces/${spaceId}/deep-research/${sessionId}`)
  },
}

// streamResearch 每次调用的 send 通道槽位（onReady 注入 / plan_feedback 提交消费）。
// 模块级单槽位足够：一次会话同时只有一个进行中的研究流（store 层 isResearching 守卫）。
const sendRef: { value: ((msg: unknown) => void) | null } = { value: null }
