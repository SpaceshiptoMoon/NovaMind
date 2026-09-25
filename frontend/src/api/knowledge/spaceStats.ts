import { request } from '../index'
import type {
  KnowledgeGapStatsResponse,
  ActionStatsResponse,
} from '../types'

/** 空间统计看板 API（批次 2b：知识缺口看板） */
export const spaceStatsApi = {
  /** 知识缺口看板（KPI/趋势/零命中/低分明细/KB 聚合） */
  getKnowledgeGap(params?: {
    spaceId: number
    start?: string
    end?: string
    kb_id?: number
    low_score_threshold?: number
  }) {
    const { spaceId, ...query } = params || { spaceId: 0 }
    return request.get<KnowledgeGapStatsResponse>(
      `/spaces/${spaceId}/stats/knowledge-gap`,
      query,
    )
  },

  /** 空间操作审计统计 */
  getActionStats(spaceId: number, params?: { start?: string; end?: string }) {
    return request.get<ActionStatsResponse>(`/spaces/${spaceId}/stats/actions`, params)
  },
}
