import { request } from '../index'
import type {
  KnowledgeGapStatsResponse,
  ActionStatsResponse,
  KbOpsGapReport,
} from '../types'

/**
 * 空间统计 API
 *
 * 空间级运营看板：知识缺口统计与操作审计聚合 + kb-ops gap 报告。
 */
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

  /** kb-ops 知识缺口报告（归因分布 + 内容缺口清单，A2） */
  getGapReport(spaceId: number, params?: { start?: string; end?: string; gap_limit?: number }) {
    return request.get<KbOpsGapReport>(`/kb-ops/spaces/${spaceId}/gap-report`, params)
  },
}
