<template>
  <div class="document-view">
    <div class="kb-layout">
      <KbSidebar :nav-items="kbNavItems" />

      <div class="kb-content">
        <section class="kb-overview">
          <div class="kb-overview__copy">
            <span class="kb-overview__eyebrow">知识库概览</span>
            <h1 class="kb-overview__title">{{ kbName || '文档管理' }}</h1>
            <p class="kb-overview__desc">当前知识库的文档概况和继承能力都集中展示在这里。</p>

            <div class="kb-overview__stats">
              <div class="kb-stat-card">
                <span class="kb-stat-card__label">文档</span>
                <strong>{{ kbStats.document_count }}</strong>
              </div>
              <div class="kb-stat-card">
                <span class="kb-stat-card__label">分块</span>
                <strong>{{ kbStats.chunk_count }}</strong>
              </div>
              <div class="kb-stat-card">
                <span class="kb-stat-card__label">已完成</span>
                <strong>{{ kbStats.completed_documents }}</strong>
              </div>
              <div class="kb-stat-card">
                <span class="kb-stat-card__label">处理中</span>
                <strong>{{ kbStats.processing_documents }}</strong>
              </div>
            </div>
          </div>

          <div class="kb-overview__inherit">
            <div class="inherit-head">
              <h2>继承能力</h2>
              <p>以下能力由空间统一提供。</p>
            </div>

            <div class="inherit-grid">
              <div class="inherit-card">
                <span class="inherit-label">文本向量模型</span>
                <strong class="inherit-value">{{ embeddingInfo.textModel || '未配置' }}</strong>
                <span class="inherit-meta">{{ embeddingInfo.textDimension ? `维度 ${embeddingInfo.textDimension}` : '维度待检测' }}</span>
              </div>

              <div class="inherit-card inherit-card--wide">
                <span class="inherit-label">可用类型</span>
                <strong class="inherit-value">{{ readableSpaceTypes }}</strong>
                <span class="inherit-meta">知识库可上传的数据类型会跟随这里变化。</span>
              </div>
            </div>
          </div>
        </section>

        <div class="action-bar">
          <div class="left-actions">
            <el-button type="primary" @click="showUploadDialog">
              <el-icon><Upload /></el-icon>
              上传文档
            </el-button>
            <el-button
              v-if="selectedIds.length > 0"
              @click="showProcessDialog(selectedIds)"
            >
              批量处理 ({{ selectedIds.length }})
            </el-button>
          </div>
          <div class="right-actions">
            <el-input
              v-model="searchKeyword"
              class="search-input"
              placeholder="搜索文件名"
              maxlength="100"
              clearable
              @keyup.enter="handleSearch"
              @clear="handleSearch"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <span class="filter-label">状态</span>
            <el-select
              v-model="statusFilter"
              class="status-filter"
              placeholder="全部状态"
              clearable
              @change="handleStatusFilterChange"
              @clear="handleStatusFilterChange"
            >
              <el-option
                v-for="item in statusOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </div>
        </div>

        <div v-loading="loading" class="doc-table-wrap">
          <el-table
            :data="documents"
            :empty-text="searchKeyword || statusFilter !== undefined ? '没有符合条件的文档' : '暂无文档，点击右上角上传'"
            @selection-change="handleSelectionChange"
            class="doc-table"
          >
            <el-table-column type="selection" width="45" />
            <el-table-column prop="filename" label="文件名" min-width="220">
              <template #default="{ row }">
                <div class="filename-cell" @click="goToDetail(row.id)">
                  <div
                    class="file-icon"
                    :style="{ background: getFileTypeStyle(row.file_type).bg, color: getFileTypeStyle(row.file_type).color }"
                  >
                    {{ row.file_type.toUpperCase().slice(0, 3) }}
                  </div>
                  <span class="file-name">{{ row.filename }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="file_size" label="大小" min-width="80" align="center">
              <template #default="{ row }">
                <span class="text-muted">{{ formatFileSize(row.file_size) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="chunk_count" label="分块" min-width="64" align="center">
              <template #default="{ row }">
                <span class="text-muted">{{ row.chunk_count ?? '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" min-width="80" align="center">
              <template #default="{ row }">
                <el-tag :type="getStatusConfig(row.status).type" effect="plain" size="small">
                  {{ getStatusConfig(row.status).text }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="上传时间" min-width="140">
              <template #default="{ row }">
                <span class="text-muted">{{ formatDate(row.created_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="" min-width="120" fixed="right" align="right">
              <template #default="{ row }">
                <div class="action-buttons">
                  <el-tooltip v-if="canProcess(row)" content="首次处理" placement="top">
                    <el-button :icon="VideoPlay" circle size="small" type="primary" @click="handleProcessSingle(row)" />
                  </el-tooltip>
                  <el-tooltip v-if="canReprocess(row)" content="重新处理" placement="top">
                    <el-button :icon="RefreshRight" circle size="small" type="primary" @click="handleProcessSingle(row)" />
                  </el-tooltip>
                  <el-tooltip v-if="canCancel(row)" content="取消" placement="top">
                    <el-button :icon="Close" circle size="small" type="warning" @click="handleCancelSingle(row)" />
                  </el-tooltip>
                  <el-tooltip v-if="canRetry(row)" content="重试" placement="top">
                    <el-button :icon="RefreshRight" circle size="small" type="warning" @click="handleRetrySingle(row)" />
                  </el-tooltip>
                  <el-tooltip content="详情" placement="top">
                    <el-button :icon="View" circle size="small" @click="goToDetail(row.id)" />
                  </el-tooltip>
                  <el-tooltip v-if="canDelete(row)" content="删除" placement="top">
                    <el-button :icon="Delete" circle size="small" type="danger" @click="handleDelete(row)" />
                  </el-tooltip>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <Pagination
          :page="currentPage"
          :page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @update:page="(p: number) => { currentPage = p; fetchDocuments() }"
          @update:page-size="(s: number) => { pageSize = s; currentPage = 1; fetchDocuments() }"
        />

        <el-dialog v-model="uploadDialogVisible" title="上传文档" width="680px" destroy-on-close class="upload-dialog">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="200"
            multiple
            :file-list="fileList"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
            :on-exceed="handleExceed"
            :accept="uploadAccept"
            drag
            class="upload-area"
          >
            <div class="upload-inner">
              <el-icon class="upload-icon"><UploadFilled /></el-icon>
              <div class="upload-text">
                拖拽文件到此处，或<em>点击上传</em>
              </div>
              <div class="upload-tip">
                {{ uploadTipText }}
              </div>
              <el-button text type="primary" class="upload-folder-btn" @click.stop="triggerFolderPick">
                <el-icon><FolderOpened /></el-icon>
                选择文件夹
              </el-button>
            </div>
          </el-upload>
          <input
            ref="folderInputRef"
            type="file"
            multiple
            hidden
            class="hidden-folder-input"
            v-bind="{ webkitdirectory: true, directory: true }"
            @change="handleFolderChange"
          />
          <template #footer>
            <el-button @click="uploadDialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="uploadLoading" @click="handleUpload" :disabled="selectedFiles.length === 0">
              上传 ({{ selectedFiles.length }})
            </el-button>
          </template>
        </el-dialog>

        <el-dialog v-model="processDialogVisible" title="处理文档" width="480px" destroy-on-close>
          <p class="process-desc">
            将对选中的 {{ processTargetIds.length }} 个文档执行切分、解析和向量化。
          </p>
          <template #footer>
            <el-button @click="processDialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="processLoading" @click="handleProcess">
              开始处理
            </el-button>
          </template>
        </el-dialog>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, DataAnalysis, Delete, Document, FolderOpened, List, RefreshRight, Search, Upload, UploadFilled, VideoPlay, View } from '@element-plus/icons-vue'
import type { UploadFile } from 'element-plus'

import { documentApi, knowledgeBaseApi } from '@/api/knowledge'
import { spaceApi } from '@/api/space'
import type { BatchUploadResponse, Document as DocType } from '@/api/types'
import { KbSidebar, buildKbNavItems, getFileMaxSize, getFileTypeStyle, getUploadAccept, hasModality, normalizeSpaceTypes, taskStatusMap } from '@/components/knowledge'
import Pagination from '@/components/common/Pagination.vue'
import { formatDate, formatFileSize } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))
const kbId = computed(() => Number(route.params.kbId))

const kbNavItems = computed(() =>
  buildKbNavItems({
    spaceId: spaceId.value,
    kbId: kbId.value,
    currentRouteName: route.name,
    icons: {
      document: Document,
      list: List,
      search: Search,
      evaluation: DataAnalysis,
    },
  })
)

const loading = ref(false)
const uploadLoading = ref(false)
const processLoading = ref(false)
const uploadDialogVisible = ref(false)
const processDialogVisible = ref(false)

const spaceTypes = ref<string[]>(['text'])
const kbName = ref('')
const kbStats = ref({
  document_count: 0,
  chunk_count: 0,
  completed_documents: 0,
  processing_documents: 0,
})
const embeddingInfo = ref({
  textModel: '',
  textDimension: null as number | null,
})
const documents = ref<DocType[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const fileList = ref<UploadFile[]>([])
const selectedFiles = ref<File[]>([])
const folderInputRef = ref<HTMLInputElement | null>(null)
// 单次上传文件数上限（与后端 MAX_BATCH_FILE_COUNT 对齐，支持文件夹整体上传）
const MAX_UPLOAD_COUNT = 200
// 文件夹选择时手动入队的 uid 基数，取负值避免与 el-upload 内部正序 uid 冲突
let folderFileUid = -1
const selectedIds = ref<number[]>([])
const processTargetIds = ref<number[]>([])
const statusFilter = ref<number | undefined>(undefined)
// 文件名搜索关键词（回车或清空时提交）
const searchKeyword = ref('')

const statusOptions = [
  { label: '待处理', value: 0 },
  { label: '处理中', value: 1 },
  { label: '已完成', value: 2 },
  { label: '失败', value: 3 },
  { label: '已取消', value: 4 },
]

const uploadAccept = computed(() => getUploadAccept(spaceTypes.value))
// 文件夹选择不接受 accept 属性，需按扩展名白名单手动过滤
const allowedExtensions = computed(() => new Set(uploadAccept.value.split(',').map((e) => e.trim().toLowerCase())))
const readableSpaceTypes = computed(() => {
  const labels: Record<string, string> = {
    text: '文本',
    image: '图片',
    video: '视频',
    audio: '音频',
  }
  return spaceTypes.value.map((item) => labels[item] || item).join(' / ')
})

const uploadTipText = computed(() => {
  const parts: string[] = []
  if (hasModality(spaceTypes.value, 'text')) parts.push('PDF/DOC/DOCX/TXT/MD/CSV/HTML/JSON')
  if (hasModality(spaceTypes.value, 'image')) parts.push('JPG/PNG/GIF/WebP')
  if (hasModality(spaceTypes.value, 'video')) parts.push('MP4/MOV/AVI/MKV/WebM')
  if (hasModality(spaceTypes.value, 'audio')) parts.push('MP3/WAV/FLAC/AAC/OGG/M4A')
  const maxMB = Math.max(...spaceTypes.value.map(t => ({ text: 100, image: 100, video: 500, audio: 200 })[t] || 100))
  const docHint = hasModality(spaceTypes.value, 'text') ? '，其中 .doc 会自动转换为 .docx' : ''
  return `支持 ${parts.join(' + ')}${docHint}，视频最大 500MB，音频最大 200MB，其它最大 ${maxMB}MB，最多 ${MAX_UPLOAD_COUNT} 个`
})

function handleSelectionChange(rows: DocType[]) {
  selectedIds.value = rows.map((r) => r.id)
}

/**
 * 校验单个文件（扩展名 + 大小）并加入待上传队列。
 * el-upload 的 on-change 与文件夹选择两条路径共用，避免逻辑分叉。
 * 返回 true 表示入队成功；失败时自行弹出提示，调用方负责回滚 fileList 展示。
 */
function addFile(file: File): boolean {
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  const maxSizeMB = getFileMaxSize(ext)
  if (file.size > maxSizeMB * 1024 * 1024) {
    ElMessage.error(`文件 "${file.name}" 大小不能超过 ${maxSizeMB}MB`)
    return false
  }
  selectedFiles.value.push(file)
  return true
}

function handleFileChange(file: UploadFile) {
  if (!file.raw) {
    ElMessage.warning('文件读取失败，请重新选择')
    return
  }
  if (!addFile(file.raw)) {
    // 校验失败：el-upload 已把该项加入 fileList，这里移除展示
    fileList.value = fileList.value.filter((f) => f.uid !== file.uid)
  }
}

function handleFileRemove(file: UploadFile) {
  selectedFiles.value = selectedFiles.value.filter((f) => f.name !== file.name || f.lastModified !== file.raw?.lastModified)
}

function handleExceed() {
  ElMessage.warning(`最多只可上传 ${MAX_UPLOAD_COUNT} 个文件`)
}

/** 触发隐藏的文件夹选择 input。点击事件 stop 以免冒泡到 el-upload 打开普通文件选择。 */
function triggerFolderPick() {
  folderInputRef.value?.click()
}

/** 文件夹选择回调：递归收集文件夹下所有文件，按扩展名白名单与大小过滤后入队。 */
function handleFolderChange(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  if (!files.length) return

  let added = 0
  let skippedType = 0
  let skippedSize = 0
  for (const file of files) {
    if (selectedFiles.value.length >= MAX_UPLOAD_COUNT) {
      ElMessage.warning(`已达单次上传上限 ${MAX_UPLOAD_COUNT} 个文件，其余已忽略`)
      break
    }
    const ext = file.name.split('.').pop()?.toLowerCase() || ''
    if (!allowedExtensions.value.has(`.${ext}`)) {
      skippedType++
      continue
    }
    const maxSizeMB = getFileMaxSize(ext)
    if (file.size > maxSizeMB * 1024 * 1024) {
      skippedSize++
      continue
    }
    selectedFiles.value.push(file)
    fileList.value.push({
      name: file.name,
      uid: folderFileUid--,
      raw: file,
      status: 'ready',
    } as UploadFile)
    added++
  }

  if (added) {
    const detail = [skippedType && `${skippedType} 个不支持的类型`, skippedSize && `${skippedSize} 个超大小`].filter(Boolean).join('，')
    ElMessage.success(`已添加 ${added} 个文件${detail ? `（跳过 ${detail}）` : ''}`)
  } else if (skippedType || skippedSize) {
    ElMessage.warning('所选文件夹中没有符合要求的文件')
  }
  // 重置 input.value，否则连续选择同一文件夹不触发 change
  input.value = ''
}

function showUploadDialog() {
  fileList.value = []
  selectedFiles.value = []
  uploadDialogVisible.value = true
}

async function handleUpload() {
  if (selectedFiles.value.length === 0) {
    ElMessage.warning('请选择要上传的文件')
    return
  }

  uploadLoading.value = true
  try {
    const singleFile = selectedFiles.value[0]
    if (selectedFiles.value.length === 1 && !singleFile) {
      ElMessage.warning('未找到可上传文件，请重新选择')
      return
    }
    const filesToSend = selectedFiles.value.length === 1 ? singleFile : selectedFiles.value
    if (!filesToSend) {
      ElMessage.warning('未找到可上传文件，请重新选择')
      return
    }
    const res = await documentApi.uploadDocument(spaceId.value, kbId.value, filesToSend)

    if ('total' in res) {
      const batchRes = res as BatchUploadResponse
      if (batchRes.success.length > 0) {
        ElMessage.success(`${batchRes.success.length} 个文件上传成功`)
      }
      if (batchRes.failed.length > 0) {
        batchRes.failed.forEach((f) => ElMessage.error(`${f.filename}: ${f.error}`))
      }
    } else {
      ElMessage.success('文档上传成功')
    }

    uploadDialogVisible.value = false
    await fetchDocuments()
  } finally {
    uploadLoading.value = false
  }
}

function showProcessDialog(ids: number[]) {
  processTargetIds.value = ids
  processDialogVisible.value = true
}

async function handleProcess() {
  processLoading.value = true
  try {
    const res = await documentApi.batchProcessDocuments(spaceId.value, kbId.value, {
      document_ids: processTargetIds.value,
    })
    const failedMessages = res.results
      .filter((item) => item.status === 'failed')
      .map((item) => item.message)

    if (res.success > 0) {
      const parts = [`已提交 ${res.success} 个文档`]
      if (res.skipped > 0) parts.push(`${res.skipped} 个跳过`)
      ElMessage.success(parts.join('，'))
    }
    if (failedMessages.length > 0) {
      ElMessage.warning(failedMessages[0])
    }

    processDialogVisible.value = false
    selectedIds.value = []
    await fetchDocuments()
  } finally {
    processLoading.value = false
  }
}

async function fetchDocuments(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    const data = await documentApi.getDocuments(spaceId.value, kbId.value, {
      status: statusFilter.value,
      keyword: searchKeyword.value.trim() || undefined,
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value,
    })
    documents.value = data.items || []
    total.value = data.total || 0
    syncStatusPolling()
  } finally {
    if (showLoading) loading.value = false
  }
}

// ==================== 任务状态轮询 ====================
// 存在待处理/处理中文档时每 5s 静默刷新列表（复用 KbEvaluationView 轮询模式），
// 全部落到终态后自动停止，避免无意义的持续请求。
let statusPollTimer: ReturnType<typeof setInterval> | null = null

function hasActiveDocuments(): boolean {
  return documents.value.some(
    (d) => (d.status ?? 0) === DOC_STATUS.PENDING || (d.status ?? 0) === DOC_STATUS.PROCESSING,
  )
}

function syncStatusPolling(): void {
  if (hasActiveDocuments() && statusPollTimer === null) {
    statusPollTimer = setInterval(async () => {
      await fetchDocuments(false)
      if (!hasActiveDocuments()) stopStatusPolling()
    }, 5000)
  } else if (!hasActiveDocuments() && statusPollTimer !== null) {
    stopStatusPolling()
  }
}

function stopStatusPolling(): void {
  if (statusPollTimer) {
    clearInterval(statusPollTimer)
    statusPollTimer = null
  }
}

onUnmounted(stopStatusPolling)

function handleStatusFilterChange() {
  currentPage.value = 1
  fetchDocuments()
}

// 回车或清空时提交搜索，回到第 1 页
function handleSearch() {
  currentPage.value = 1
  fetchDocuments()
}

function goToDetail(docId: number) {
  // 携带当前页码，详情页“返回文档管理”时回到进入时的页，而非第 1 页
  router.push(
    `/home/spaces/${spaceId.value}/documents/${docId}?kbId=${kbId.value}&fromPage=${currentPage.value}`,
  )
}

async function handleDelete(doc: DocType) {
  try {
    await ElMessageBox.confirm(
      `确定要删除文档 "${doc.filename}" 吗？此操作不可恢复。`,
      '警告',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'error',
      },
    )
    await documentApi.deleteDocument(spaceId.value, kbId.value, doc.id)
    ElMessage.success('文档已删除')
    await fetchDocuments()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      return
    }
  }
}

function getStatusConfig(status: number | undefined) {
  return taskStatusMap[status ?? 0] ?? { text: '未知', type: 'info' as const }
}

// 文档状态枚举（与后端 TaskStatus / 前端 taskStatusMap 对齐：
// 0 待处理 / 1 处理中 / 2 已完成 / 3 失败 / 4 已取消）
const DOC_STATUS = {
  PENDING: 0,
  PROCESSING: 1,
  COMPLETED: 2,
  FAILED: 3,
  CANCELLED: 4,
} as const

/**
 * 各状态可执行操作（与后端校验严格对齐，避免按钮可见却报错）：
 * - 0 待处理：首次处理 / 详情 / 删除
 * - 1 处理中：取消 / 详情            （delete 被后端 DocumentAlreadyProcessingError 拒绝）
 * - 2 已完成：重新处理 / 详情 / 删除
 * - 3 失败：重试 / 详情 / 删除
 * - 4 已取消：重新处理 / 详情 / 删除
 */
function canProcess(doc: DocType): boolean {
  // 首次处理：从未入队解析的文档（仅状态 0 待处理）
  return (doc.status ?? 0) === DOC_STATUS.PENDING
}

function canReprocess(doc: DocType): boolean {
  // 重新处理：已跑过一次（已完成或已取消）后再次触发
  const s = doc.status ?? 0
  return s === DOC_STATUS.COMPLETED || s === DOC_STATUS.CANCELLED
}

function canCancel(doc: DocType): boolean {
  return (doc.status ?? 0) === DOC_STATUS.PROCESSING
}

function canRetry(doc: DocType): boolean {
  return (doc.status ?? 0) === DOC_STATUS.FAILED
}

function canDelete(doc: DocType): boolean {
  // 处理中的文档后端拒绝删除（有活跃任务），其余状态可删
  return (doc.status ?? 0) !== DOC_STATUS.PROCESSING
}

async function handleProcessSingle(doc: DocType) {
  const res = await documentApi.batchProcessDocuments(spaceId.value, kbId.value, {
    document_ids: [doc.id],
  })
  const item = res.results.find((result) => result.document_id === doc.id)
  if (item?.status === 'processing') {
    ElMessage.success(`文档 "${doc.filename}" 已加入任务项 #${item.task_item_id ?? '-'}`)
  } else if (item?.message) {
    ElMessage.warning(item.message)
  }
  await fetchDocuments()
}

async function handleCancelSingle(doc: DocType) {
  try {
    await ElMessageBox.confirm(
      `确定要取消文档 "${doc.filename}" 的处理吗？已完成的解析步骤会保留。`,
      '取消处理',
      {
        confirmButtonText: '确定取消',
        cancelButtonText: '继续处理',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  await documentApi.cancelDocument(spaceId.value, kbId.value, doc.id)
  ElMessage.success(`已取消文档 "${doc.filename}" 的处理`)
  await fetchDocuments()
}

async function handleRetrySingle(doc: DocType) {
  const res = await documentApi.retryDocument(spaceId.value, kbId.value, doc.id)
  ElMessage.success(`文档 "${doc.filename}" 已重新加入任务项 #${res.task_item_id ?? '-'}`)
  await fetchDocuments()
}

onMounted(async () => {
  // 从详情页返回时，恢复进入时的页码（由详情页 back 按钮通过 query.page 带回）
  const queryPage = Number(route.query.page)
  if (Number.isFinite(queryPage) && queryPage > 0) {
    currentPage.value = queryPage
  }
  await fetchDocuments()
  try {
    const kbConfig = await knowledgeBaseApi.getConfig(spaceId.value, kbId.value)
    kbName.value = kbConfig.name || ''
    kbStats.value = {
      document_count: kbConfig.stats?.document_count ?? 0,
      chunk_count: kbConfig.stats?.chunk_count ?? 0,
      completed_documents: kbConfig.stats?.completed_documents ?? 0,
      processing_documents: kbConfig.stats?.processing_documents ?? 0,
    }
    if (kbConfig.config?.space_type && Array.isArray(kbConfig.config.space_type) && kbConfig.config.space_type.length > 0) {
      spaceTypes.value = kbConfig.config.space_type
    }

    const space = await spaceApi.getSpace(spaceId.value)
    if (!kbConfig.config?.space_type || !Array.isArray(kbConfig.config.space_type) || kbConfig.config.space_type.length === 0) {
      spaceTypes.value = normalizeSpaceTypes(space.config)
    }
    embeddingInfo.value = {
      textModel: space.config?.embedding?.model || '',
      textDimension: space.config?.embedding?.dimension ?? null,
    }
  } catch {
    // keep default text
  }
})
</script>

<style scoped>
.document-view {
  padding-top: var(--space-2);
  height: 100%;
}

.kb-layout {
  display: flex;
  height: 100%;
}

.kb-content {
  flex: 1;
  min-width: 0;
  padding: var(--space-4) var(--space-5);
  overflow-y: auto;
}

.kb-overview {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 400px);
  align-items: stretch;
  width: 100%;
  margin: 0 0 var(--space-5);
  gap: var(--space-4);
  padding: 0;
}

.kb-overview__copy {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px 22px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-3xl);
  background: var(--color-bg-card-elevated);
  box-shadow: var(--shadow-md);
}

.kb-overview__eyebrow {
  display: inline-flex;
  align-self: flex-start;
  padding: 5px 10px;
  border-radius: var(--radius-full);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.kb-overview__title {
  margin: 0;
  font-size: clamp(24px, 2.6vw, 30px);
  line-height: 1.1;
  letter-spacing: -0.025em;
}

.kb-overview__desc {
  max-width: 460px;
  margin: 0;
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  font-size: 13px;
}

.kb-overview__stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  max-width: 100%;
  margin-top: 2px;
}

.kb-stat-card {
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  min-height: 88px;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card-elevated);
  box-shadow: var(--shadow-sm);
}

.kb-stat-card__label {
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 600;
}

.kb-stat-card strong {
  color: var(--color-text);
  font-size: clamp(24px, 2.8vw, 30px);
  line-height: 1;
  letter-spacing: -0.035em;
  font-family: var(--font-display);
}

.kb-overview__inherit {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-3xl);
  background: var(--color-bg-card-elevated);
  box-shadow: var(--shadow-md);
}

.inherit-head h2 {
  margin: 0 0 4px;
  font-size: 16px;
}

.inherit-head p {
  margin: 0;
  color: var(--color-text-muted);
  font-size: 12px;
  line-height: var(--leading-relaxed);
}

.inherit-grid {
  display: grid;
  gap: 12px;
}

.inherit-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card);
  position: relative;
  overflow: hidden;
}

.inherit-card--wide .inherit-value {
  line-height: 1.4;
}

.inherit-label {
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 600;
}

.inherit-value {
  color: var(--color-text);
  font-size: 13px;
  font-family: var(--font-mono);
  word-break: break-word;
}

.inherit-meta {
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
}

.left-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.right-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.filter-label {
  color: var(--color-text-muted);
  font-size: 13px;
  font-weight: 600;
}

.status-filter {
  width: 160px;
}

.search-input {
  width: 220px;
}

.filename-cell {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  cursor: pointer;
}

.file-icon {
  width: 32px;
  height: 38px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: var(--weight-bold);
  flex-shrink: 0;
  box-shadow: var(--shadow-sm);
  transition: box-shadow var(--transition-fast);
}

.filename-cell:hover .file-icon {
  box-shadow: var(--shadow-md);
}

.file-name {
  font-size: var(--text-sm);
  color: var(--color-text);
  font-weight: var(--weight-medium);
  transition: color var(--transition-fast);
}

.filename-cell:hover .file-name {
  color: var(--color-primary);
}

.text-muted {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.action-buttons {
  display: flex;
  gap: var(--space-1);
  justify-content: flex-end;
  flex-wrap: wrap;
}

.upload-area :deep(.el-upload-dragger) {
  padding: var(--space-10) var(--space-6);
  border-radius: var(--radius-xl);
  border: 2px dashed var(--color-border);
  background: var(--color-bg-card-elevated);
  transition: all var(--transition-base);
}

.upload-area :deep(.el-upload-dragger:hover) {
  border-color: var(--color-primary);
  background: var(--color-primary-subtle);
}

.upload-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
}

.upload-icon {
  font-size: var(--text-4xl);
  color: var(--color-text-faint);
}

.upload-text {
  font-size: var(--text-base);
  color: var(--color-text-secondary);
}

.upload-text em {
  color: var(--color-primary);
  font-style: normal;
}

.upload-tip {
  font-size: var(--text-sm);
  color: var(--color-text-faint);
}

.upload-folder-btn {
  margin-top: var(--space-2);
  font-size: var(--text-sm);
}

/* el-upload 内嵌按钮触发 dragger hover 高亮，禁用其 pointer-events 干扰 */
.upload-folder-btn :deep(span) {
  align-items: center;
  gap: var(--space-1);
}

.hidden-folder-input {
  display: none;
}

.process-desc {
  margin: 0 0 var(--space-4);
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
}

.doc-table-wrap {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-xs);
}

.doc-table-wrap :deep(.el-table) {
  --el-table-border-color: transparent;
}

.doc-table-wrap :deep(.el-table th.el-table__cell) {
  background: var(--color-bg-card);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-weight: var(--weight-medium);
  border-bottom: 1px solid var(--color-border);
}

.doc-table-wrap :deep(.el-table td.el-table__cell) {
  border-bottom: 1px solid var(--color-border-light);
}

.doc-table-wrap :deep(.el-table__body tr:last-child td.el-table__cell) {
  border-bottom: none;
}

.doc-table-wrap :deep(.el-table tr:hover > td.el-table__cell) {
  background: var(--color-bg-hover) !important;
}

.document-view :deep(.el-upload-list) {
  max-height: 300px;
  overflow-y: auto;
}

@media (max-width: 1100px) {
  .kb-overview {
    grid-template-columns: 1fr;
  }

  .kb-overview__stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    max-width: 100%;
  }

  /* 中窄视口：内容区左右留白收紧，给表格让位 */
  .kb-content {
    padding: var(--space-4) var(--space-3);
  }

  .kb-overview__copy,
  .kb-overview__inherit {
    padding: var(--space-4);
  }
}

@media (max-width: 900px) {
  /* 窄视口：收掉次要列宽，表格总宽降到 ~600px 内不再需要横向滚动 */
  .doc-table-wrap :deep(.el-table) {
    font-size: var(--text-xs);
  }

  .action-bar {
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .right-actions {
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .search-input {
    width: 100%;
    min-width: 140px;
    flex: 1;
  }

  .status-filter {
    width: 120px;
  }
}

@media (max-width: 768px) {
  .kb-content {
    padding: var(--space-3);
  }

  .kb-overview__stats {
    grid-template-columns: 1fr;
    max-width: 100%;
  }

  .action-bar {
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-3);
  }

  .right-actions {
    justify-content: space-between;
  }

  .status-filter {
    width: 100%;
  }

  .search-input {
    width: 100%;
  }
}
</style>


