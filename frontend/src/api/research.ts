import { request, createWebSocketStream } from './index'
import type { ResearchRequest, Research, ResearchListResponse, ResearchStats } from './types'

export const researchApi = {
  startResearch(spaceId: number, data: ResearchRequest) {
    return request.post<Research>(`/spaces/${spaceId}/deep-research`, data)
  },

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
      onContent?: (chunk: string) => void
      // 与后端 deep_research_service 的 done 事件载荷对齐：
      // stats 为 ResearchStats 形状（elapsed_seconds/internal_searches/external_searches/total_results 等）
      onDone?: (d: {
        session_id: string
        final_report: string
        stats: ResearchStats
        sources?: string[]
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
      },
      'research',
    )
  },

  getResearchHistory(
    spaceId: number,
    params?: { limit?: number; offset?: number; status?: string },
  ) {
    return request.get<ResearchListResponse>(`/spaces/${spaceId}/deep-research`, params)
  },

  getResearchDetail(spaceId: number, sessionId: string) {
    return request.get<Research>(`/spaces/${spaceId}/deep-research/${sessionId}`)
  },

  deleteResearch(spaceId: number, sessionId: string) {
    return request.delete<{ message: string }>(`/spaces/${spaceId}/deep-research/${sessionId}`)
  },
}
