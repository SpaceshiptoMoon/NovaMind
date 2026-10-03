<template>
  <div class="knowledge-base-view">
    <!-- 页头：eyebrow 空间名 + 主标题 + 描述，右上唯一主 CTA（与用户管理/角色管理同范式） -->
    <div class="page-header">
      <div>
        <p class="eyebrow">{{ spaceStore.currentSpace?.name || '知识空间' }}</p>
        <h2>知识库</h2>
        <p class="desc">管理空间内的知识库：上传文档、配置解析与检索，或归档不再使用的库</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="showCreateDialog">
          <el-icon><Plus /></el-icon>
          新建知识库
        </el-button>
        <el-button @click="fetchKnowledgeBases">刷新</el-button>
      </div>
    </div>

    <!-- 统计卡条：点击切换归档筛选（第四卡纯展示：文档总数汇总） -->
    <div class="stat-grid">
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': statusFilter === '' }"
        @click="setStatusFilter('')"
      >
        <span class="stat-value">{{ knowledgeBases.length }}</span>
        <span class="stat-label">全部知识库</span>
      </button>
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': statusFilter === 1 }"
        @click="setStatusFilter(1)"
      >
        <span class="stat-value">{{ activeCount }}</span>
        <span class="stat-label">活跃</span>
      </button>
      <button
        type="button"
        class="stat-card"
        :class="{ 'is-active': statusFilter === 2 }"
        @click="setStatusFilter(2)"
      >
        <span class="stat-value">{{ archivedCount }}</span>
        <span class="stat-label">已归档</span>
      </button>
      <button type="button" class="stat-card is-static">
        <span class="stat-value">{{ totalDocuments }}</span>
        <span class="stat-label">文档总数</span>
      </button>
    </div>

    <div class="section-card">
      <!-- 工具行：搜索 + 计数 -->
      <div class="toolbar">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索知识库名称、描述"
          clearable
          :prefix-icon="Search"
          class="toolbar-search"
        />
        <span class="toolbar-meta">共 {{ filteredKBs.length }} 个知识库</span>
      </div>

      <!-- 知识库卡片网格（中性横卡：头像 + 名称/描述 + 元信息） -->
      <div v-loading="loading" class="kb-grid">
        <div
          v-for="kb in filteredKBs"
          :key="kb.id"
          class="kb-card"
          :class="{ 'is-archived': kb.status !== 1 }"
          @click="goToDocuments(kb.id)"
        >
          <!-- 左：首字头像（中性灰底；归档库降透明度） -->
          <div class="kb-avatar">{{ kb.name.charAt(0) }}</div>

          <!-- 右：内容列 -->
          <div class="kb-card-body">
            <div class="kb-title-row">
              <h4 class="kb-name">{{ kb.name }}</h4>
              <span v-if="kb.status !== 1" class="kb-archived-tag">已归档</span>
            </div>
            <p class="kb-desc">{{ kb.config?.description || '暂无描述' }}</p>
            <div class="kb-meta-row">
              <span class="meta-item">
                <el-icon :size="13"><Document /></el-icon>
                {{ kb.stats?.document_count ?? 0 }} 文档
              </span>
              <!-- 后端 stats 数值为字符串（"0" 是 truthy），须 Number 归一后再判零 -->
              <span
                v-if="
                  Number(kb.stats?.processing_documents) + Number(kb.stats?.pending_documents) > 0
                "
                class="meta-item meta-warn"
              >
                {{ Number(kb.stats?.processing_documents) + Number(kb.stats?.pending_documents) }}
                处理中
              </span>
            </div>
          </div>

          <!-- hover 操作（右上角，不与内容挤一行） -->
          <div class="kb-actions" @click.stop>
            <el-tooltip content="编辑" placement="top">
              <el-button size="small" circle text aria-label="编辑" @click="showEditDialog(kb)">
                <el-icon><Edit /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip content="配置" placement="top">
              <el-button size="small" circle text aria-label="配置" @click="goConfig(kb)">
                <el-icon><Setting /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip v-if="kb.status === 1" content="归档" placement="top">
              <el-button size="small" circle text aria-label="归档" @click="handleArchive(kb)">
                <el-icon><FolderOpened /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip v-else content="激活" placement="top">
              <el-button size="small" circle text aria-label="激活" @click="handleUnarchive(kb)">
                <el-icon><FolderAdd /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip content="删除" placement="top">
              <el-button
                size="small"
                circle
                text
                aria-label="删除"
                class="danger-btn"
                @click="handleDeleteSingle(kb)"
              >
                <el-icon><Delete /></el-icon>
              </el-button>
            </el-tooltip>
          </div>
        </div>

        <!-- 空状态（区分「真的没有」与「筛选后为空」） -->
        <EmptyState
          v-if="!loading && filteredKBs.length === 0 && knowledgeBases.length > 0"
          variant="search"
          headline="没有匹配的知识库"
          description="换个关键词试试，或清除筛选查看全部"
        >
          <el-button @click="clearFilters">清除搜索与筛选</el-button>
        </EmptyState>
        <EmptyState
          v-if="!loading && knowledgeBases.length === 0"
          variant="default"
          headline="暂无知识库"
          description="创建知识库，上传文档，开始构建你的知识体系"
        >
          <el-button type="primary" @click="showCreateDialog"> 新建知识库 </el-button>
        </EmptyState>
      </div>
    </div>

    <!-- 新建/编辑知识库弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editKbId ? '编辑知识库' : '新建知识库'"
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
        <el-button type="primary" :loading="submitLoading" @click="handleSubmit"> 保存 </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 空间内知识库列表页。
 *
 * 对应路由 /home/spaces/:id/knowledge-bases：页头（空间名 eyebrow）+ 统计卡条
 * （点击筛选活跃/归档）+ 搜索工具行 + 横卡网格。点击卡片进入文档管理，hover 提供
 * 编辑/配置/归档激活/删除操作；新建与空态快捷创建统一走同一弹窗（名称+描述）。
 */

import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Document,
  Edit,
  Setting,
  FolderOpened,
  FolderAdd,
  Delete,
  Plus,
  Search,
} from '@element-plus/icons-vue'
import { knowledgeBaseApi } from '@/api/knowledge'
import { useSpaceStore } from '@/stores/space'
import type { KnowledgeBase } from '@/api/types'
import type { FormInstance, FormRules } from 'element-plus'
import EmptyState from '@/components/common/EmptyState.vue'

const route = useRoute()
const router = useRouter()
const spaceStore = useSpaceStore()

const spaceId = computed(() => Number(route.params.id))

const loading = ref(false)
const submitLoading = ref(false)
const dialogVisible = ref(false)
const editKbId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const knowledgeBases = ref<KnowledgeBase[]>([])

// 筛选：''=全部 / 1=活跃 / 2=已归档（与统计卡点击联动）
type StatusFilter = '' | 1 | 2
const statusFilter = ref<StatusFilter>('')
const searchKeyword = ref('')

function setStatusFilter(next: StatusFilter) {
  statusFilter.value = statusFilter.value === next ? '' : next
}

function clearFilters() {
  statusFilter.value = ''
  searchKeyword.value = ''
}

const activeCount = computed(() => knowledgeBases.value.filter((kb) => kb.status === 1).length)
const archivedCount = computed(() => knowledgeBases.value.filter((kb) => kb.status !== 1).length)
const totalDocuments = computed(() =>
  knowledgeBases.value.reduce((sum, kb) => sum + Number(kb.stats?.document_count ?? 0), 0),
)

// 搜索 + 状态筛选后的列表
const filteredKBs = computed(() => {
  let list = knowledgeBases.value
  if (searchKeyword.value) {
    const keyword = searchKeyword.value.toLowerCase()
    list = list.filter(
      (kb) =>
        kb.name.toLowerCase().includes(keyword) ||
        (kb.config?.description || '').toLowerCase().includes(keyword),
    )
  }
  if (statusFilter.value !== '') {
    list = list.filter((kb) => kb.status === statusFilter.value)
  }
  return list
})

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

// === 跳转配置向导页 ===

function goConfig(kb: KnowledgeBase) {
  router.push({ name: 'KbConfig', params: { id: spaceId.value, kbId: kb.id } })
}

// === 知识库列表 ===

/** 加载空间下知识库列表（含文档数统计与归档状态）。 */
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

// === 新建/编辑（统一弹窗：空态快捷创建与页头新建共用） ===

function showCreateDialog() {
  editKbId.value = null
  formData.name = ''
  formData.description = ''
  dialogVisible.value = true
}

function showEditDialog(kb: KnowledgeBase) {
  editKbId.value = kb.id
  formData.name = kb.name
  formData.description = kb.config?.description || ''
  dialogVisible.value = true
}

/** 新建或保存编辑：描述空串也显式提交，避免 config 缺失导致清空操作静默失效。 */
async function handleSubmit() {
  if (!formRef.value) return

  await formRef.value.validate(async (valid) => {
    if (!valid) return

    submitLoading.value = true
    try {
      if (editKbId.value) {
        await knowledgeBaseApi.updateKnowledgeBase(spaceId.value, editKbId.value, {
          name: formData.name,
          // 描述为空也要显式传 ""，否则 config 整个不发送，清空操作静默失效
          config: { description: formData.description },
        })
        ElMessage.success('知识库更新成功')
      } else {
        await knowledgeBaseApi.createKnowledgeBase(spaceId.value, {
          name: formData.name.trim(),
          config: { description: formData.description },
        })
        ElMessage.success('知识库创建成功')
      }
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

onMounted(() => {
  fetchKnowledgeBases()
})
</script>

<style scoped>
.knowledge-base-view {
  /* flex column 容器内 margin:auto 会吞掉 stretch 致整页退化 fit-content 宽（实测坑），显式撑满 */
  width: 100%;
}

/* ===== 页头（与用户管理/角色管理同款） ===== */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: var(--space-4);
  flex-wrap: wrap;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  padding: var(--space-5) var(--space-6);
  margin-bottom: var(--space-4);
}

.eyebrow {
  margin: 0 0 var(--space-1);
  font-size: 12px;
  font-weight: var(--weight-semibold);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-text-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page-header h2 {
  margin: 0 0 var(--space-1);
  font-size: 22px;
  font-weight: var(--weight-bold);
}

.page-header .desc {
  color: var(--color-text-muted);
  font-size: var(--text-base);
  margin: 0;
}

.header-actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

/* ===== 统计卡条 ===== */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-1);
  padding: var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition:
    border-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.stat-card:hover {
  border-color: var(--color-border-focus);
}

.stat-card.is-active {
  border-color: var(--color-border-focus);
  box-shadow: var(--shadow-sm);
}

/* 纯展示卡不做选中描边 */
.stat-card.is-static {
  cursor: default;
}

.stat-value {
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}

.stat-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

/* ===== 列表区 ===== */
.section-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  padding: var(--space-5) var(--space-6);
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-bottom: var(--space-4);
}

.toolbar-search {
  width: 260px;
  max-width: 100%;
}

.toolbar-meta {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

/* ===== 知识库卡片网格 ===== */
.kb-grid {
  display: grid;
  /* 下限 320px：横卡（头像+双行文本+hover 操作）低于此宽度会挤压换行；
     上限用卡片自身 max-width 收，不用轨道 max（auto-repeat 按 max 计数轨道，实测坑） */
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--space-3);
  min-height: 200px;
}

/* 空状态需横跨所有列，否则只占一个单元格、图标视觉偏左不居中 */
.kb-grid > :deep(.empty-state) {
  grid-column: 1 / -1;
}

/* 矮视口下空态按钮落在内滚折叠线下（评审 P3-1）：压缩空态垂直留白，
   常见笔记本视口一屏可见操作按钮（仅本页网格内收，不动全站组件） */
.kb-grid > :deep(.empty-state) {
  padding: var(--space-3) 0;
}

.kb-grid > :deep(.empty-illustration) {
  margin-bottom: var(--space-2);
  opacity: 0.8;
}

.kb-grid > :deep(.empty-headline) {
  margin-bottom: var(--space-1);
}

.kb-grid > :deep(.empty-actions) {
  margin-top: var(--space-3);
}

/* 中性横卡：左头像 + 右内容列；hover 只提边框不上浮（Neutral Minimal 扁平原则） */
.kb-card {
  position: relative;
  display: flex;
  gap: var(--space-3);
  max-width: 560px;
  padding: var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: border-color var(--transition-fast);
}

.kb-card:hover {
  border-color: var(--color-border-focus);
}

/* 归档库：整体降存在感（头像与文字降透明度），区别于活跃库 */
.kb-card.is-archived .kb-avatar,
.kb-card.is-archived .kb-name {
  opacity: 0.55;
}

/* 首字头像：中性灰底 */
.kb-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-lg);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: var(--weight-semibold);
  flex-shrink: 0;
  user-select: none;
}

.kb-card-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.kb-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.kb-name {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-archived-tag {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--color-text-muted);
  background: var(--color-bg-hover);
  padding: 1px 8px;
  border-radius: var(--radius-full);
}

.kb-desc {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  line-height: var(--leading-normal);
}

.kb-meta-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: 2px;
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

/* 处理中文档数：语义警示色文字（不上底色，克制） */
.meta-warn {
  color: var(--color-warning);
}

/* hover 操作：右上角，不与内容挤一行 */
.kb-actions {
  position: absolute;
  top: 6px;
  right: 6px;
  display: flex;
  align-items: center;
  opacity: 0;
  transition: opacity var(--transition-base);
}

.kb-card:hover .kb-actions {
  opacity: 1;
}

/* 删除按钮：hover 才显danger色，平时跟随中性 */
.danger-btn:hover {
  color: var(--color-danger);
}

/* 窄屏：统计卡 4→2 列，网格降单列下限 */
@media (max-width: 960px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .section-card {
    padding: var(--space-4);
  }

  .kb-grid {
    grid-template-columns: 1fr;
  }

  /* 窄屏：绝对定位的右上操作会叠印在标题上（评审 P2-1 实测），改为卡片底部
     常显操作行——wrap 换行占独立文档流位置，头像/正文保持并排不重叠 */
  .kb-card {
    flex-wrap: wrap;
  }

  .kb-actions {
    position: static;
    width: 100%;
    opacity: 1;
    margin: 0 calc(-1 * var(--space-4)) calc(-1 * var(--space-4));
    padding: var(--space-2) var(--space-4);
    padding-left: calc(var(--space-4) + 40px + var(--space-3));
    border-top: 1px solid var(--color-border-light);
  }
}
</style>
