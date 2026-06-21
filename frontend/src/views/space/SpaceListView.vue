<template>
  <div class="space-list-view">
    <!-- 主内容区（全宽，空间切换收进顶部下拉） -->
    <main class="main-content">
      <!-- 空间首页（KB 列表）：完整空间栏 -->
      <div v-if="isSpaceHome" class="content-header content-header--full">
        <div class="header-left">
          <el-select
            :model-value="selectedSpaceId"
            placeholder="选择知识空间"
            class="space-select"
            filterable
            @change="handleSpaceChange"
          >
            <el-option-group v-if="spaceStore.spaces.length" label="我的空间">
              <el-option
                v-for="space in spaceStore.spaces"
                :key="space.id"
                :label="space.name"
                :value="space.id"
              >
                <span class="space-option-name">{{ space.name }}</span>
                <el-tag
                  v-if="space.config?.space_type === 'multimodal'"
                  size="small"
                  type="primary"
                  class="space-option-tag"
                >图片</el-tag>
              </el-option>
            </el-option-group>
            <el-option-group
              v-if="spaceStore.publicSpaces.length"
              label="公开空间"
            >
              <el-option
                v-for="space in spaceStore.publicSpaces"
                :key="space.id"
                :label="space.name"
                :value="space.id"
              >
                <span class="space-option-name">{{ space.name }}</span>
                <el-tag
                  v-if="space.config?.space_type === 'multimodal'"
                  size="small"
                  type="primary"
                  class="space-option-tag"
                >图片</el-tag>
              </el-option>
            </el-option-group>
          </el-select>
          <BreadcrumbNav v-if="selectedSpaceId" />
        </div>
        <div class="header-actions">
          <el-button
            v-if="selectedSpaceId"
            type="primary"
            size="small"
            @click="showCreateKbDialog"
          >
            <el-icon><Plus /></el-icon>
            新建知识库
          </el-button>
          <el-button
            v-if="selectedSpaceId"
            size="small"
            circle
            aria-label="空间设置"
            @click="switchTab('settings')"
            title="空间设置"
          >
            <el-icon><Setting /></el-icon>
          </el-button>
          <el-button size="small" circle aria-label="新建知识空间" @click="showCreateSpaceDialog" title="新建知识空间">
            <el-icon><Plus /></el-icon>
          </el-button>
          <el-button size="small" text @click="showManageSpacesDialog">
            <el-icon><Collection /></el-icon>
            管理空间
          </el-button>
        </div>
      </div>

      <!-- 子页面：极简返回栏（仅 返回 + 面包屑） -->
      <div v-else class="content-header content-header--slim">
        <button v-if="navBack" class="slim-back" @click="handleNavBack">
          <el-icon><ArrowLeft /></el-icon>
          <span>{{ navBack.label }}</span>
        </button>
        <BreadcrumbNav />
      </div>

      <!-- 子路由内容 -->
      <div v-if="selectedSpaceId" class="content-body">
        <router-view :key="`${route.params.id || ''}-${kbRefreshKey}`" />
      </div>

      <!-- 未选择空间时的欢迎页（始终显示，不依赖 loading 避免白屏） -->
      <div v-if="!selectedSpaceId" class="welcome-state">
        <EmptyState
          variant="default"
          title="选择知识空间"
          description="从顶部下拉选择或创建一个知识空间，开始管理知识库"
        >
          <el-button type="primary" @click="showCreateSpaceDialog">
            新建知识空间
          </el-button>
        </EmptyState>
      </div>
    </main>

    <!-- 创建空间弹窗 -->
    <el-dialog
      v-model="createSpaceDialogVisible"
      title="新建知识空间"
      width="480px"
      destroy-on-close
    >
      <el-form
        ref="createSpaceFormRef"
        :model="createSpaceForm"
        :rules="spaceFormRules"
        label-width="80px"
      >
        <el-form-item label="名称" prop="name">
          <el-input
            v-model="createSpaceForm.name"
            placeholder="请输入空间名称"
            maxlength="100"
          />
        </el-form-item>
        <el-form-item label="可见性" prop="visibility">
          <el-radio-group v-model="createSpaceForm.visibility">
            <el-radio :value="0">私有</el-radio>
            <el-radio :value="1">团队</el-radio>
            <el-radio :value="2">公开</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="空间类型">
          <el-radio-group v-model="createSpaceForm.space_type" @change="createSpaceForm.embedding_model = ''">
            <el-radio value="text">文本空间</el-radio>
            <el-radio value="multimodal">图片空间</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="createSpaceForm.description"
            type="textarea"
            :rows="3"
            placeholder="请输入空间描述（可选）"
            maxlength="2000"
          />
        </el-form-item>
        <el-divider content-position="left">
          {{ createSpaceForm.space_type === 'multimodal' ? '多模态 Embedding 模型' : 'Embedding 模型' }}
        </el-divider>
        <el-form-item label="模型">
          <el-select
            v-model="createSpaceForm.embedding_model"
            :placeholder="createSpaceForm.space_type === 'multimodal' ? '选择多模态模型（可选）' : '选择模型（可选，也可后续配置）'"
            clearable
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="m in currentCreateModels"
              :key="m.model"
              :label="m.model"
              :value="m.model"
            />
          </el-select>
        </el-form-item>
        <el-row v-if="createSpaceForm.embedding_model" :gutter="20">
          <el-col :span="12">
            <el-form-item label="批处理大小">
              <el-input-number v-model="createSpaceForm.embedding_batch_size" :min="1" :max="128" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="向量归一化">
              <el-switch v-model="createSpaceForm.embedding_normalize" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="createSpaceDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="createSpaceLoading"
          @click="handleCreateSpace"
        >
          创建
        </el-button>
      </template>
    </el-dialog>

    <!-- 管理空间弹窗 -->
    <el-dialog
      v-model="manageSpacesDialogVisible"
      title="管理空间"
      width="640px"
      destroy-on-close
    >
      <div v-if="selectedSpaceIds.length > 0" class="batch-bar">
        <span class="batch-count">已选 {{ selectedSpaceIds.length }} 项</span>
        <el-button size="small" @click="selectedSpaceIds = []">取消选择</el-button>
        <el-button type="danger" size="small" @click="handleBatchDeleteSpaces">
          批量删除
        </el-button>
      </div>

      <el-table
        :data="spaceStore.spaces"
        v-loading="manageLoading"
        stripe
        @selection-change="handleSpaceSelectionChange"
      >
        <el-table-column type="selection" width="45" />
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="visibility" label="可见性" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="getVisibilityType(row.visibility)" size="small">
              {{ getVisibilityText(row.visibility) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="160">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button type="danger" link size="small" @click="handleDeleteSpace(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 新建知识库弹窗 -->
    <el-dialog
      v-model="createKbDialogVisible"
      title="新建知识库"
      width="480px"
      destroy-on-close
    >
      <el-form
        ref="createKbFormRef"
        :model="createKbForm"
        :rules="createKbRules"
        label-width="80px"
      >
        <el-form-item label="名称" prop="name">
          <el-input
            v-model="createKbForm.name"
            placeholder="请输入知识库名称"
            maxlength="100"
          />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="createKbForm.description"
            type="textarea"
            :rows="3"
            placeholder="请输入知识库描述（可选）"
            maxlength="500"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createKbDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="createKbLoading"
          @click="handleCreateKb"
        >
          创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus,
  Setting,
  Collection,
  ArrowLeft,
} from '@element-plus/icons-vue'
import { useSpaceStore } from '@/stores/space'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import { userApi } from '@/api/user'
import type { FormInstance, FormRules } from 'element-plus'
import type { Space, AvailableModelItem } from '@/api/types'
import BreadcrumbNav from '@/components/common/BreadcrumbNav.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const route = useRoute()
const router = useRouter()
const spaceStore = useSpaceStore()

const loading = ref(false)
const selectedSpaceId = ref<number | null>(null)
const kbRefreshKey = ref(0)

// 可见性映射
const visibilityMap: Record<number, { text: string; type: string }> = {
  0: { text: '私有', type: 'info' },
  1: { text: '团队', type: 'warning' },
  2: { text: '公开', type: 'success' },
}

function getVisibilityText(visibility?: number): string {
  if (visibility === undefined) return '未知'
  return visibilityMap[visibility]?.text || '未知'
}

function getVisibilityType(visibility?: number): string {
  if (visibility === undefined) return 'info'
  return visibilityMap[visibility]?.type || 'info'
}

// === 空间选择 ===

function handleSpaceClick(spaceId: number) {
  router.push(`/home/spaces/${spaceId}/knowledge-bases`)
}

function handleSpaceChange(spaceId: number) {
  handleSpaceClick(spaceId)
}

// === Tab 导航 ===

function switchTab(tab: string) {
  if (selectedSpaceId.value) {
    router.push(`/home/spaces/${selectedSpaceId.value}/${tab}`)
  }
}

// === 知识库上下文 ===

const kbId = computed(() => {
  if (route.params.kbId) return Number(route.params.kbId)
  if (route.query.kbId) return Number(route.query.kbId)
  return null
})

// 是否处于空间首页（KB 列表）——决定显示完整空间栏还是极简返回栏
const isSpaceHome = computed(
  () => !selectedSpaceId.value || route.name === 'KnowledgeBases',
)

// 子页面极简返回栏的返回目标（按路由名精确判定，不依赖 activeTab 字符串匹配）
const navBack = computed<{ label: string; to: string } | null>(() => {
  const sid = selectedSpaceId.value
  if (!sid) return null
  const kbIdParam =
    (route.params.kbId as string | undefined) ??
    (route.query.kbId as string | undefined)
  const kbBase = `/home/spaces/${sid}/knowledge-bases`
  const docBase = kbIdParam ? `${kbBase}/${kbIdParam}/documents` : ''
  const name = route.name
  if (name === 'Documents') return { label: '返回知识库', to: kbBase }
  if (name === 'KbEvaluation' || name === 'DocumentDetail' || name === 'Search') {
    return kbIdParam
      ? { label: '返回文档管理', to: docBase }
      : { label: '返回知识库', to: kbBase }
  }
  if (name === 'SpaceSettings') return { label: '返回知识库', to: kbBase }
  return null
})

function handleNavBack() {
  if (navBack.value) router.push(navBack.value.to)
}

// === 创建空间 ===

const createSpaceDialogVisible = ref(false)
const createSpaceLoading = ref(false)
const createSpaceFormRef = ref<FormInstance>()
const createSpaceForm = reactive({
  name: '',
  visibility: 0,
  space_type: 'text' as 'text' | 'multimodal',
  description: '',
  embedding_model: '',
  embedding_batch_size: 32,
  embedding_normalize: true,
})
const embeddingModels = ref<AvailableModelItem[]>([])
const mmEmbeddingModels = ref<AvailableModelItem[]>([])
const currentCreateModels = computed(() =>
  createSpaceForm.space_type === 'multimodal' ? mmEmbeddingModels.value : embeddingModels.value
)

const spaceFormRules: FormRules = {
  name: [
    { required: true, message: '请输入空间名称', trigger: 'blur' },
    { min: 1, max: 100, message: '名称长度 1-100 字符', trigger: 'blur' },
  ],
}

function showCreateSpaceDialog() {
  createSpaceForm.name = ''
  createSpaceForm.visibility = 0
  createSpaceForm.space_type = 'text'
  createSpaceForm.description = ''
  createSpaceForm.embedding_model = ''
  createSpaceForm.embedding_batch_size = 32
  createSpaceForm.embedding_normalize = true
  createSpaceDialogVisible.value = true
  fetchEmbeddingModels()
}

async function fetchEmbeddingModels() {
  try {
    const data = await userApi.getAvailableModelDetails()
    embeddingModels.value = data.embedding || []
    mmEmbeddingModels.value = data.multimodal_embedding || []
  } catch {
    // ignore
  }
}

async function handleCreateSpace() {
  if (!createSpaceFormRef.value) return

  await createSpaceFormRef.value.validate(async (valid) => {
    if (!valid) return

    createSpaceLoading.value = true
    try {
      const config: Record<string, any> = {
        space_type: createSpaceForm.space_type,
        description: createSpaceForm.description || undefined,
        embedding: createSpaceForm.embedding_model
          ? {
              model: createSpaceForm.embedding_model,
              batch_size: createSpaceForm.embedding_batch_size,
              normalize: createSpaceForm.embedding_normalize,
            }
          : undefined,
      }
      if (createSpaceForm.space_type === 'multimodal' && createSpaceForm.embedding_model) {
        config.multimodal_embedding = { model: createSpaceForm.embedding_model }
      }
      const space = await spaceStore.createSpace({
        name: createSpaceForm.name,
        visibility: createSpaceForm.visibility,
        config,
      })
      ElMessage.success('空间创建成功')
      createSpaceDialogVisible.value = false
      router.push(`/home/spaces/${space.id}/knowledge-bases`)
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: { message?: string } } } }
      ElMessage.error(err.response?.data?.error?.message || '创建失败')
    } finally {
      createSpaceLoading.value = false
    }
  })
}

// === 管理空间 ===

const manageSpacesDialogVisible = ref(false)
const manageLoading = ref(false)
const selectedSpaceIds = ref<number[]>([])

function formatDate(date: string): string {
  try {
    return new Date(date).toLocaleDateString('zh-CN') + ' ' +
      new Date(date).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return '-'
  }
}

function showManageSpacesDialog() {
  selectedSpaceIds.value = []
  manageSpacesDialogVisible.value = true
}

function handleSpaceSelectionChange(rows: Space[]) {
  selectedSpaceIds.value = rows.map((r) => r.id)
}

async function handleDeleteSpace(space: Space) {
  try {
    await ElMessageBox.confirm(
      `确定要删除空间 "${space.name}" 吗？此操作将删除所有关联知识库和文档，且不可恢复。`,
      '警告',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'error' },
    )
    manageLoading.value = true
    await spaceStore.deleteSpace(space.id)
    ElMessage.success('空间已删除')
    if (selectedSpaceId.value === space.id) {
      router.replace('/home/spaces')
    }
    spaceStore.fetchSpaces()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      // Error already shown by response interceptor
    }
  } finally {
    manageLoading.value = false
  }
}

async function handleBatchDeleteSpaces() {
  if (selectedSpaceIds.value.length === 0) return

  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedSpaceIds.value.length} 个空间吗？此操作将删除所有关联知识库和文档，且不可恢复。`,
      '批量删除',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'error' },
    )
  } catch {
    return
  }

  manageLoading.value = true
  const ids = [...selectedSpaceIds.value]
  let failCount = 0

  for (const id of ids) {
    try {
      await spaceStore.deleteSpace(id)
    } catch {
      failCount++
    }
  }

  selectedSpaceIds.value = []
  if (failCount === 0) {
    ElMessage.success(`已删除 ${ids.length} 个空间`)
  } else {
    ElMessage.warning(`${ids.length - failCount} 个删除成功，${failCount} 个删除失败`)
  }

  if (selectedSpaceId.value && ids.includes(selectedSpaceId.value)) {
    router.replace('/home/spaces')
  }
  spaceStore.fetchSpaces()
  manageLoading.value = false
}

// === 新建知识库 ===

const createKbDialogVisible = ref(false)
const createKbLoading = ref(false)
const createKbFormRef = ref<FormInstance>()
const createKbForm = reactive({
  name: '',
  description: '',
})

const createKbRules: FormRules = {
  name: [
    { required: true, message: '请输入知识库名称', trigger: 'blur' },
    { min: 1, max: 100, message: '名称长度 1-100 字符', trigger: 'blur' },
  ],
}

function showCreateKbDialog() {
  createKbForm.name = ''
  createKbForm.description = ''
  createKbDialogVisible.value = true
}

async function handleCreateKb() {
  if (!createKbFormRef.value || !selectedSpaceId.value) return

  await createKbFormRef.value.validate(async (valid) => {
    if (!valid) return

    createKbLoading.value = true
    try {
      await knowledgeBaseApi.createKnowledgeBase(selectedSpaceId.value!, {
        name: createKbForm.name,
        config: createKbForm.description
          ? { description: createKbForm.description }
          : undefined,
      })
      ElMessage.success('知识库创建成功')
      createKbDialogVisible.value = false
      kbRefreshKey.value++
    } catch {
      // Error already shown by response interceptor
    } finally {
      createKbLoading.value = false
    }
  })
}

// === 路由同步 ===

watch(
  () => route.params.id,
  (id) => {
    if (id) {
      selectedSpaceId.value = Number(id)
      spaceStore.fetchSpace(Number(id))
    }
  },
  { immediate: true },
)

// === 初始化 ===

async function init() {
  loading.value = true
  try {
    await Promise.all([
      spaceStore.fetchSpaces(),
      spaceStore.fetchPublicSpaces(),
    ])
    if (!route.params.id && spaceStore.spaces.length > 0) {
      router.replace(`/home/spaces/${spaceStore.spaces[0]!.id}/knowledge-bases`)
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  init()
})
</script>

<style scoped>
.space-list-view {
  display: flex;
  height: 100%;
}

/* ===== Header（空间下拉） ===== */

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.space-select {
  width: 220px;
  flex-shrink: 0;
}

/* 空间下拉：发丝线（Linear 风） */
.space-select :deep(.el-select__wrapper) {
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-border) inset;
  transition: box-shadow var(--transition-fast);
}

.space-select :deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--color-text-faint) inset;
}

.space-select :deep(.el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 1px var(--color-primary) inset;
}

.space-option-name {
  margin-right: var(--space-2);
}

.space-option-tag {
  flex-shrink: 0;
}

/* ===== Main Content ===== */

.main-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  background: var(--color-bg);
}

.content-header {
  display: flex;
  align-items: center;
  background: var(--color-bg-card);
  border-bottom: 1px solid var(--color-border);
  box-shadow: var(--shadow-xs);
  flex-shrink: 0;
}

/* 空间首页：完整栏 —— 发丝线 + 大留白，无阴影 */
.content-header--full {
  justify-content: space-between;
  padding: var(--space-5) var(--space-8);
}

/* 子页面：极简返回栏 */
.content-header--slim {
  gap: var(--space-4);
  padding: var(--space-4) var(--space-8);
}

/* 返回按钮：发丝线胶囊，hover 浅底（Linear 风，无阴影/上浮） */
.slim-back {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  padding: 5px 10px;
  transition: background-color var(--transition-fast), color var(--transition-fast);
}

.slim-back:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* ===== Header 按钮：Linear 极简风（扁平 · 发丝线 · hover 浅底，无阴影/上浮） ===== */
.header-actions {
  gap: var(--space-2);
}

.header-actions :deep(.el-button) {
  border-radius: var(--radius-md);
  font-weight: var(--weight-medium);
  transition: background-color var(--transition-fast), color var(--transition-fast),
    border-color var(--transition-fast);
}

/* 实心主操作（新建知识库）：微渐变 + 轻投影，有"放下来"的质感 */
.header-actions :deep(.el-button:not(.is-text):not(.is-circle)) {
  background: linear-gradient(135deg, #6366F1, #5B5FE8);
  border: none;
  padding: 6px 14px;
  font-size: 14px;
  height: auto;
  box-shadow: 0 1px 3px rgba(99, 102, 241, 0.18), 0 1px 0 rgba(255, 255, 255, 0.12) inset;
  transition: background var(--transition-fast), box-shadow var(--transition-fast), transform var(--transition-fast);
}

.header-actions :deep(.el-button:not(.is-text):not(.is-circle)) span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.header-actions :deep(.el-button:not(.is-text):not(.is-circle):hover) {
  background: linear-gradient(135deg, #6D70F5, #6366F1);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.28), 0 1px 0 rgba(255, 255, 255, 0.15) inset;
  transform: translateY(-0.5px);
}

.header-actions :deep(.el-button:not(.is-text):not(.is-circle):active) {
  transform: translateY(0);
  box-shadow: 0 1px 2px rgba(99, 102, 241, 0.14);
}

/* 圆形图标按钮：发丝线，透明底，hover 浅底 */
.header-actions :deep(.el-button.is-circle) {
  width: 30px;
  height: 30px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-secondary);
  box-shadow: none;
}

.header-actions :deep(.el-button.is-circle:hover) {
  color: var(--color-text);
  border-color: var(--color-border);
  background: var(--color-bg-hover);
  transform: none;
  box-shadow: none;
}

/* 文字按钮：hover 浅底 */
.header-actions :deep(.el-button.is-text:hover) {
  color: var(--color-text);
  background: var(--color-bg-hover);
}


.content-body {
  flex: 1;
  padding: var(--space-6) var(--space-8);
  overflow-y: auto;
}

.welcome-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ===== Dialog shared ===== */

.batch-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
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
</style>
