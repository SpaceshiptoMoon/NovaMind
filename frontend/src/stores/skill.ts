import { ref } from 'vue'
import { defineStore } from 'pinia'
import { skillApi } from '@/api/skill'
import type {
  SkillDefinition,
  SkillListItem,
  SkillReviewItem,
  SkillAdminSettingsResponse,
  SkillAISearchParsedQuery,
} from '@/api/types'

export const useSkillStore = defineStore('skill', () => {
  // 广场列表
  const marketplaceSkills = ref<SkillListItem[]>([])
  const marketplaceTotal = ref(0)
  const marketplaceLoading = ref(false)

  // 我的技能
  const mySkills = ref<SkillDefinition[]>([])
  const mySkillsTotal = ref(0)

  // 当前查看的技能
  const currentSkill = ref<SkillDefinition | null>(null)

  // 评价列表
  const reviews = ref<SkillReviewItem[]>([])
  const reviewsTotal = ref(0)

  // 上传状态
  const uploading = ref(false)
  const uploadProgress = ref(0)

  // 管理员 — 审查设置
  const adminSettings = ref<SkillAdminSettingsResponse | null>(null)

  // 管理员 — 待审核列表
  const pendingReviews = ref<SkillListItem[]>([])
  const pendingReviewsTotal = ref(0)

  // 分类列表（从 API 获取）
  const categories = ref<string[]>([])
  const categoriesLoading = ref(false)

  // 标签列表（从 API 获取）
  const availableTags = ref<string[]>([])
  const tagsLoading = ref(false)

  // AI 搜索
  const aiSearchResults = ref<SkillListItem[]>([])
  const aiSearchTotal = ref(0)
  const aiSearchExplanation = ref('')
  const aiSearchParsedQuery = ref<SkillAISearchParsedQuery | null>(null)
  const aiSearchLoading = ref(false)

  async function fetchMarketplace(params?: {
    keyword?: string
    category?: string
    tags?: string
    sort?: string
    limit?: number
    offset?: number
  }) {
    marketplaceLoading.value = true
    try {
      const res = await skillApi.listMarketplace(params)
      marketplaceSkills.value = res.items || []
      marketplaceTotal.value = res.total
    } catch {
      marketplaceSkills.value = []
      marketplaceTotal.value = 0
    } finally {
      marketplaceLoading.value = false
    }
  }

  async function fetchMySkills(params?: { status?: number; limit?: number; offset?: number }) {
    try {
      const res = await skillApi.listMySkills(params)
      mySkills.value = (res.items as unknown as SkillDefinition[]) || []
      mySkillsTotal.value = res.total
    } catch {
      mySkills.value = []
      mySkillsTotal.value = 0
    }
  }

  async function fetchSkillDetail(skillId: number) {
    try {
      currentSkill.value = await skillApi.getSkill(skillId)
    } catch {
      currentSkill.value = null
    }
  }

  async function uploadSkill(file: File) {
    uploading.value = true
    uploadProgress.value = 0
    try {
      const skill = await skillApi.uploadSkill(file)
      return skill
    } finally {
      uploading.value = false
      uploadProgress.value = 100
    }
  }

  async function updateSkillVersion(skillId: number, file: File) {
    uploading.value = true
    try {
      return await skillApi.updateSkillVersion(skillId, file)
    } finally {
      uploading.value = false
    }
  }

  async function publishSkill(skillId: number) {
    return await skillApi.publishSkill(skillId)
  }

  async function unpublishSkill(skillId: number) {
    return await skillApi.unpublishSkill(skillId)
  }

  async function installSkill(skillId: number, agentId: number) {
    return await skillApi.installSkill(skillId, agentId)
  }

  async function uninstallSkill(skillId: number, agentId: number) {
    return await skillApi.uninstallSkill(skillId, agentId)
  }

  async function deleteSkill(skillId: number) {
    return await skillApi.deleteSkill(skillId)
  }

  async function fetchReviews(skillId: number, params?: { limit?: number; offset?: number }) {
    try {
      const res = await skillApi.listReviews(skillId, params)
      reviews.value = res.items || []
      reviewsTotal.value = res.total
    } catch {
      reviews.value = []
      reviewsTotal.value = 0
    }
  }

  async function submitReview(skillId: number, rating: number, content?: string) {
    return await skillApi.createReview(skillId, rating, content)
  }

  async function deleteReview(skillId: number) {
    return await skillApi.deleteReview(skillId)
  }

  // ==================== 管理员 ====================

  async function fetchAdminSettings() {
    try {
      const result = await skillApi.getAdminSettings()
      adminSettings.value = result
      return result
    } catch {
      adminSettings.value = null
      return null
    }
  }

  async function updateAdminSettings(enabled: boolean, model?: string | null) {
    adminSettings.value = await skillApi.updateAdminSettings({
      llm_review_enabled: enabled,
      llm_review_model: model ?? null,
    })
  }

  async function fetchReviewModels() {
    return await skillApi.listReviewModels()
  }

  async function fetchPendingReviews(params?: { limit?: number; offset?: number }) {
    try {
      const res = await skillApi.listPendingReviews(params)
      pendingReviews.value = res.items || []
      pendingReviewsTotal.value = res.total
    } catch {
      pendingReviews.value = []
      pendingReviewsTotal.value = 0
    }
  }

  async function approveSkill(skillId: number) {
    return await skillApi.approveSkill(skillId)
  }

  async function rejectSkill(skillId: number, reason?: string) {
    return await skillApi.rejectSkill(skillId, reason ? { reason } : undefined)
  }

  // ==================== 分类和标签 ====================

  async function fetchCategories() {
    categoriesLoading.value = true
    try {
      const res = await skillApi.listCategories()
      categories.value = res.categories || []
    } catch {
      categories.value = []
    } finally {
      categoriesLoading.value = false
    }
  }

  async function fetchTags() {
    tagsLoading.value = true
    try {
      const res = await skillApi.listTags()
      availableTags.value = res.tags || []
    } catch {
      availableTags.value = []
    } finally {
      tagsLoading.value = false
    }
  }

  // ==================== AI 搜索 ====================

  async function aiSearch(params: { query: string; limit?: number; offset?: number }) {
    aiSearchLoading.value = true
    try {
      const res = await skillApi.aiSearch(params)
      aiSearchResults.value = res.items || []
      aiSearchTotal.value = res.total
      aiSearchExplanation.value = res.explanation
      aiSearchParsedQuery.value = res.ai_query
    } catch {
      aiSearchResults.value = []
      aiSearchTotal.value = 0
      aiSearchExplanation.value = ''
      aiSearchParsedQuery.value = null
    } finally {
      aiSearchLoading.value = false
    }
  }

  return {
    marketplaceSkills,
    marketplaceTotal,
    marketplaceLoading,
    mySkills,
    mySkillsTotal,
    currentSkill,
    reviews,
    reviewsTotal,
    uploading,
    uploadProgress,
    categories,
    categoriesLoading,
    availableTags,
    tagsLoading,
    aiSearchResults,
    aiSearchTotal,
    aiSearchExplanation,
    aiSearchParsedQuery,
    aiSearchLoading,
    adminSettings,
    pendingReviews,
    pendingReviewsTotal,
    fetchMarketplace,
    fetchMySkills,
    fetchSkillDetail,
    uploadSkill,
    updateSkillVersion,
    publishSkill,
    unpublishSkill,
    installSkill,
    uninstallSkill,
    deleteSkill,
    fetchReviews,
    submitReview,
    deleteReview,
    fetchCategories,
    fetchTags,
    aiSearch,
    fetchAdminSettings,
    updateAdminSettings,
    fetchReviewModels,
    fetchPendingReviews,
    approveSkill,
    rejectSkill,
  }
})
