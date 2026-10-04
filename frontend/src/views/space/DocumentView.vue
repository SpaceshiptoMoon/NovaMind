<template>
  <div class="document-view">
    <div class="kb-layout">
      <KbSidebar :nav-items="kbNavItems" />

      <div class="kb-content">
        <!-- 非法 kbId（地址栏手改/坏链接）空态，替代打出 NaN 请求 -->
        <el-empty v-if="kbInvalid" description="知识库不存在或链接无效，请从知识库列表重新进入" />

        <section v-else class="page-head">
          <div class="page-head__main">
            <p class="page-head__eyebrow">知识库</p>
            <h1 class="page-head__title">{{ kbName || '文档管理' }}</h1>
            <p class="page-head__desc" :title="inheritSummary">
              <span class="inherit-dot" :class="{ 'is-off': !embeddingInfo.textModel }"></span>
              <span class="page-head__desc-text">{{ inheritSummary }}</span>
            </p>
          </div>
          <el-button type="primary" class="page-head__cta" @click="showUploadDialog">
            <el-icon><Upload /></el-icon>
            上传文档
          </el-button>
        </section>

        <!-- 单行统计条：常显三项，处理中/待处理仅在有活跃文档时出现（避免满屏无效 0） -->
        <div class="stats-bar">
          <div class="stats-item">
            <span class="stats-label">文档</span>
            <strong class="stats-value">{{ kbStats.document_count }}</strong>
          </div>
          <span class="stats-divider"></span>
          <div class="stats-item">
            <span class="stats-label">分块</span>
            <strong class="stats-value">{{ kbStats.chunk_count }}</strong>
          </div>
          <span class="stats-divider"></span>
          <div class="stats-item">
            <span class="stats-label">已完成</span>
            <strong class="stats-value">{{ kbStats.completed_documents }}</strong>
          </div>
          <template v-if="kbStats.processing_documents > 0">
            <span class="stats-divider"></span>
            <div class="stats-item">
              <span class="stats-label">处理中</span>
              <strong class="stats-value is-warning">{{ kbStats.processing_documents }}</strong>
            </div>
          </template>
        </div>

        <div class="action-bar">
          <div class="left-actions">
            <el-button v-if="selectedIds.length > 0" @click="showProcessDialog(selectedIds)">
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
              <template #prefix
                ><el-icon><Search /></el-icon
              ></template>
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

        <!-- 文档卡片网格（类型色块 + 文件名 + 元信息 + hover 操作） -->
        <div v-loading="loading" class="doc-grid-wrap">
          <div v-if="documents.length === 0 && !loading" class="doc-grid-empty">
            <EmptyState
              :variant="searchKeyword || statusFilter !== undefined ? 'search' : 'data'"
              :headline="
                searchKeyword || statusFilter !== undefined ? '没有符合条件的文档' : '还没有文档'
              "
              :description="
                searchKeyword || statusFilter !== undefined
                  ? '换个关键词或清除筛选条件再试'
                  : '上传 PDF、Word、Markdown 等文件，处理后即可检索提问'
              "
            >
              <el-button
                v-if="!searchKeyword && statusFilter === undefined"
                type="primary"
                @click="showUploadDialog"
              >
                <el-icon><Upload /></el-icon>
                上传第一个文档
              </el-button>
            </EmptyState>
          </div>
          <div v-for="doc in documents" :key="doc.id" class="doc-card" @click="goToDetail(doc.id)">
            <!-- 选择复选框（hover / 已选显示） -->
            <el-checkbox
              class="doc-card-check"
              :model-value="selectedIds.includes(doc.id)"
              @click.stop
              @change="toggleDocSelection(doc)"
            />

            <!-- 类型色块（ima 缩略区语言） -->
            <div
              class="doc-card-cover"
              :style="{
                background: getFileTypeStyle(doc.file_type).bg,
                color: getFileTypeStyle(doc.file_type).color,
              }"
            >
              {{ doc.file_type.toUpperCase().slice(0, 3) }}
            </div>

            <!-- 主体 -->
            <div class="doc-card-body">
              <div class="doc-card-name" :title="doc.filename">{{ doc.filename }}</div>
              <div class="doc-card-meta">
                <span>{{ formatFileSize(doc.file_size) }}</span>
                <template v-if="doc.duration_seconds">
                  <span class="meta-dot">·</span>
                  <span>{{ formatDuration(doc.duration_seconds) }}</span>
                </template>
                <span class="meta-dot">·</span>
                <span>{{ doc.chunk_count ?? 0 }} 分块</span>
                <span class="meta-dot">·</span>
                <span>{{ formatShortDate(doc.created_at) }}</span>
              </div>
            </div>

            <!-- 状态 + 操作 -->
            <div class="doc-card-side">
              <el-tag :type="getStatusConfig(doc.status).type" effect="plain" size="small">
                {{ getStatusConfig(doc.status).text }}
              </el-tag>
              <div class="doc-card-actions" @click.stop>
                <el-tooltip v-if="canProcess(doc)" content="首次处理" placement="top">
                  <el-button
                    :icon="VideoPlay"
                    circle
                    size="small"
                    type="primary"
                    @click="handleProcessSingle(doc)"
                  />
                </el-tooltip>
                <el-tooltip v-if="canReprocess(doc)" content="重新处理" placement="top">
                  <el-button
                    :icon="RefreshRight"
                    circle
                    size="small"
                    type="primary"
                    @click="handleProcessSingle(doc)"
                  />
                </el-tooltip>
                <el-tooltip v-if="canCancel(doc)" content="取消" placement="top">
                  <el-button
                    :icon="Close"
                    circle
                    size="small"
                    type="warning"
                    @click="handleCancelSingle(doc)"
                  />
                </el-tooltip>
                <el-tooltip v-if="canRetry(doc)" content="重试" placement="top">
                  <el-button
                    :icon="RefreshRight"
                    circle
                    size="small"
                    type="warning"
                    @click="handleRetrySingle(doc)"
                  />
                </el-tooltip>
                <el-tooltip content="详情" placement="top">
                  <el-button :icon="View" circle size="small" @click="goToDetail(doc.id)" />
                </el-tooltip>
                <el-tooltip v-if="canDelete(doc)" content="删除" placement="top">
                  <el-button
                    :icon="Delete"
                    circle
                    size="small"
                    type="danger"
                    @click="handleDelete(doc)"
                  />
                </el-tooltip>
              </div>
            </div>
          </div>
        </div>

        <Pagination
          :page="currentPage"
          :page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @update:page="
            (p: number) => {
              currentPage = p
              fetchDocuments()
            }
          "
          @update:page-size="
            (s: number) => {
              pageSize = s
              currentPage = 1
              fetchDocuments()
            }
          "
        />

        <el-dialog
          v-model="uploadDialogVisible"
          title="上传文档"
          width="680px"
          destroy-on-close
          class="upload-dialog"
        >
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
              <div class="upload-text">拖拽文件到此处，或<em>点击上传</em></div>
              <div class="upload-tip">
                {{ uploadTipText }}
              </div>
              <el-button
                text
                type="primary"
                class="upload-folder-btn"
                @click.stop="triggerFolderPick"
              >
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
          <div v-if="uploadProgressVisible" class="chunk-progress">
            <el-progress :percentage="uploadProgress" :stroke-width="10" />
            <div class="chunk-progress-tip">大文件分片上传中，请勿关闭页面</div>
          </div>
          <template #footer>
            <el-button @click="uploadDialogVisible = false">取消</el-button>
            <el-button
              type="primary"
              :loading="uploadLoading"
              @click="handleUpload"
              :disabled="selectedFiles.length === 0"
            >
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
/**
 * 知识库文档管理页。
 *
 * 对应路由 /home/spaces/:id/knowledge-bases/:kbId/documents，展示知识库概览统计与
 * 空间继承能力（embedding/数据类型），承载文档上传（多选 + 文件夹递归）、搜索筛选、
 * 卡片式批量选择、单文档处理/取消/重试/删除，跳详情时携带页码供返回恢复。
 * 存在待处理/处理中文档时每 5s 静默轮询刷新，全部到终态自动停止。
 */

import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Close,
  Delete,
  FolderOpened,
  RefreshRight,
  Search,
  Upload,
  UploadFilled,
  VideoPlay,
  View,
} from '@element-plus/icons-vue'
import type { UploadFile } from 'element-plus'

import { documentApi, knowledgeBaseApi } from '@/api/knowledge'
import { spaceApi } from '@/api/space'
import type { BatchUploadResponse, Document as DocType } from '@/api/types'
import {
  KbSidebar,
  buildKbNavItems,
  getFileMaxSize,
  getFileTypeStyle,
  getUploadAccept,
  hasModality,
  normalizeSpaceTypes,
  taskStatusMap,
} from '@/components/knowledge'
import Pagination from '@/components/common/Pagination.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { formatDuration, formatFileSize, formatShortDate } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))
// 非法 kbId（手改地址栏/坏链接 → NaN）兜 0；onMounted 拦截后走空态，不打 NaN 请求
const kbId = computed(() => Number(route.params.kbId) || 0)
const kbInvalid = computed(() => kbId.value === 0)

const kbNavItems = computed(() =>
  buildKbNavItems({
    spaceId: spaceId.value,
    kbId: kbId.value,
    currentRouteName: route.name,
  }),
)

const loading = ref(false)
const uploadLoading = ref(false)
const processLoading = ref(false)
const uploadDialogVisible = ref(false)
const processDialogVisible = ref(false)

// 分片上传聚合进度（>100MB 单文件自动走分片路径时展示）
const uploadProgress = ref(0)
const uploadProgressVisible = ref(false)

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
const allowedExtensions = computed(
  () => new Set(uploadAccept.value.split(',').map((e) => e.trim().toLowerCase())),
)
const readableSpaceTypes = computed(() => {
  const labels: Record<string, string> = {
    text: '文本',
    image: '图片',
    video: '视频',
    audio: '音频',
  }
  return spaceTypes.value.map((item) => labels[item] || item).join(' / ')
})

/** 页头继承能力一行摘要：向量模型状态 + 可用类型（替代旧的双卡占版面） */
const inheritSummary = computed(() => {
  const model = embeddingInfo.value.textModel
  const dim = embeddingInfo.value.textDimension
  const modelPart = model ? `${model}${dim ? `（${dim} 维）` : ''}` : '向量模型未配置'
  return `${modelPart} · 可上传 ${readableSpaceTypes.value}`
})

const uploadTipText = computed(() => {
  const parts: string[] = []
  if (hasModality(spaceTypes.value, 'text')) parts.push('PDF/DOC/DOCX/TXT/MD/CSV/HTML/JSON')
  if (hasModality(spaceTypes.value, 'image')) parts.push('JPG/PNG/GIF/WebP')
  if (hasModality(spaceTypes.value, 'video')) parts.push('MP4/MOV/AVI/MKV/WebM')
  if (hasModality(spaceTypes.value, 'audio')) parts.push('MP3/WAV/FLAC/AAC/OGG/M4A')
  const maxMB = Math.max(
    ...spaceTypes.value.map((t) => ({ text: 100, image: 100, video: 500, audio: 200 })[t] || 100),
  )
  const docHint = hasModality(spaceTypes.value, 'text') ? '，其中 .doc 会自动转换为 .docx' : ''
  return `支持 ${parts.join(' + ')}${docHint}，视频最大 500MB，音频最大 200MB，其它最大 ${maxMB}MB，最多 ${MAX_UPLOAD_COUNT} 个`
})

// 卡片网格的选择切换（替代 el-table selection 事件）
function toggleDocSelection(doc: DocType) {
  const idx = selectedIds.value.indexOf(doc.id)
  if (idx >= 0) {
    selectedIds.value.splice(idx, 1)
  } else {
    selectedIds.value.push(doc.id)
  }
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
  selectedFiles.value = selectedFiles.value.filter(
    (f) => f.name !== file.name || f.lastModified !== file.raw?.lastModified,
  )
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
    const detail = [
      skippedType && `${skippedType} 个不支持的类型`,
      skippedSize && `${skippedSize} 个超大小`,
    ]
      .filter(Boolean)
      .join('，')
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

/** 上传入队文件：单文件走单传接口，多文件走批量接口并逐项播报成败。 */
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

    // 单文件超阈值自动切分片上传（大视频防单请求巨体；分片天然绕开
    // nginx client_max_body_size，单片 timeout/重试让慢网络可恢复）
    const CHUNKED_THRESHOLD = 100 * 1024 * 1024
    if (!Array.isArray(filesToSend) && filesToSend.size > CHUNKED_THRESHOLD) {
      uploadProgress.value = 0
      uploadProgressVisible.value = true
      try {
        await documentApi.uploadDocumentChunked(
          spaceId.value,
          kbId.value,
          filesToSend,
          (percent) => {
            uploadProgress.value = percent
          },
        )
        ElMessage.success('文档分片上传成功')
        uploadDialogVisible.value = false
        await fetchDocuments()
      } finally {
        uploadProgressVisible.value = false
      }
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

/** 分页拉取文档列表（带状态/关键词过滤），并按活跃文档启停状态轮询。 */
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

/** 按活跃文档存在性启停 5s 轮询定时器（幂等），全部到终态后自动停止。 */
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
    await ElMessageBox.confirm(`确定要删除文档 "${doc.filename}" 吗？此操作不可恢复。`, '警告', {
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
      type: 'error',
    })
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

/** 初始化：恢复详情页带回的页码，加载文档列表，再拉 KB 配置/统计与空间继承信息。 */
onMounted(async () => {
  // 非法 kbId：不再发任何请求（文档列表/KB 配置都依赖 kbId），落到模板空态
  if (kbInvalid.value) return
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
    if (
      kbConfig.config?.space_type &&
      Array.isArray(kbConfig.config.space_type) &&
      kbConfig.config.space_type.length > 0
    ) {
      spaceTypes.value = kbConfig.config.space_type
    }

    const space = await spaceApi.getSpace(spaceId.value)
    if (
      !kbConfig.config?.space_type ||
      !Array.isArray(kbConfig.config.space_type) ||
      kbConfig.config.space_type.length === 0
    ) {
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
/* 与其余 KB 子页面同款满高根容器（不带根级 padding），保证 KbSidebar 跨模块切换高度一致；
   顶部呼吸感由 .kb-content 自身 padding 提供 */
.document-view {
  height: 100%;
}

.kb-layout {
  display: flex;
  height: 100%;
}

/* 窄屏：KB 二级侧栏改横向滚动条（WikiBrowserView 960px 同款降级思路，
   侧栏不再挤压主内容） */
@media (max-width: 960px) {
  .kb-layout {
    flex-direction: column;
  }

  .kb-layout :deep(.kb-sidebar) {
    width: 100%;
    flex-direction: row;
    overflow-x: auto;
    border-right: none;
    border-bottom: 1px solid var(--color-border-light);
    padding: var(--space-2) var(--space-3);
  }

  .kb-layout :deep(.sidebar-item.active)::before {
    display: none;
  }
}

.kb-content {
  flex: 1;
  min-width: 0;
  padding: var(--space-4) var(--space-5);
  overflow-y: auto;
}

/* ===== 紧凑页头：左标题+继承摘要，右主 CTA（对齐 ModelConfigView page-header 骨架） ===== */
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
  margin: 0 0 var(--space-4);
}

.page-head__eyebrow {
  margin: 0 0 2px;
  font-size: 12px;
  font-weight: var(--weight-semibold);
  letter-spacing: 0.1em;
  color: var(--color-text-faint);
}

.page-head__title {
  margin: 0;
  font-size: var(--text-2xl);
  letter-spacing: var(--tracking-tight);
}

.page-head__desc {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 4px 0 0;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  min-width: 0;
  max-width: 560px;
}

.page-head__main {
  /* flex 链允许收缩（min-width:auto 会拒绝窄于内容），desc 才能收到省略号 */
  min-width: 0;
  flex: 1 1 auto;
}

/* 摘要文本单独收敛省略（flex 子项 text-overflow 需挂在文本节点上才生效） */
.page-head__desc-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 继承能力状态点：已配置=墨水蓝、未配置=灰（页头一行内的轻量状态锚点） */
.inherit-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--color-primary);
  flex-shrink: 0;
}

.inherit-dot.is-off {
  background: var(--color-text-faint);
}

/* ===== 单行统计条（WikiBrowserView wiki-stats 同款语言） ===== */
.stats-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-5);
  padding: var(--space-3) var(--space-5);
  margin: 0 0 var(--space-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  background: var(--color-bg-card);
}

.stats-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.stats-label {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.stats-value {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: var(--weight-semibold);
  letter-spacing: var(--tracking-tight);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.stats-value.is-warning {
  color: var(--color-warning);
}

.stats-divider {
  align-self: stretch;
  width: 1px;
  background: var(--color-border-light);
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

.text-muted {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
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

/* 分片上传聚合进度（大文件） */
.chunk-progress {
  margin-top: var(--space-3);
}

.chunk-progress-tip {
  margin-top: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-faint);
}

.process-desc {
  margin: 0 0 var(--space-4);
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
}

/* ========================================
   文档卡片网格（ima 式：类型色块 + 文件名 + 元信息 + hover 操作）
   ======================================== */
.doc-grid-wrap {
  display: grid;
  /* 轨道均分整行宽度（无右侧留白），但卡片本体 max-width 420px 居中不拉伸 */
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--space-3);
  min-height: 200px;
  align-content: start;
}

.doc-grid-empty {
  grid-column: 1 / -1;
  padding: var(--space-6) var(--space-4) var(--space-10);
}

.doc-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  /* 轨道宽但卡片不跟宽：max-width 封顶 + 水平居中（视觉均匀，无大留白） */
  max-width: 420px;
  width: 100%;
  margin: 0 auto;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
  cursor: pointer;
  /* 文件名两行化后统一高度基准，单行名与双行名卡片不忽高忽低 */
  min-height: 76px;
  transition:
    border-color var(--transition-fast),
    box-shadow var(--transition-fast),
    transform var(--transition-base);
}

.doc-card:hover {
  border-color: var(--color-border);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

/* 选择复选框：hover / 已选时可见，贴卡片左上角 */
.doc-card-check {
  position: absolute;
  top: 2px;
  left: 3px;
  opacity: 0;
  transition: opacity var(--transition-fast);
}

.doc-card:hover .doc-card-check,
.doc-card-check.is-checked {
  opacity: 1;
}

/* 类型色块（缩略区语言） */
.doc-card-cover {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: var(--radius-lg);
  font-size: 12px;
  font-weight: var(--weight-bold);
  letter-spacing: 0.04em;
  flex-shrink: 0;
  user-select: none;
}

/* 主体 */
.doc-card-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.doc-card-name {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  /* 长文件名两行收敛（学术论文标题普遍超长，单行省略丢信息），配 line-clamp */
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
  word-break: break-all;
  line-height: 1.45;
}

.doc-card-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.meta-dot {
  color: var(--color-text-faint);
}

/* 状态 + hover 操作 */
.doc-card-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  flex-shrink: 0;
}

.doc-card-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity var(--transition-base);
}

.doc-card:hover .doc-card-actions {
  opacity: 1;
}

.document-view :deep(.el-upload-list) {
  max-height: 300px;
  overflow-y: auto;
}

@media (max-width: 1100px) {
  /* 中窄视口：内容区留白收紧 */
  .kb-content {
    padding: var(--space-4) var(--space-3);
  }
}

@media (max-width: 900px) {
  /* 单列且允许轨道收到 0：极窄视口下卡片跟容器宽收缩（minmax 下限 0 防固定 min 300px
     撑出容器内横向滚动——评审 320px 实测 362px 列宽溢出教训） */
  .doc-grid-wrap {
    grid-template-columns: minmax(0, 1fr);
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

/* 极窄视口（≤480px）：卡片内部换结构——hover 操作列与复选框隐藏（触屏无 hover，
   操作入口由详情页承载），卡片改纵向堆叠（cover 上、名称中、meta 下、状态标签尾），
   名称列拿到满宽不再被固定子项挤压（R2/R3 评审 320px 实测：两行堆叠下 body 仅 56px） */
@media (max-width: 480px) {
  .doc-card {
    flex-direction: column;
    align-items: stretch;
  }

  .doc-card-actions,
  .doc-card-check {
    display: none;
  }

  .doc-card-side {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
}
</style>
