import { request, createSSEStream } from './index'
import type { ResearchRequest, Research, ResearchListResponse } from './types'

export const researchApi = {
  startResearch(spaceId: number, data: ResearchRequest) {
    return request.post<Research>(`/spaces/${spaceId}/deep-research`, data)
  },

  streamResearch(
    spaceId: number,
    data: ResearchRequest,
    callbacks: {
      onProgress?: (d: { status: string; current_step: string; progress_percent: number; completed_tasks: number; total_tasks: number }) => void
      onContent?: (chunk: string) => void
      onDone?: (d: { session_id: string; final_report: string; stats: Record<string, number> }) => void
      onError?: (d: { message: string; session_id: string }) => void
      signal?: AbortSignal
    },
  ) {
    return createSSEStream(`/spaces/${spaceId}/deep-research/stream`, data, {
      onMessage(event) {
        const e = event as { type: string; data: unknown }
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
      onError: callbacks.onError ? (msg) => callbacks.onError!({ message: msg, session_id: '' }) : undefined,
      signal: callbacks.signal,
    })
  },

  getResearchHistory(spaceId: number, params?: { limit?: number; offset?: number; status?: string }) {
    return request.get<ResearchListResponse>(`/spaces/${spaceId}/deep-research`, params)
  },

  getResearchDetail(spaceId: number, sessionId: string) {
    return request.get<Research>(`/spaces/${spaceId}/deep-research/${sessionId}`)
  },

  deleteResearch(spaceId: number, sessionId: string) {
    return request.delete<{ message: string }>(`/spaces/${spaceId}/deep-research/${sessionId}`)
  },
}
