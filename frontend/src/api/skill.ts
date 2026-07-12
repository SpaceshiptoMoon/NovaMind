import { request } from './index'
import instance from './index'
import type {
  SkillDefinition,
  SkillListItem,
  SkillMarketplaceListResponse,
  SkillReviewItem,
  SkillReviewListResponse,
  SkillInstallationItem,
  SkillValidateResponse,
  SkillAdminSettingsResponse,
  SkillAdminSettingsUpdate,
  SkillAdminReviewAction,
  SkillPendingReviewListResponse,
  SkillCategoriesResponse,
  SkillTagsResponse,
  SkillAISearchResponse,
} from './types'

// ===================== 技能广场 =====================

export const skillApi = {
  uploadSkill(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    return instance
      .post<SkillDefinition>('/skills/upload', formData)
      .then((r) => r.data)
  },

  updateSkillVersion(skillId: number, file: File) {
    const formData = new FormData()
    formData.append('file', file)
    return instance
      .put<SkillDefinition>(`/skills/${skillId}/upload`, formData)
      .then((r) => r.data)
  },

  getSkill(skillId: number) {
    return request.get<SkillDefinition>(`/skills/${skillId}`)
  },

  listMySkills(params?: { status?: number; limit?: number; offset?: number }) {
    return request.get<SkillMarketplaceListResponse>('/skills/mine', params as Record<string, unknown>)
  },

  listMarketplace(params?: {
    keyword?: string
    category?: string
    tags?: string
    sort?: string
    limit?: number
    offset?: number
  }) {
    return request.get<SkillMarketplaceListResponse>('/skills/marketplace', params as Record<string, unknown>)
  },

  deleteSkill(skillId: number) {
    return request.delete<{ success: boolean; message: string }>(`/skills/${skillId}`)
  },

  downloadSkill(skillId: number) {
    return request.download(`/skills/${skillId}/download`)
  },

  publishSkill(skillId: number) {
    return request.post<SkillDefinition>(`/skills/${skillId}/publish`)
  },

  unpublishSkill(skillId: number) {
    return request.post<SkillDefinition>(`/skills/${skillId}/unpublish`)
  },

  installSkill(skillId: number, agentId: number) {
    return request.post<SkillInstallationItem>(`/skills/${skillId}/install`, { agent_id: agentId })
  },

  uninstallSkill(skillId: number, agentId: number) {
    return request.delete<{ success: boolean; message: string }>(`/skills/${skillId}/install/${agentId}`)
  },

  listInstalled(agentId: number) {
    return request.get<SkillInstallationItem[]>(`/skills/installed/${agentId}`)
  },

  createReview(skillId: number, rating: number, content?: string) {
    return request.post<SkillReviewItem>(`/skills/${skillId}/reviews`, { rating, content })
  },

  listReviews(skillId: number, params?: { limit?: number; offset?: number }) {
    return request.get<SkillReviewListResponse>(`/skills/${skillId}/reviews`, params as Record<string, unknown>)
  },

  deleteReview(skillId: number) {
    return request.delete<{ success: boolean; message: string }>(`/skills/${skillId}/reviews`)
  },

  validate(content: string) {
    return request.post<SkillValidateResponse>('/skills/validate', { content })
  },

  // ==================== 管理员接口 ====================

  getAdminSettings() {
    return request.get<SkillAdminSettingsResponse>('/skills/admin/settings')
  },

  updateAdminSettings(data: SkillAdminSettingsUpdate) {
    return request.put<SkillAdminSettingsResponse>('/skills/admin/settings', data)
  },

  listReviewModels() {
    return request.get<string[]>('/skills/admin/models')
  },

  listPendingReviews(params?: { limit?: number; offset?: number }) {
    return request.get<SkillPendingReviewListResponse>('/skills/admin/reviews', params as Record<string, unknown>)
  },

  approveSkill(skillId: number) {
    return request.post<{ success: boolean; review_status: number }>(`/skills/admin/reviews/${skillId}/approve`)
  },

  rejectSkill(skillId: number, data?: SkillAdminReviewAction) {
    return request.post<{ success: boolean; review_status: number }>(`/skills/admin/reviews/${skillId}/reject`, data || {})
  },

  // ==================== 分类和标签 ====================

  listCategories() {
    return request.get<SkillCategoriesResponse>('/skills/categories')
  },

  listTags() {
    return request.get<SkillTagsResponse>('/skills/tags')
  },

  // ==================== AI 搜索 ====================

  aiSearch(data: { query: string; limit?: number; offset?: number }) {
    return request.post<SkillAISearchResponse>('/skills/ai-search', data)
  },
}
