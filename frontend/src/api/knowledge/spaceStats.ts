import { request } from '../index'
import type {
  KnowledgeGapStatsResponse,
  ActionStatsResponse,
  KbOpsGapReport,
  KbOpsSuggestionList,
  KbOpsSuggestionResolve,
  KbOpsDuplicates,
  KbOpsCitationStats,
  KbOpsContradictionScan,
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

  /** kb-ops 复审建议列表（open 状态，得分降序，B2/D） */
  getReviewSuggestions(spaceId: number, params?: { suggestion_type?: string }) {
    return request.get<KbOpsSuggestionList>(`/kb-ops/spaces/${spaceId}/review-suggestions`, params)
  },

  /** kb-ops 处置建议（accept: new_version 触发 supersede / contradiction 通知 owner；dismiss 忽略） */
  resolveSuggestion(spaceId: number, suggestionId: number, action: 'accepted' | 'dismissed') {
    return request.post<KbOpsSuggestionResolve>(
      `/kb-ops/spaces/${spaceId}/review-suggestions/${suggestionId}/resolve`,
      { action },
    )
  },

  /** kb-ops 重复文档分组（精确 hash + 同归一化名，D1） */
  getDuplicates(spaceId: number, params?: { kb_id?: number; limit?: number }) {
    return request.get<KbOpsDuplicates>(`/kb-ops/spaces/${spaceId}/duplicates`, params)
  },

  /** kb-ops 文档贡献统计（点击核验 + 支撑回答，D3） */
  getCitationStats(spaceId: number, params?: { limit?: number }) {
    return request.get<KbOpsCitationStats>(`/kb-ops/spaces/${spaceId}/citation-stats`, params)
  },

  /** kb-ops 触发矛盾检测（空间 admin，D2；LLM 成本操作） */
  runContradictionScan(spaceId: number, kbId: number) {
    return request.post<KbOpsContradictionScan>(
      `/kb-ops/spaces/${spaceId}/contradiction-scan?kb_id=${kbId}`,
    )
  },
}
