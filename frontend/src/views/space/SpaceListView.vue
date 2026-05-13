<template>
  <div class="space-list-view">
    <!-- 左侧边栏 -->
    <aside class="sidebar">
      <!-- 侧边栏头部 -->
      <div class="sidebar-header">
        <h3 class="sidebar-title">知识空间</h3>
        <el-button type="primary" size="small" circle @click="showCreateSpaceDialog">
          <el-icon><Plus /></el-icon>
        </el-button>
      </div>

      <!-- 搜索框 -->
      <div class="sidebar-search">
        <el-input
          v-model="searchQuery"
          placeholder="搜索空间..."
          prefix-icon="Search"
          size="small"
          clearable
        />
      </div>

      <!-- 空间列表 -->
      <div class="sidebar-body">
        <!-- 我的空间 -->
        <div class="sidebar-section">
          <div class="section-label">我的空间</div>
          <div
            v-for="space in filteredMySpaces"
            :key="space.id"
            class="space-item"
            :class="{ active: selectedSpaceId === space.id }"
            @click="handleSpaceClick(space.id)"
          >
            <div class="space-item-icon">
              <el-icon :size="16"><Collection /></el-icon>
            </div>
            <div class="space-item-info">
              <span class="space-item-name">{{ space.name }}</span>
              <el-tag
                :type="getVisibilityType(space.visibility)"
                size="small"
                class="space-item-vis"
              >
                {{ getVisibilityText(space.visibility) }}
              </el-tag>
            </div>
          </div>
          <div v-if="filteredMySpaces.length === 0" class="section-empty">
            {{ searchQuery ? '无匹配空间' : '暂无空间' }}
          </div>
        </div>

        <!-- 公开空间 -->
        <div v-if="filteredPublicSpaces.length > 0" class="sidebar-section">
          <div class="section-label">公开空间</div>
          <div
            v-for="space in filteredPublicSpaces"
            :key="space.id"
            class="space-item"
            :class="{ active: selectedSpaceId === space.id }"
            @click="handleSpaceClick(space.id)"
          >
            <div class="space-item-icon public">
              <el-icon :size="16"><Collection /></el-icon>
            </div>
            <div class="space-item-info">
              <span class="space-item-name">{{ space.name }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 侧边栏底部 -->
      <div class="sidebar-footer">
        <el-button size="small" text @click="showManageSpacesDialog">
          <el-icon><Setting /></el-icon>
          管理空间
        </el-button>
      </div>
    </aside>

    <!-- 右侧主内容区 -->
    <main class="main-content">
      <!-- 内容头部（面包屑 + 操作） -->
      <div v-if="selectedSpaceId" class="content-header">
        <BreadcrumbNav />
        <div class="header-actions">
          <el-button
            v-if="activeTab === 'knowledge-bases'"
            size="small"
            @click="showCreateKbDialog"
          >
            <el-icon><Plus /></el-icon>
            新建知识库
          </el-button>
          <el-button
            size="small"
            circle
            class="settings-btn"
            @click="switchTab('settings')"
          >
            <el-icon><Setting /></el-icon>
          </el-button>
        </div>
      </div>

      <!-- 子路由内容 -->
      <div v-if="selectedSpaceId" class="content-body">
        <router-view :key="`${route.params.id || ''}-${kbRefreshKey}`" />
      </div>

      <!-- 未选择空间时的欢迎页 -->
      <div v-if="!selectedSpaceId && !loading" class="welcome-state">
        <EmptyState
          variant="default"
          title="选择知识空间"
          description="从左侧选择或创建一个知识空间，开始管理知识库"
        />
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
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="createSpaceForm.description"
            type="textarea"
            :rows="3"
            placeholder="请输入空间描述（可选）"
            maxlength="2000"
          />
        </el-form-item>
        <el-divider content-position="left">Embedding 模型</el-divider>
        <el-form-item label="模型">
          <el-select
            v-model="createSpaceForm.embedding_model"
            placeholder="选择模型（可选，也可后续配置）"
            clearable
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="m in embeddingModels"
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
const activeTab = ref('knowledge-bases')
const kbRefreshKey = ref(0)
const searchQuery = ref('')

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

// === 搜索过滤 ===

const filteredMySpaces = computed(() => {
  const q = searchQuery.value.toLowerCase().trim()
  if (!q) return spaceStore.spaces
  return spaceStore.spaces.filter((s) => s.name.toLowerCase().includes(q))
})

const filteredPublicSpaces = computed(() => {
  const q = searchQuery.value.toLowerCase().trim()
  if (!q) return spaceStore.publicSpaces
  return spaceStore.publicSpaces.filter((s) => s.name.toLowerCase().includes(q))
})

// === 空间选择 ===

function handleSpaceClick(spaceId: number) {
  router.push(`/home/spaces/${spaceId}/${activeTab.value}`)
}

// === Tab 导航 ===

function switchTab(tab: string) {
  if (selectedSpaceId.value) {
    activeTab.value = tab
    router.push(`/home/spaces/${selectedSpaceId.value}/${tab}`)
  }
}

// === 知识库上下文 ===

const kbId = computed(() => {
  if (route.params.kbId) return Number(route.params.kbId)
  if (route.query.kbId) return Number(route.query.kbId)
  return null
})

// === 创建空间 ===

const createSpaceDialogVisible = ref(false)
const createSpaceLoading = ref(false)
const createSpaceFormRef = ref<FormInstance>()
const createSpaceForm = reactive({
  name: '',
  visibility: 0,
  description: '',
  embedding_model: '',
  embedding_batch_size: 32,
  embedding_normalize: true,
})
const embeddingModels = ref<AvailableModelItem[]>([])

const spaceFormRules: FormRules = {
  name: [
    { required: true, message: '请输入空间名称', trigger: 'blur' },
    { min: 1, max: 100, message: '名称长度 1-100 字符', trigger: 'blur' },
  ],
}

function showCreateSpaceDialog() {
  createSpaceForm.name = ''
  createSpaceForm.visibility = 0
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
      const space = await spaceStore.createSpace({
        name: createSpaceForm.name,
        visibility: createSpaceForm.visibility,
        config: {
          description: createSpaceForm.description || undefined,
          embedding: createSpaceForm.embedding_model
            ? {
                model: createSpaceForm.embedding_model,
                batch_size: createSpaceForm.embedding_batch_size,
                normalize: createSpaceForm.embedding_normalize,
              }
            : undefined,
        },
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

watch(
  () => route.path,
  (path) => {
    if (path.includes('/knowledge-bases')) {
      activeTab.value = 'knowledge-bases'
    } else if (path.includes('/search')) {
      activeTab.value = 'search'
    } else if (path.includes('/settings')) {
      activeTab.value = 'settings'
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

/* ===== Sidebar ===== */

.sidebar {
  width: 260px;
  flex-shrink: 0;
  background: var(--color-bg-sidebar);
  border-right: 1px solid var(--color-border-light);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-4) var(--space-3);
}

.sidebar-title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  font-family: var(--font-display);
}

.sidebar-search {
  padding: 0 var(--space-4) var(--space-3);
}

.sidebar-body {
  flex: 1;
  overflow-y: auto;
  padding: 0 var(--space-2);
}

.sidebar-section {
  margin-bottom: var(--space-4);
}

.section-label {
  padding: var(--space-1) var(--space-3) var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.space-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  position: relative;
  margin-bottom: 2px;
}

.space-item:hover {
  background: var(--color-bg-hover);
}

.space-item.active {
  background: var(--color-primary-muted);
}

.space-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 60%;
  border-radius: 0 2px 2px 0;
  background: var(--color-primary);
}

.space-item-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  flex-shrink: 0;
}

.space-item-icon.public {
  background: var(--color-success-subtle);
  color: var(--color-success);
}

.space-item-info {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.space-item-name {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.space-item.active .space-item-name {
  color: var(--color-primary);
}

.space-item-vis {
  flex-shrink: 0;
}

.section-empty {
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-faint);
  font-style: italic;
}

.sidebar-footer {
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--color-border-light);
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
  justify-content: space-between;
  padding: var(--space-4) var(--space-6);
  background: var(--color-bg-card);
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.settings-btn {
  border: none !important;
  background: transparent !important;
  transition: background-color var(--transition-base);
}

.settings-btn:hover {
  background: var(--color-bg-hover) !important;
}

.content-body {
  flex: 1;
  padding: var(--space-5) var(--space-6);
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
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.batch-count {
  font-size: var(--text-sm);
  color: var(--color-danger);
  font-weight: var(--weight-medium);
}
</style>
