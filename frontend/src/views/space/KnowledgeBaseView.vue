<template>
  <div class="knowledge-base-view">
    <!-- 批量操作栏 -->
    <div v-if="selectedIds.length > 0" class="batch-bar">
      <span class="batch-count">已选 {{ selectedIds.length }} 项</span>
      <el-button size="small" @click="clearSelection">取消选择</el-button>
      <el-button type="danger" size="small" @click="handleBatchDelete">
        批量删除
      </el-button>
    </div>

    <!-- 知识库卡片网格 -->
    <div v-loading="loading" class="kb-grid">
      <div
        v-for="(kb, index) in knowledgeBases"
        :key="kb.id"
        class="kb-card"
        :class="{ selected: selectedIds.includes(kb.id) }"
      >
        <div class="kb-card-body" @click="goToDocuments(kb.id)">
          <!-- 头部：名称 + 状态 -->
          <div class="kb-card-header">
            <div class="kb-card-title-row">
              <div class="kb-color-dot" :style="{ background: getColor(index) }" />
              <h4 class="kb-name">{{ kb.name }}</h4>
            </div>
            <span class="kb-status-label">{{ kb.status === 1 ? '活跃' : '已归档' }}</span>
          </div>

          <!-- 描述 -->
          <p class="kb-desc">{{ kb.config?.description || '暂无描述' }}</p>

          <!-- 元信息 -->
          <div class="kb-meta">
            <span class="meta-item">
              <el-icon :size="14"><Document /></el-icon>
              {{ kb.stats?.document_count ?? 0 }} 文档
            </span>
          </div>
        </div>

        <!-- 操作按钮（hover 显示） -->
        <div class="kb-actions">
          <el-tooltip content="编辑" placement="top">
            <el-button size="small" circle aria-label="编辑" @click.stop="showEditDialog(kb)">
              <el-icon><Edit /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip content="配置" placement="top">
            <el-button size="small" circle aria-label="配置" @click.stop="goConfig(kb)">
              <el-icon><Setting /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip v-if="kb.status === 1" content="归档" placement="top">
            <el-button size="small" circle aria-label="归档" @click.stop="handleArchive(kb)">
              <el-icon><FolderOpened /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip v-else content="激活" placement="top">
            <el-button size="small" circle aria-label="激活" @click.stop="handleUnarchive(kb)">
              <el-icon><FolderAdd /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip content="删除" placement="top">
            <el-button size="small" circle aria-label="删除" @click.stop="handleDeleteSingle(kb)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </el-tooltip>
        </div>
      </div>

      <!-- 空状态 -->
      <EmptyState
        v-if="!loading && knowledgeBases.length === 0"
        variant="default"
        title="暂无知识库"
        description="创建知识库，上传文档，开始构建你的知识体系"
      >
        <el-button type="primary" @click="handleQuickCreateKb">
          新建知识库
        </el-button>
      </EmptyState>
    </div>

    <!-- 编辑知识库弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      title="编辑知识库"
      width="480px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="formData" :rules="formRules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="formData.name" placeholder="请输入知识库名称" maxlength="100" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="formData.description"
            type="textarea"
            :rows="3"
            placeholder="请输入知识库描述（可选）"
            maxlength="500"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handleSubmit">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Edit, Setting, FolderOpened, FolderAdd, Delete } from '@element-plus/icons-vue'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import type { KnowledgeBase } from '@/api/types'
import type { FormInstance, FormRules } from 'element-plus'
import EmptyState from '@/components/common/EmptyState.vue'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))

const loading = ref(false)
const submitLoading = ref(false)
const dialogVisible = ref(false)
const editKbId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const knowledgeBases = ref<KnowledgeBase[]>([])
const selectedIds = ref<number[]>([])

const formData = reactive({
  name: '',
  description: '',
})

const formRules: FormRules = {
  name: [
    { required: true, message: '请输入知识库名称', trigger: 'blur' },
    { min: 1, max: 100, message: '名称长度 1-100 字符', trigger: 'blur' },
  ],
}

// === 色板 ===

const colorPalette = [
  '#6366F1',
  '#10B981',
  '#EF4444',
  '#7C3AED',
  '#F59E0B',
  '#6366F1',
  '#F97316',
  '#14B8A6',
]

function getColor(index: number): string {
  return colorPalette[index % colorPalette.length] ?? '#6366F1'
}

// === 跳转配置向导页 ===

function goConfig(kb: KnowledgeBase) {
  router.push({ name: 'KbConfig', params: { id: spaceId.value, kbId: kb.id } })
}

// === 选择 ===

function toggleSelect(kbId: number, checked: boolean) {
  if (checked) {
    if (!selectedIds.value.includes(kbId)) {
      selectedIds.value.push(kbId)
    }
  } else {
    selectedIds.value = selectedIds.value.filter((id) => id !== kbId)
  }
}

function clearSelection() {
  selectedIds.value = []
}

// === 知识库列表 ===

async function fetchKnowledgeBases() {
  loading.value = true
  try {
    const data = await knowledgeBaseApi.getKnowledgeBases(spaceId.value)
    knowledgeBases.value = data.items || []
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '获取知识库列表失败')
  } finally {
    loading.value = false
  }
}

// === 编辑 ===

function showEditDialog(kb: KnowledgeBase) {
  editKbId.value = kb.id
  formData.name = kb.name
  formData.description = kb.config?.description || ''
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!formRef.value || !editKbId.value) return

  await formRef.value.validate(async (valid) => {
    if (!valid) return

    submitLoading.value = true
    try {
      await knowledgeBaseApi.updateKnowledgeBase(spaceId.value, editKbId.value!, {
        name: formData.name,
        config: formData.description ? { description: formData.description } : undefined,
      })
      ElMessage.success('知识库更新成功')
      dialogVisible.value = false
      fetchKnowledgeBases()
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: { message?: string } } } }
      ElMessage.error(err.response?.data?.error?.message || '操作失败')
    } finally {
      submitLoading.value = false
    }
  })
}

// === 归档/激活 ===

async function handleArchive(kb: KnowledgeBase) {
  try {
    await ElMessageBox.confirm(`确定要归档知识库 "${kb.name}" 吗？`, '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await knowledgeBaseApi.updateKnowledgeBase(spaceId.value, kb.id, { status: 2 })
    ElMessage.success('知识库已归档')
    fetchKnowledgeBases()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      const err = error as { response?: { data?: { error?: { message?: string } } } }
      ElMessage.error(err.response?.data?.error?.message || '操作失败')
    }
  }
}

async function handleUnarchive(kb: KnowledgeBase) {
  try {
    await knowledgeBaseApi.updateKnowledgeBase(spaceId.value, kb.id, { status: 1 })
    ElMessage.success('知识库已激活')
    fetchKnowledgeBases()
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '操作失败')
  }
}

// === 批量删除 ===

async function handleBatchDelete() {
  if (selectedIds.value.length === 0) return

  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedIds.value.length} 个知识库吗？此操作将删除所有关联文档，且不可恢复。`,
      '批量删除',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'error',
      },
    )
  } catch {
    return
  }

  const ids = [...selectedIds.value]
  let failCount = 0

  for (const id of ids) {
    try {
      await knowledgeBaseApi.deleteKnowledgeBase(spaceId.value, id)
    } catch {
      failCount++
    }
  }

  selectedIds.value = []

  if (failCount === 0) {
    ElMessage.success(`已删除 ${ids.length} 个知识库`)
  } else {
    ElMessage.warning(`${ids.length - failCount} 个删除成功，${failCount} 个删除失败`)
  }

  fetchKnowledgeBases()
}

// === 单个删除 ===

async function handleDeleteSingle(kb: KnowledgeBase) {
  try {
    await ElMessageBox.confirm(
      `确定要删除知识库「${kb.name}」吗？此操作将删除该知识库下的所有文档，且不可恢复。`,
      '删除知识库',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'error',
      },
    )
  } catch {
    return
  }

  try {
    await knowledgeBaseApi.deleteKnowledgeBase(spaceId.value, kb.id)
    ElMessage.success(`已删除知识库「${kb.name}」`)
    fetchKnowledgeBases()
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '删除失败')
  }
}

function goToDocuments(kbId: number) {
  router.push(`/home/spaces/${spaceId.value}/knowledge-bases/${kbId}/documents`)
}

async function handleQuickCreateKb() {
  try {
    const { value } = await ElMessageBox.prompt('请输入知识库名称', '新建知识库', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputPattern: /\S/,
      inputErrorMessage: '名称不能为空',
    })
    if (value) {
      await knowledgeBaseApi.createKnowledgeBase(spaceId.value, { name: value.trim() })
      ElMessage.success('知识库创建成功')
      fetchKnowledgeBases()
    }
  } catch {
    // 用户取消
  }
}

onMounted(() => {
  fetchKnowledgeBases()
})
</script>

<style scoped>
.knowledge-base-view {
  padding-top: var(--space-2);
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--color-danger-subtle);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-danger-subtle);
}

.batch-count {
  font-size: var(--text-sm);
  color: var(--color-danger);
  font-weight: var(--weight-medium);
}

.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-4);
}

.kb-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-xs);
  transition: border-color var(--transition-fast), background-color var(--transition-fast), box-shadow var(--transition-fast);
  display: flex;
  flex-direction: row;
}

.kb-card:hover {
  border-color: var(--color-text-faint);
  background: var(--color-bg-card-elevated);
  box-shadow: var(--shadow-sm);
}

.kb-card.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
}

.kb-card-body {
  padding: var(--space-4) var(--space-5);
  cursor: pointer;
  flex: 1;
  min-width: 0;
}

.kb-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-3);
}

.kb-card-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  flex: 1;
}

.kb-color-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.kb-name {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color var(--transition-fast);
}

.kb-card:hover .kb-name {
  color: var(--color-primary);
}

.kb-status-label {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-weight: var(--weight-medium);
}

.kb-desc {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: var(--leading-relaxed);
}

.kb-meta {
  display: flex;
  gap: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.meta-item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.kb-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border-top: 1px solid var(--color-border-light);
  opacity: 0;
  transition: opacity var(--transition-base);
}

.kb-card:hover .kb-actions {
  opacity: 1;
}
</style>
