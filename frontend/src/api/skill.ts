import { request } from './index'
import instance from './index'
import type {
  SkillDefinition,
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

/**
 * skill API
 *
 * 技能广场：上传/版本更新/发布下架、安装到 Agent、评价、审核（管理员）、分类标签与 AI 搜索
 */
export const skillApi = {
  /** 上传技能压缩包（SKILL.md frontmatter 定义，服务端校验） */
  uploadSkill(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    return instance.post<SkillDefinition>('/skills/upload', formData).then((r) => r.data)
  },

  /** 为已有技能上传新版本压缩包 */
  updateSkillVersion(skillId: number, file: File) {
    const formData = new FormData()
    formData.append('file', file)
    return instance.put<SkillDefinition>(`/skills/${skillId}/upload`, formData).then((r) => r.data)
  },

  /** 技能详情 */
  getSkill(skillId: number) {
    return request.get<SkillDefinition>(`/skills/${skillId}`)
  },

  /** 我发布的技能列表（可按审核状态过滤） */
  listMySkills(params?: { status?: number; limit?: number; offset?: number }) {
    return request.get<SkillMarketplaceListResponse>(
      '/skills/mine',
      params as Record<string, unknown>,
    )
  },

  /** 广场公开技能列表（关键字/分类/标签过滤 + 排序分页） */
  listMarketplace(params?: {
    keyword?: string
    category?: string
    tags?: string
    sort?: string
    limit?: number
    offset?: number
  }) {
    return request.get<SkillMarketplaceListResponse>(
      '/skills/marketplace',
      params as Record<string, unknown>,
    )
  },

  /** 删除自己的技能 */
  deleteSkill(skillId: number) {
    return request.delete<{ success: boolean; message: string }>(`/skills/${skillId}`)
  },

  /** 下载技能压缩包 */
  downloadSkill(skillId: number) {
    return request.download(`/skills/${skillId}/download`)
  },

  /** 提交审核并上架（DRAFT/PENDING → 上架可见） */
  publishSkill(skillId: number) {
    return request.post<SkillDefinition>(`/skills/${skillId}/publish`)
  },

  /** 下架（广场不再展示，已安装不受影响） */
  unpublishSkill(skillId: number) {
    return request.post<SkillDefinition>(`/skills/${skillId}/unpublish`)
  },

  /** 把技能安装到指定 Agent */
  installSkill(skillId: number, agentId: number) {
    return request.post<SkillInstallationItem>(`/skills/${skillId}/install`, { agent_id: agentId })
  },

  /** 从指定 Agent 卸载技能 */
  uninstallSkill(skillId: number, agentId: number) {
    return request.delete<{ success: boolean; message: string }>(
      `/skills/${skillId}/install/${agentId}`,
    )
  },

  /** 某 Agent 已安装的技能清单 */
  listInstalled(agentId: number) {
    return request.get<SkillInstallationItem[]>(`/skills/installed/${agentId}`)
  },

  /** 发表评价（1-5 星评分 + 可选内容） */
  createReview(skillId: number, rating: number, content?: string) {
    return request.post<SkillReviewItem>(`/skills/${skillId}/reviews`, { rating, content })
  },

  /** 技能评价列表（分页） */
  listReviews(skillId: number, params?: { limit?: number; offset?: number }) {
    return request.get<SkillReviewListResponse>(
      `/skills/${skillId}/reviews`,
      params as Record<string, unknown>,
    )
  },

  /** 删除自己对该技能的评价 */
  deleteReview(skillId: number) {
    return request.delete<{ success: boolean; message: string }>(`/skills/${skillId}/reviews`)
  },

  /** 上传前本地校验 SKILL.md 内容（返回错误清单与解析结果，不落库） */
  validate(content: string) {
    return request.post<SkillValidateResponse>('/skills/validate', { content })
  },

  // ==================== 管理员接口 ====================

  /** 审核设置（LLM 自动审开关与所用模型） */
  getAdminSettings() {
    return request.get<SkillAdminSettingsResponse>('/skills/admin/settings')
  },

  /** 更新审核设置 */
  updateAdminSettings(data: SkillAdminSettingsUpdate) {
    return request.put<SkillAdminSettingsResponse>('/skills/admin/settings', data)
  },

  /** 可选审核模型名单 */
  listReviewModels() {
    return request.get<string[]>('/skills/admin/models')
  },

  /** 待审核技能列表（分页） */
  listPendingReviews(params?: { limit?: number; offset?: number }) {
    return request.get<SkillPendingReviewListResponse>(
      '/skills/admin/reviews',
      params as Record<string, unknown>,
    )
  },

  /** 审核通过 */
  approveSkill(skillId: number) {
    return request.post<{ success: boolean; review_status: number }>(
      `/skills/admin/reviews/${skillId}/approve`,
    )
  },

  /** 审核驳回（可附原因） */
  rejectSkill(skillId: number, data?: SkillAdminReviewAction) {
    return request.post<{ success: boolean; review_status: number }>(
      `/skills/admin/reviews/${skillId}/reject`,
      data || {},
    )
  },

  // ==================== 分类和标签 ====================

  /** 技能分类清单（广场筛选项） */
  listCategories() {
    return request.get<SkillCategoriesResponse>('/skills/categories')
  },

  /** 技能标签清单（广场筛选项） */
  listTags() {
    return request.get<SkillTagsResponse>('/skills/tags')
  },

  // ==================== AI 搜索 ====================

  /** 语义搜索技能（LLM 理解意图后匹配，非关键字检索） */
  aiSearch(data: { query: string; limit?: number; offset?: number }) {
    return request.post<SkillAISearchResponse>('/skills/ai-search', data)
  },
}
