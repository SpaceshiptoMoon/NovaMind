<template>
  <div class="space-list-view">
    <!-- 顶部栏：系统标识 + 空间选择 -->
    <div v-if="!kbId" class="top-bar">
      <div class="top-bar-left">
        <UnicornIcon :size="38" @click="router.push('/home/spaces')" title="返回空间列表" />
        <el-select
          v-model="selectedSpaceId"
          placeholder="请选择知识空间"
          class="space-select"
          filterable
          @change="handleSpaceChange"
        >
          <el-option-group label="我的空间">
            <el-option
              v-for="space in spaceStore.spaces"
              :key="space.id"
              :label="space.name"
              :value="space.id"
            />
          </el-option-group>
          <el-option-group
            v-if="spaceStore.publicSpaces.length > 0"
            label="公开空间"
          >
            <el-option
              v-for="space in spaceStore.publicSpaces"
              :key="space.id"
              :label="space.name"
              :value="space.id"
            />
          </el-option-group>
        </el-select>
        <el-tag
          v-if="currentSpace"
          :type="getVisibilityType(currentSpace.visibility)"
          size="small"
        >
          {{ getVisibilityText(currentSpace.visibility) }}
        </el-tag>
        <span v-if="currentSpace" class="space-desc-inline">
          {{ currentSpace.config?.description || '' }}
        </span>
      </div>
      <div class="top-bar-right">
        <el-button type="primary" size="small" @click="showCreateSpaceDialog">
          <el-icon><Plus /></el-icon>
          空间
        </el-button>
        <el-button size="small" @click="showManageSpacesDialog">
          管理空间
        </el-button>
        <el-button
          v-if="selectedSpaceId"
          size="small"
          circle
          class="settings-icon-btn"
          @click="switchTab('settings')"
        >
          <el-icon color="#5C5C5C"><Setting /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- 知识库快捷操作（仅知识库视图显示） -->
    <div v-if="selectedSpaceId && activeTab === 'knowledge-bases' && !kbId" class="kb-toolbar">
      <el-button size="small" @click="showCreateKbDialog">
        <el-icon><Plus /></el-icon>
        新建知识库
      </el-button>
      <span class="member-count">{{ memberCount }} 成员</span>
    </div>

    <!-- 子路由内容 -->
    <div v-if="selectedSpaceId" class="space-content">
      <router-view :key="`${route.params.id || ''}-${kbRefreshKey}`" />
    </div>

    <!-- 未选择空间时的空状态 -->
    <el-empty
      v-if="!selectedSpaceId && !loading"
      description="请选择或创建一个知识空间"
    />

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
} from '@element-plus/icons-vue'
import { useSpaceStore } from '@/stores/space'
import { memberApi } from '@/api/member'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import { userApi } from '@/api/user'
import type { FormInstance, FormRules } from 'element-plus'
import type { Space, AvailableModelItem } from '@/api/types'
import UnicornIcon from '@/components/common/UnicornIcon.vue'

const route = useRoute()
const router = useRouter()
const spaceStore = useSpaceStore()

const loading = ref(false)
const selectedSpaceId = ref<number | null>(null)
const memberCount = ref(0)
const activeTab = ref('knowledge-bases')
const kbRefreshKey = ref(0)

const currentSpace = computed(() => spaceStore.currentSpace)

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

function handleSpaceChange(spaceId: number) {
  router.push(`/home/spaces/${spaceId}/${activeTab.value}`)
}

async function fetchSpaceDetails() {
  if (!selectedSpaceId.value) return
  try {
    await spaceStore.fetchSpace(selectedSpaceId.value)
    const data = await memberApi.getMembers(selectedSpaceId.value)
    memberCount.value = data.total || 0
  } catch {
    // ignore
  }
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
      // Force child component re-mount to refresh KB list
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
      fetchSpaceDetails()
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
  padding: var(--space-5);
}

.top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
}

.top-bar-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.top-bar-right {
  display: flex;
  gap: var(--space-2);
}

.space-select {
  width: 280px;
}

.space-desc-inline {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.kb-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.member-count {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.space-content {
  min-height: 400px;
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-danger-subtle);
  border-radius: var(--radius-lg);
  border: 1px solid rgba(212, 64, 64, 0.2);
}

.batch-count {
  font-size: var(--text-sm);
  color: var(--color-danger);
  font-weight: var(--weight-medium);
}

.settings-icon-btn {
  border: none !important;
  background: transparent !important;
  transition: background-color var(--transition-base);
}

.settings-icon-btn:hover {
  background: var(--color-bg-hover) !important;
}

.settings-icon-btn:hover .el-icon {
  color: var(--color-primary) !important;
}
</style>
