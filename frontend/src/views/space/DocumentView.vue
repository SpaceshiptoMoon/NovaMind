<template>
  <div class="document-view">
    <div class="kb-layout">
      <KbSidebar :nav-items="kbNavItems" />

      <div class="kb-content">
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
          <div class="right-actions" />
        </div>

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
            <el-table-column prop="status" label="状态" width="90" align="center">
              <template #default="{ row }">
                <el-tag :type="getStatusConfig(row.status).type" effect="plain" size="small">
                  {{ getStatusConfig(row.status).text }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="上传时间" width="160">
              <template #default="{ row }">
                <span class="text-muted">{{ formatDate(row.created_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="" width="170" fixed="right" align="right">
              <template #default="{ row }">
                <div class="action-buttons">
                  <el-tooltip v-if="canProcess(row)" content="处理" placement="top">
                    <el-button :icon="VideoPlay" circle size="small" type="primary" @click="handleProcessSingle(row)" />
                  </el-tooltip>
                  <el-tooltip v-if="canCancel(row)" content="取消" placement="top">
                    <el-button :icon="Close" circle size="small" type="warning" @click="handleCancelSingle(row)" />
                  </el-tooltip>
                  <el-tooltip v-if="canRetry(row)" content="重试" placement="top">
                    <el-button :icon="RefreshRight" circle size="small" type="success" @click="handleRetrySingle(row)" />
                  </el-tooltip>
                  <el-tooltip content="详情" placement="top">
                    <el-button :icon="View" circle size="small" @click="goToDetail(row.id)" />
                  </el-tooltip>
                  <el-tooltip content="删除" placement="top">
                    <el-button :icon="Delete" circle size="small" @click="handleDelete(row)" />
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
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, DataAnalysis, Delete, Document, List, RefreshRight, Search, Upload, UploadFilled, VideoPlay, View } from '@element-plus/icons-vue'
import type { UploadFile } from 'element-plus'

import { documentApi } from '@/api/document'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import { spaceApi } from '@/api/space'
import type { BatchUploadResponse, Document as DocType } from '@/api/types'
import KbSidebar from '@/components/common/KbSidebar.vue'
import type { KbNavItem } from '@/components/common/KbSidebar.vue'
import Pagination from '@/components/common/Pagination.vue'
import { getFileMaxSize, getFileTypeStyle, getUploadAccept, hasModality, normalizeSpaceTypes, taskStatusMap } from '@/utils/document'
import { formatDate, formatFileSize } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))
const kbId = computed(() => Number(route.params.kbId))

const kbNavItems = computed<KbNavItem[]>(() => {
  const sid = spaceId.value
  const kid = kbId.value
  return [
    { label: '文档管理', to: `/home/spaces/${sid}/knowledge-bases/${kid}/documents`, route: 'Documents', active: route.name === 'Documents' || route.name === 'DocumentDetail', icon: Document },
    { label: '任务列表', to: `/home/spaces/${sid}/knowledge-bases/${kid}/tasks`, route: 'DocumentTasks', active: route.name === 'DocumentTasks', icon: List },
    { label: '搜索', to: `/home/spaces/${sid}/search?kbId=${kid}`, route: 'Search', active: route.name === 'Search', icon: Search },
    { label: '测评', to: `/home/spaces/${sid}/knowledge-bases/${kid}/evaluation`, route: 'KbEvaluation', active: route.name === 'KbEvaluation', icon: DataAnalysis },
  ]
})

const loading = ref(false)
const uploadLoading = ref(false)
const processLoading = ref(false)
const uploadDialogVisible = ref(false)
const processDialogVisible = ref(false)

const spaceTypes = ref<string[]>(['text'])
const documents = ref<DocType[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const fileList = ref<UploadFile[]>([])
const selectedFiles = ref<File[]>([])
const selectedIds = ref<number[]>([])
const processTargetIds = ref<number[]>([])

const uploadAccept = computed(() => getUploadAccept(spaceTypes.value))

const uploadTipText = computed(() => {
  const parts: string[] = []
  if (hasModality(spaceTypes.value, 'text')) parts.push('PDF/Word/TXT/MD/CSV/HTML/JSON')
  if (hasModality(spaceTypes.value, 'image')) parts.push('JPG/PNG/GIF/WebP')
  if (hasModality(spaceTypes.value, 'video')) parts.push('MP4/MOV/AVI/MKV/WebM')
  if (hasModality(spaceTypes.value, 'audio')) parts.push('MP3/WAV/FLAC/AAC/OGG/M4A')
  const maxMB = Math.max(...spaceTypes.value.map(t => ({ text: 100, image: 100, video: 500, audio: 200 })[t] || 100))
  return `支持 ${parts.join(' + ')}，视频最大 500MB，音频最大 200MB，其余最大 ${maxMB}MB，最多 20 个`
})

function handleSelectionChange(rows: DocType[]) {
  selectedIds.value = rows.map((r) => r.id)
}

function handleFileChange(file: UploadFile) {
  if (!file.raw) return
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  const maxSizeMB = getFileMaxSize(ext)
  if (file.raw.size > maxSizeMB * 1024 * 1024) {
    ElMessage.error(`文件 "${file.name}" 大小不能超过 ${maxSizeMB}MB`)
    fileList.value = fileList.value.filter((f) => f.uid !== file.uid)
    return
  }
  selectedFiles.value.push(file.raw)
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
    ElMessage.success(`已创建任务 #${res.task_id ?? '-'}，包含 ${res.total} 个文档`)
    processDialogVisible.value = false
    selectedIds.value = []
    await fetchDocuments()
  } finally {
    processLoading.value = false
  }
}

async function fetchDocuments() {
  loading.value = true
  try {
    const data = await documentApi.getDocuments(spaceId.value, kbId.value, {
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value,
    })
    documents.value = data.items || []
    total.value = data.total || 0
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

function canProcess(doc: DocType): boolean {
  const s = doc.status ?? 0
  return s === 0 || s === 3
}

function canCancel(doc: DocType): boolean {
  const s = doc.status ?? 0
  return s === 0 || s === 1
}

function canRetry(doc: DocType): boolean {
  const s = doc.status ?? 0
  return s === 3
}

async function handleProcessSingle(doc: DocType) {
  const res = await documentApi.processDocument(spaceId.value, kbId.value, doc.id)
  ElMessage.success(`文档 "${doc.filename}" 已加入任务 #${res.task_id ?? '-'}`)
  await fetchDocuments()
}

async function handleCancelSingle(doc: DocType) {
  await documentApi.cancelDocument(spaceId.value, kbId.value, doc.id)
  ElMessage.success(`已取消文档 "${doc.filename}" 的处理`)
  await fetchDocuments()
}

async function handleRetrySingle(doc: DocType) {
  const res = await documentApi.retryDocument(spaceId.value, kbId.value, doc.id)
  ElMessage.success(`文档 "${doc.filename}" 已重新加入任务 #${res.task_id ?? '-'}`)
  await fetchDocuments()
}

onMounted(async () => {
  await fetchDocuments()
  try {
    const kbConfig = await knowledgeBaseApi.getConfig(spaceId.value, kbId.value)
    if (kbConfig.config?.space_type && Array.isArray(kbConfig.config.space_type) && kbConfig.config.space_type.length > 0) {
      spaceTypes.value = kbConfig.config.space_type
    } else {
      const space = await spaceApi.getSpace(spaceId.value)
      spaceTypes.value = normalizeSpaceTypes(space.config)
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

.action-buttons {
  display: flex;
  gap: var(--space-1);
  justify-content: flex-end;
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
</style>
