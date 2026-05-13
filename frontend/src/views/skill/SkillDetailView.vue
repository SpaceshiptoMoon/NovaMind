<template>
  <div class="skill-detail">
    <div v-if="skill" class="detail-content">
      <!-- 头部 -->
      <div class="detail-header">
        <el-button text @click="router.push('/home/workspace/skills')">
          <el-icon><ArrowLeft /></el-icon> 返回广场
        </el-button>
      </div>

      <!-- 元数据区 -->
      <div class="detail-meta">
        <div class="meta-top">
          <span class="skill-icon">{{ skill.icon || '⚡' }}</span>
          <div class="meta-info">
            <h1>{{ skill.display_name }}</h1>
            <div class="meta-tags">
              <el-tag v-if="skill.skill_source === 'builtin'" type="warning">内置</el-tag>
              <el-tag v-else>{{ skill.category || '通用' }}</el-tag>
              <el-tag v-for="tag in (skill.tags || [])" :key="tag" size="small" type="info">{{ tag }}</el-tag>
              <span class="meta-stat">v{{ skill.version }}</span>
              <el-tag :type="reviewStatusType" size="small">{{ reviewStatusLabel }}</el-tag>
            </div>
          </div>
        </div>

        <p class="skill-description">{{ skill.description }}</p>

        <!-- 审查结果 -->
        <div v-if="skill.review_result && (skill.review_result.llm?.reason || skill.review_result.admin_reason)" class="review-notice">
          <div v-if="skill.review_result.admin_reason" class="review-line">
            <span class="review-label">管理员备注：</span>
            <span>{{ skill.review_result.admin_reason }}</span>
          </div>
          <div v-if="skill.review_result.llm?.reason" class="review-line">
            <span class="review-label">审查说明：</span>
            <span>{{ skill.review_result.llm.reason }}</span>
          </div>
        </div>

        <div class="meta-actions">
          <div class="meta-stats">
            <span><el-icon><Download /></el-icon> {{ skill.install_count }} 次安装</span>
            <span><el-icon><Star /></el-icon> {{ skill.rating_avg.toFixed(1) }} ({{ skill.rating_count }} 评价)</span>
          </div>
          <div class="action-buttons">
            <template v-if="isOwner && fromMine">
              <el-button v-if="skill.status === 0" :disabled="!canPublish" @click="handlePublish">
                发布
              </el-button>
              <el-button v-else type="warning" @click="handleUnpublish">取消发布</el-button>
              <el-upload :show-file-list="false" :before-upload="handleUpdateVersion" accept=".zip">
                <el-button>更新版本</el-button>
              </el-upload>
              <el-button type="danger" @click="handleDelete">删除</el-button>
            </template>
            <template v-else>
              <el-button type="primary" @click="openInstallDialog">安装到 Agent</el-button>
              <el-button @click="handleDownload">下载</el-button>
            </template>
          </div>
        </div>
      </div>

      <!-- 允许的工具 -->
      <div v-if="skill.allowed_tools?.length" class="detail-section">
        <h3>引用工具</h3>
        <div class="tool-list">
          <el-tag v-for="tool in skill.allowed_tools" :key="tool" type="success">{{ tool }}</el-tag>
        </div>
      </div>

      <!-- Markdown 指令预览 -->
      <div class="detail-section">
        <h3>技能指令</h3>
        <div class="markdown-preview">
          <pre>{{ skill.body_markdown }}</pre>
        </div>
      </div>

      <!-- 评价区 -->
      <div class="detail-section">
        <h3>评价 ({{ reviewsTotal }})</h3>
        <div class="review-form" v-if="!isOwner">
          <el-rate v-model="newReviewRating" :colors="['#F7BA2A', '#F7BA2A', '#F7BA2A']" />
          <el-input v-model="newReviewContent" type="textarea" :rows="2" placeholder="写点评价..." />
          <el-button type="primary" size="small" @click="handleSubmitReview" :disabled="!newReviewRating">提交</el-button>
        </div>
        <div class="review-list">
          <div v-for="review in skillStore.reviews" :key="review.id" class="review-item">
            <div class="review-header">
              <span class="review-user">{{ review.user_name || `用户${review.user_id}` }}</span>
              <el-rate :model-value="review.rating" disabled size="small" />
            </div>
            <p v-if="review.content" class="review-content">{{ review.content }}</p>
          </div>
          <el-empty v-if="skillStore.reviews.length === 0" description="暂无评价" />
        </div>
      </div>
    </div>

    <el-empty v-else-if="!loading" description="技能不存在" />

    <!-- 安装对话框 -->
    <el-dialog v-model="installDialogVisible" title="安装到 Agent" width="460px">
      <p style="margin-bottom: 16px">选择要安装此技能的 Agent：</p>
      <p style="color: var(--text-secondary); font-size: 13px; margin-bottom: 16px">
        安装后，技能的指令和声明的工具将自动注入 Agent 的 enabled_tools 中。
      </p>
      <div v-loading="agentsLoading" class="agent-select-list">
        <div
          v-for="agent in agents"
          :key="agent.id"
          class="agent-select-item"
          :class="{ selected: selectedAgentId === agent.id }"
          @click="selectedAgentId = agent.id"
        >
          <div class="agent-avatar-sm">{{ agent.name.charAt(0) }}</div>
          <div class="agent-info">
            <span class="agent-name">{{ agent.name }}</span>
            <span class="agent-desc">{{ agent.description || '暂无描述' }}</span>
          </div>
          <el-icon v-if="selectedAgentId === agent.id" class="check-icon"><Check /></el-icon>
        </div>
        <el-empty v-if="agents.length === 0 && !agentsLoading" description="暂无可用的智能体" />
      </div>
      <template #footer>
        <el-button @click="installDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="installing" :disabled="!selectedAgentId" @click="handleInstall">安装</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Download, Star, Check } from '@element-plus/icons-vue'
import { useSkillStore } from '@/stores/skill'
import { useAgentStore } from '@/stores/agent'
import { useUserStore } from '@/stores/user'
import { skillApi } from '@/api/skill'
import type { Agent } from '@/api/types'

const route = useRoute()
const router = useRouter()
const skillStore = useSkillStore()
const agentStore = useAgentStore()
const userStore = useUserStore()

const loading = ref(true)
const installDialogVisible = ref(false)
const installing = ref(false)
const agentsLoading = ref(false)
const selectedAgentId = ref<number | null>(null)
const newReviewRating = ref(0)
const newReviewContent = ref('')
const reviewsTotal = computed(() => skillStore.reviewsTotal)

const skill = computed(() => skillStore.currentSkill)
const fromMine = computed(() => route.query.from === 'mine')
const isOwner = computed(() => {
  return skill.value?.user_id != null && skill.value.user_id === userStore.user?.id
})
const agents = computed(() => agentStore.agents)

const canPublish = computed(() => {
  if (!skill.value) return false
  const rs = skill.value.review_status
  return rs === 1 // APPROVED
})

const reviewStatusType = computed(() => {
  const map: Record<number, 'success' | 'warning' | 'danger' | 'info'> = {
    0: 'info',    // PENDING
    1: 'success', // APPROVED
    2: 'warning', // SUSPICIOUS
    3: 'danger',  // REJECTED
  }
  return map[skill.value?.review_status ?? 0] || 'info'
})

const reviewStatusLabel = computed(() => {
  const map: Record<number, string> = {
    0: '待审查',
    1: '已通过',
    2: '待人工审核',
    3: '已拒绝',
  }
  return map[skill.value?.review_status ?? 0] || '未知'
})

onMounted(async () => {
  const skillId = Number(route.params.skillId)
  loading.value = true
  await Promise.all([
    skillStore.fetchSkillDetail(skillId),
    skillStore.fetchReviews(skillId),
  ])
  loading.value = false
})

watch(() => route.params.skillId, async (newId) => {
  if (newId) {
    loading.value = true
    await Promise.all([
      skillStore.fetchSkillDetail(Number(newId)),
      skillStore.fetchReviews(Number(newId)),
    ])
    loading.value = false
  }
})

async function handlePublish() {
  if (!skill.value) return
  try {
    await skillStore.publishSkill(skill.value.id)
    ElMessage.success('技能已发布')
    skillStore.fetchSkillDetail(skill.value.id)
  } catch (e: any) {
    ElMessage.error(e?.message || '发布失败')
  }
}

async function handleUnpublish() {
  if (!skill.value) return
  try {
    await skillStore.unpublishSkill(skill.value.id)
    ElMessage.success('已取消发布')
    skillStore.fetchSkillDetail(skill.value.id)
  } catch (e: any) {
    ElMessage.error(e?.message || '操作失败')
  }
}

async function handleDelete() {
  if (!skill.value) return
  try {
    await ElMessageBox.confirm('确定删除此技能？', '确认')
    await skillStore.deleteSkill(skill.value.id)
    ElMessage.success('技能已删除')
    router.push('/home/workspace/skills')
  } catch {}
}

async function handleUpdateVersion(file: File) {
  if (!skill.value || !file.name.endsWith('.zip')) {
    ElMessage.error('请上传 .zip 文件')
    return false
  }
  try {
    await skillStore.updateSkillVersion(skill.value.id, file)
    ElMessage.success('版本更新成功')
    skillStore.fetchSkillDetail(skill.value.id)
  } catch (e: any) {
    ElMessage.error(e?.message || '更新失败')
  }
  return false
}

async function handleDownload() {
  if (!skill.value) return
  try {
    const blob = await skillApi.downloadSkill(skill.value.id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${skill.value.name}.zip`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e: any) {
    ElMessage.error('下载失败')
  }
}

async function handleSubmitReview() {
  if (!skill.value || !newReviewRating.value) return
  try {
    await skillStore.submitReview(skill.value.id, newReviewRating.value, newReviewContent.value || undefined)
    ElMessage.success('评价已提交')
    newReviewRating.value = 0
    newReviewContent.value = ''
    skillStore.fetchReviews(skill.value.id)
  } catch (e: any) {
    ElMessage.error(e?.message || '评价失败')
  }
}

// ==================== 安装到 Agent ====================

async function openInstallDialog() {
  selectedAgentId.value = null
  installDialogVisible.value = true
  if (agentStore.agents.length === 0) {
    agentsLoading.value = true
    try {
      await agentStore.fetchAgents()
    } finally {
      agentsLoading.value = false
    }
  }
}

async function handleInstall() {
  if (!skill.value || !selectedAgentId.value) return
  installing.value = true
  try {
    await skillStore.installSkill(skill.value.id, selectedAgentId.value)
    ElMessage.success('安装成功')
    installDialogVisible.value = false
  } catch (e: any) {
    ElMessage.error(e?.message || '安装失败')
  } finally {
    installing.value = false
  }
}
</script>

<style scoped>
.skill-detail {
  position: absolute;
  inset: 0;
  padding: 24px;
  overflow-y: auto;
}

.detail-header {
  margin-bottom: 16px;
}

.detail-meta {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 24px;
  margin-bottom: 24px;
}

.meta-top {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
}

.skill-icon {
  font-size: 40px;
}

.meta-info h1 {
  font-size: 22px;
  margin: 0 0 8px;
}

.meta-tags {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.meta-stat {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.skill-description {
  color: var(--color-text-secondary);
  margin: 0 0 16px;
  line-height: 1.6;
}

.review-notice {
  background: var(--color-bg);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  margin-bottom: 16px;
  font-size: 13px;
  line-height: 1.6;
}

.review-line {
  margin-bottom: 4px;
}

.review-line:last-child {
  margin-bottom: 0;
}

.review-label {
  font-weight: 500;
  color: var(--color-text-secondary);
}

.meta-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.meta-stats {
  display: flex;
  gap: 16px;
  font-size: 14px;
  color: var(--color-text-secondary);
}

.meta-stats span {
  display: flex;
  align-items: center;
  gap: 4px;
}

.action-buttons {
  display: flex;
  gap: 8px;
}

.detail-section {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 20px;
  margin-bottom: 16px;
}

.detail-section h3 {
  font-size: 16px;
  margin: 0 0 12px;
}

.tool-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.markdown-preview {
  background: var(--color-bg);
  border-radius: var(--radius-md);
  padding: 16px;
  overflow-x: auto;
}

.markdown-preview pre {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.6;
  margin: 0;
}

.review-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--color-border);
}

.review-item {
  padding: 12px 0;
  border-bottom: 1px solid var(--color-border-light);
}

.review-item:last-child {
  border-bottom: none;
}

.review-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.review-user {
  font-weight: 500;
}

.review-content {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 4px 0 0;
}

/* ==================== Agent 选择列表 ==================== */

.agent-select-list {
  max-height: 320px;
  overflow-y: auto;
}

.agent-select-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.agent-select-item:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
}

.agent-select-item.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
}

.agent-avatar-sm {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-lg);
  background: var(--color-primary-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  color: var(--color-primary);
  flex-shrink: 0;
}

.agent-info {
  flex: 1;
  min-width: 0;
}

.agent-name {
  display: block;
  font-size: 14px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-desc {
  display: block;
  font-size: 12px;
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.check-icon {
  color: var(--color-primary);
  font-size: 18px;
  flex-shrink: 0;
}
</style>
