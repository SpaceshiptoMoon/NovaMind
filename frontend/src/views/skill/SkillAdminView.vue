<template>
  <div class="skill-admin">
    <PageHeader title="技能审核">
      <el-button @click="router.push('/home/workspace/skills')">
        <el-icon><ArrowLeft /></el-icon>
        返回广场
      </el-button>
    </PageHeader>

    <!-- 审查设置 -->
    <div class="settings-card">
      <h3 class="section-title">自动审查设置</h3>
      <div class="setting-row">
        <span>LLM 安全审查</span>
        <el-switch v-model="llmReviewEnabled" @change="handleSaveSettings" />
      </div>
      <div class="setting-row setting-model">
        <span>审查模型</span>
        <el-select
          v-model="llmReviewModel"
          placeholder="使用用户默认模型"
          clearable
          class="model-select"
          @change="handleSaveSettings"
        >
          <el-option v-for="m in availableModels" :key="m" :label="m" :value="m" />
          <template #empty>暂无可用模型</template>
        </el-select>
      </div>
      <div v-if="settingsLoading" class="loading-hint">加载中...</div>
    </div>

    <!-- 待审核列表 -->
    <h3 class="section-title section-spacing">待审核技能</h3>
    <div v-loading="skillStore.marketplaceLoading" class="review-list">
      <div v-for="skill in skillStore.pendingReviews" :key="skill.id" class="review-card">
        <div class="review-main">
          <div class="review-icon">{{ skill.icon || '⚡' }}</div>
          <div class="review-info">
            <h4>{{ skill.display_name }}</h4>
            <p>{{ skill.description }}</p>
            <span class="review-meta">by {{ skill.author_name || '未知' }} · 版本 {{ skill.version }}</span>
          </div>
        </div>
        <div class="review-actions">
          <el-button type="success" size="small" @click="handleApprove(skill.id)">
            批准
          </el-button>
          <el-button type="danger" size="small" @click="handleReject(skill.id)">
            拒绝
          </el-button>
        </div>
      </div>

      <el-empty v-if="!skillStore.marketplaceLoading && skillStore.pendingReviews.length === 0" description="暂无待审核技能" />
    </div>

    <!-- 分页 -->
    <div v-if="skillStore.pendingReviewsTotal > pageSize" class="pagination-area">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="skillStore.pendingReviewsTotal"
        layout="prev, pager, next"
        @current-change="handlePageChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { useSkillStore } from '@/stores/skill'
import PageHeader from '@/components/common/PageHeader.vue'

const router = useRouter()
const skillStore = useSkillStore()

const llmReviewEnabled = ref(false)
const llmReviewModel = ref<string | null>(null)
const availableModels = ref<string[]>([])
const settingsLoading = ref(true)
const currentPage = ref(1)
const pageSize = 20

onMounted(async () => {
  try {
    const [settings, models] = await Promise.all([
      skillStore.fetchAdminSettings(),
      skillStore.fetchReviewModels(),
    ])
    if (settings) {
      llmReviewEnabled.value = settings.llm_review_enabled
      llmReviewModel.value = settings.llm_review_model
    }
    if (models) availableModels.value = models
  } catch {
    // 使用默认值
  } finally {
    settingsLoading.value = false
  }
  skillStore.fetchPendingReviews({ limit: pageSize, offset: 0 })
})

async function handleSaveSettings() {
  try {
    await skillStore.updateAdminSettings(llmReviewEnabled.value, llmReviewModel.value)
    ElMessage.success('设置已更新')
  } catch (e: any) {
    ElMessage.error(e?.message || '更新失败')
  }
}

async function handleApprove(skillId: number) {
  try {
    await ElMessageBox.confirm('确认批准该技能？', '批准确认', { type: 'success' })
    await skillStore.approveSkill(skillId)
    ElMessage.success('已批准')
    skillStore.fetchPendingReviews({ limit: pageSize, offset: (currentPage.value - 1) * pageSize })
  } catch {
    // cancelled or error
  }
}

async function handleReject(skillId: number) {
  try {
    const { value: reason } = await ElMessageBox.prompt('请输入拒绝原因（可选）', '拒绝确认', {
      type: 'warning',
      inputPlaceholder: '拒绝原因...',
      confirmButtonText: '拒绝',
    })
    await skillStore.rejectSkill(skillId, reason || undefined)
    ElMessage.success('已拒绝')
    skillStore.fetchPendingReviews({ limit: pageSize, offset: (currentPage.value - 1) * pageSize })
  } catch {
    // cancelled
  }
}

function handlePageChange(page: number) {
  skillStore.fetchPendingReviews({ limit: pageSize, offset: (page - 1) * pageSize })
}
</script>

<style scoped>
.skill-admin {
  position: absolute;
  inset: 0;
  padding: var(--space-6);
  overflow-y: auto;
}

.settings-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  padding: var(--space-5);
  margin-top: var(--space-5);
}

.section-title {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  margin: 0 0 var(--space-4);
}

.section-spacing {
  margin-top: var(--space-6);
}

.setting-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.setting-model {
  margin-top: var(--space-3);
}

.model-select {
  width: 260px;
}

.loading-hint {
  font-size: var(--text-sm);
  color: var(--color-text-faint);
  margin-top: var(--space-2);
}

.review-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 200px;
}

.review-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  padding: var(--space-4) var(--space-5);
  transition: all var(--transition-fast);
}

.review-card:hover {
  border-color: var(--color-border);
  background: var(--color-bg-hover);
}

.review-main {
  display: flex;
  gap: var(--space-4);
  align-items: flex-start;
  flex: 1;
  min-width: 0;
}

.review-icon {
  font-size: var(--text-3xl);
  flex-shrink: 0;
}

.review-info {
  min-width: 0;
}

.review-info h4 {
  margin: 0 0 var(--space-1);
  font-size: var(--text-md);
  font-weight: var(--weight-medium);
}

.review-info p {
  margin: 0 0 var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-meta {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

.review-actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
  margin-left: var(--space-4);
}

.pagination-area {
  display: flex;
  justify-content: center;
  margin-top: var(--space-6);
}
</style>
