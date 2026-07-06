<template>
  <div class="document-view">
    <!-- 子导航标签 -->
    <div class="page-nav">
      <div class="nav-tabs">
        <router-link
          :to="`/home/spaces/${spaceId}/knowledge-bases/${kbId}/documents`"
          class="nav-tab"
          :class="{ active: route.name === 'Documents' || route.name === 'DocumentDetail' }"
        >
          文档管理
        </router-link>
        <router-link
          :to="`/home/spaces/${spaceId}/search?kbId=${kbId}`"
          class="nav-tab"
          :class="{ active: route.name === 'Search' }"
        >
          检索
        </router-link>
        <router-link
          :to="`/home/spaces/${spaceId}/knowledge-bases/${kbId}/evaluation`"
          class="nav-tab"
          :class="{ active: route.name === 'KbEvaluation' }"
        >
          评测
        </router-link>
      </div>
    </div>

    <!-- 操作栏 -->
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
        <el-select v-model="statusFilter" placeholder="状态筛选" clearable style="width: 130px" @change="handleFilterChange">
          <el-option label="全部" value="" />
          <el-option label="待处理" value="uploaded" />
          <el-option label="处理中" value="processing" />
          <el-option label="已完成" value="completed" />
          <el-option label="失败" value="failed" />
        </el-select>
      </div>
    </div>

    <!-- 文档列表 -->
    <div v-loading="loading" class="doc-table-wrap">
      <el-table
        :data="documents"
        @selection-change="handleSelectionChange"
        class="doc-table"
      >
        <el-table-column type="selection" width="45" />
        <el-table-column prop="filename" label="文件名" min-width="220">
          <template #default="{ row }">
            <div class="filename-cell" @click="goToDetail(row.id)">
              <div class="file-icon" :style="{ background: getFileTypeStyle(row.file_type).bg, color: getFileTypeStyle(row.file_type).color }">
                {{ row.file_type.toUpperCase().slice(0, 3) }}
              </div>
              <span class="file-name">{{ row.filename }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="file_size" label="大小" width="90" align="center">
          <template #default="{ row }">
            <span class="text-muted">{{ formatFileSize(row.file_size) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="分块" width="70" align="center">
          <template #default="{ row }">
            <span class="text-muted">{{ row.chunk_count ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110" align="center">
          <template #default="{ row }">
            <div class="status-cell">
              <el-progress
                v-if="isProcessing(row.status)"
                :percentage="100"
                :indeterminate="true"
                :stroke-width="3"
                :show-text="false"
                class="status-progress"
              />
              <StatusTag :status="String(row.status)" :status-map="docStatusMap" size="small" />
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="上传时间" width="140">
          <template #default="{ row }">
            <span class="text-muted">{{ formatDate(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="" width="120" fixed="right" align="right">
          <template #default="{ row }">
            <div class="action-buttons">
              <el-tooltip v-if="isProcessing(row.status)" content="取消处理" placement="top">
                <el-button :icon="CircleClose" circle size="small" :loading="cancelLoadingId === row.id" aria-label="取消处理" @click="handleCancel(row)" />
              </el-tooltip>
              <el-tooltip v-if="canProcess(row.status)" :content="(row.status === 'completed' || row.status === 2) ? '重新解析' : '处理'" placement="top">
                <el-button :icon="Refresh" circle size="small" aria-label="处理" @click="handleSingleProcess(row)" />
              </el-tooltip>
              <el-tooltip v-if="isFailed(row.status)" content="重试" placement="top">
                <el-button :icon="RefreshRight" circle size="small" :loading="retryLoadingId === row.id" aria-label="重试" @click="handleRetry(row)" />
              </el-tooltip>
              <el-tooltip content="详情" placement="top">
                <el-button :icon="View" circle size="small" aria-label="详情" @click="goToDetail(row.id)" />
              </el-tooltip>
              <el-tooltip content="删除" placement="top">
                <el-button :icon="Delete" circle size="small" aria-label="删除" @click="handleDelete(row)" />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 分页 -->
    <Pagination
      :page="currentPage"
      :page-size="pageSize"
      :total="total"
      :page-sizes="[10, 20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      @update:page="(p: number) => { currentPage = p; fetchDocuments() }"
      @update:page-size="(s: number) => { pageSize = s; currentPage = 1; fetchDocuments() }"
    />

    <!-- 上传文档弹窗 -->
    <el-dialog v-model="uploadDialogVisible" title="上传文档" width="680px" destroy-on-close>
      <el-form label-width="80px">
        <el-form-item label="选择文件">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="20"
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
                拖拽文件到此处，或 <em>点击上传</em>
              </div>
              <div class="upload-tip">
                {{ uploadTipText }}
              </div>
            </div>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploadLoading" @click="handleUpload" :disabled="selectedFiles.length === 0">
          上传 ({{ selectedFiles.length }})
        </el-button>
      </template>
    </el-dialog>

    <!-- 处理文档弹窗 -->
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
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, UploadFilled, Refresh, RefreshRight, CircleClose, View, Delete } from '@element-plus/icons-vue'
import { documentApi } from '@/api/document'
import { spaceApi } from '@/api/space'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import StatusTag from '@/components/common/StatusTag.vue'
import Pagination from '@/components/common/Pagination.vue'
import type { Document as DocType, BatchUploadResponse } from '@/api/types'
import type { UploadFile } from 'element-plus'
import { docStatusMap, getFileTypeStyle, normalizeSpaceTypes, getUploadAccept, getFileMaxSize, hasModality } from '@/utils/document'
import { formatFileSize, formatDate } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))
const kbId = computed(() => Number(route.params.kbId))

const loading = ref(false)
const uploadLoading = ref(false)
const spaceTypes = ref<string[]>(['text'])

const uploadAccept = computed(() => getUploadAccept(spaceTypes.value))

const uploadTipText = computed(() => {
  const parts: string[] = []
  if (hasModality(spaceTypes.value, 'text')) parts.push('PDF/Word/TXT/MD/Excel/PPT/HTML/JSON')
  if (hasModality(spaceTypes.value, 'image')) parts.push('JPG/PNG/GIF/WebP')
  if (hasModality(spaceTypes.value, 'video')) parts.push('MP4/MOV/AVI/MKV/WebM')
  if (hasModality(spaceTypes.value, 'audio')) parts.push('MP3/WAV/FLAC/AAC/OGG/M4A')
  const maxMB = Math.max(...spaceTypes.value.map(t => ({ text: 100, image: 100, video: 500, audio: 200 })[t] || 100))
  return `支持 ${parts.join(' + ')}，视频最大500MB，音频最大200MB，其余最大100MB，最多 20 个`
})

const uploadDialogVisible = ref(false)
const statusFilter = ref<string>('')
const documents = ref<DocType[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const fileList = ref<UploadFile[]>([])
const selectedFiles = ref<File[]>([])
const selectedIds = ref<number[]>([])

// 处理弹窗
const processDialogVisible = ref(false)
const processLoading = ref(false)
const processTargetIds = ref<number[]>([])


function handleSelectionChange(rows: DocType[]) {
  selectedIds.value = rows.map((r) => r.id)
}

function handleFilterChange() {
  currentPage.value = 1
  fetchDocuments()
}

// === 上传 ===

function handleFileChange(file: UploadFile) {
  if (file.raw) {
    const ext = file.name.split('.').pop()?.toLowerCase() || ''
    const maxSizeMB = getFileMaxSize(ext)
    if (file.raw.size > maxSizeMB * 1024 * 1024) {
      ElMessage.error(`文件 "${file.name}" 大小不能超过 ${maxSizeMB}MB`)
      fileList.value = fileList.value.filter((f) => f.uid !== file.uid)
      return
    }
    selectedFiles.value.push(file.raw)
  }
}

function handleFileRemove(file: UploadFile) {
  selectedFiles.value = selectedFiles.value.filter((f) => f.name !== file.name || f.lastModified !== file.raw?.lastModified)
}

function handleExceed() {
  ElMessage.warning('最多只能上传 20 个文件')
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
    const filesToSend = selectedFiles.value.length === 1 ? selectedFiles.value[0] : selectedFiles.value
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
    fetchDocuments()
  } catch {
    // Error already shown by response interceptor
  } finally {
    uploadLoading.value = false
  }
}

// === 处理 ===

const cancelLoadingId = ref<number | null>(null)
const retryLoadingId = ref<number | null>(null)

function isProcessing(status: string | number): boolean {
  return status === 'processing' || status === 1
}

function isFailed(status: string | number): boolean {
  return status === 'failed' || status === 3
}

function canProcess(status: string | number): boolean {
  return status === 'uploaded' || status === 'completed' || status === 0 || status === 2
}

function showProcessDialog(ids: number[]) {
  processTargetIds.value = ids
  processDialogVisible.value = true
}

async function handleProcess() {
  processLoading.value = true
  try {
    await documentApi.batchProcessDocuments(spaceId.value, kbId.value, {
      document_ids: processTargetIds.value,
    })
    ElMessage.success('已提交处理任务')
    processDialogVisible.value = false
    selectedIds.value = []
    fetchDocuments()
  } catch {
    // Error already shown by response interceptor
  } finally {
    processLoading.value = false
  }
}

async function handleSingleProcess(row: DocType) {
  const isCompleted = row.status === 'completed' || row.status === 2
  if (isCompleted) {
    try {
      await ElMessageBox.confirm(
        `确定要重新解析文档 "${row.filename}" 吗？将清除旧的分块数据。`,
        '重新解析',
        { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' },
      )
      processLoading.value = true
      await documentApi.reprocessDocument(spaceId.value, kbId.value, row.id)
      ElMessage.success('已提交重新解析任务')
      fetchDocuments()
    } catch (error: unknown) {
      if ((error as string) !== 'cancel') {
        // Error already shown by response interceptor
      }
    } finally {
      processLoading.value = false
    }
  } else {
    showProcessDialog([row.id])
  }
}

async function handleCancel(row: DocType) {
  try {
    await ElMessageBox.confirm(
      `确定要取消文档 "${row.filename}" 的处理吗？`,
      '取消处理',
      { confirmButtonText: '确定取消', cancelButtonText: '返回', type: 'warning' },
    )
    cancelLoadingId.value = row.id
    await documentApi.cancelDocument(spaceId.value, kbId.value, row.id)
    ElMessage.success('取消请求已发送')
    fetchDocuments()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      // Error already shown by response interceptor
    }
  } finally {
    cancelLoadingId.value = null
  }
}

async function handleRetry(row: DocType) {
  try {
    await ElMessageBox.confirm(
      `确定要重试文档 "${row.filename}" 的处理吗？将清除旧的分块数据并重新解析。`,
      '重试处理',
      { confirmButtonText: '确定重试', cancelButtonText: '取消', type: 'info' },
    )
    retryLoadingId.value = row.id
    await documentApi.retryDocument(spaceId.value, kbId.value, row.id)
    ElMessage.success('已提交重试任务')
    fetchDocuments()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      // Error already shown by response interceptor
    }
  } finally {
    retryLoadingId.value = null
  }
}

// === 列表 ===

async function fetchDocuments() {
  loading.value = true
  try {
    const data = await documentApi.getDocuments(spaceId.value, kbId.value, {
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value,
      ...(statusFilter.value ? { status: statusFilter.value } : {}),
    })
    documents.value = data.items || []
    total.value = data.total || 0
  } catch {
    // Error already shown by response interceptor
  } finally {
    loading.value = false
  }
}

function goToDetail(docId: number) {
  router.push(`/home/spaces/${spaceId.value}/documents/${docId}?kbId=${kbId.value}`)
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
    fetchDocuments()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      // Error already shown by response interceptor
    }
  }
}

onMounted(async () => {
  fetchDocuments()
  try {
    // 优先从 KB config 读取 space_type，fallback 到 Space config
    const kbConfig = await knowledgeBaseApi.getConfig(spaceId.value, kbId.value)
    if (kbConfig.config?.space_type && Array.isArray(kbConfig.config.space_type) && kbConfig.config.space_type.length > 0) {
      spaceTypes.value = kbConfig.config.space_type
    } else {
      const space = await spaceApi.getSpace(spaceId.value)
      spaceTypes.value = normalizeSpaceTypes(space.config)
    }
  } catch {
    // 默认 text
  }
})
</script>

<style scoped>
.document-view {
  padding-top: var(--space-2);
}

/* ===== Sub Navigation ===== */
.page-nav {
  margin-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.nav-tabs {
  display: flex;
  gap: 0;
}

.nav-tab {
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  text-decoration: none;
  transition: all var(--transition-fast);
  position: relative;
  font-weight: var(--weight-medium);
}

.nav-tab:hover {
  color: var(--color-text-secondary);
}

.nav-tab.active {
  color: var(--color-primary);
}

.nav-tab.active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  background: var(--color-primary);
  border-radius: 2px 2px 0 0;
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

/* 文件名单元格 */
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
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.5),
    inset 0 -2px 3px rgba(0, 0, 0, 0.05),
    0 1px 2px rgba(15, 23, 42, 0.08);
  transition: box-shadow var(--transition-fast);
}

.filename-cell:hover .file-icon {
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.55),
    inset 0 -2px 3px rgba(0, 0, 0, 0.06),
    0 2px 6px rgba(15, 23, 42, 0.12);
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

/* 状态列 */
.status-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
}

.status-progress {
  width: 60px;
}

/* 操作按钮 */
.action-buttons {
  display: flex;
  gap: var(--space-1);
  justify-content: flex-end;
}

/* 上传区域 */
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

.form-tip {
  margin-left: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.process-desc {
  margin: 0 0 var(--space-4);
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
}

/* ===== 文档表格：Linear 风（发丝线分隔 · 去斑马纹 · 扁平） ===== */
.doc-table-wrap {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-xs);
}

.doc-table-wrap :deep(.el-table) {
  --el-table-border-color: transparent;
}

/* 表头：扁平白底、发丝线、小字 muted */
.doc-table-wrap :deep(.el-table th.el-table__cell) {
  background: var(--color-bg-card);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-weight: var(--weight-medium);
  border-bottom: 1px solid var(--color-border);
}

/* 单元格：发丝线行分隔 */
.doc-table-wrap :deep(.el-table td.el-table__cell) {
  border-bottom: 1px solid var(--color-border-light);
}

/* 末行无线 */
.doc-table-wrap :deep(.el-table__body tr:last-child td.el-table__cell) {
  border-bottom: none;
}

/* hover 行：浅底，无阴影 */
.doc-table-wrap :deep(.el-table tr:hover > td.el-table__cell) {
  background: var(--color-bg-hover) !important;
}

.document-view :deep(.el-upload-list) {
  max-height: 300px;
  overflow-y: auto;
}
</style>
