<template>
  <div class="document-view">
    <!-- 页面导航 -->
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
      <BreadcrumbNav />
    </div>

    <!-- 操作栏 -->
    <div class="action-bar">
      <div class="left-actions">
        <el-button type="primary" @click="showUploadDialog">
          <el-icon><Upload /></el-icon>
          上传文档
        </el-button>
        <el-button
          :disabled="selectedIds.length === 0"
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
    <el-table
      :data="documents"
      v-loading="loading"
      stripe
      @selection-change="handleSelectionChange"
    >
      <el-table-column type="selection" width="45" />
      <el-table-column prop="filename" label="文件名" min-width="200">
        <template #default="{ row }">
          <div class="filename">
            <el-icon><Document /></el-icon>
            <span>{{ row.filename }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="file_type" label="类型" width="80" align="center">
        <template #default="{ row }">
          <el-tag size="small">{{ row.file_type.toUpperCase() }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="file_size" label="大小" width="100" align="center">
        <template #default="{ row }">
          {{ formatFileSize(row.file_size) }}
        </template>
      </el-table-column>
      <el-table-column prop="chunk_count" label="分块数" width="80" align="center" />
      <el-table-column prop="status" label="状态" width="100" align="center">
        <template #default="{ row }">
          <StatusTag :status="String(row.status)" :status-map="docStatusMap" size="small" />
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="上传时间" width="160">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.status === 'uploaded' || row.status === 'failed' || row.status === 'completed' || row.status === 0 || row.status === 3 || row.status === 2"
            type="primary"
            link
            size="small"
            @click="handleSingleProcess(row)"
          >
            {{ (row.status === 'completed' || row.status === 2) ? '重新解析' : '处理' }}
          </el-button>
          <el-button type="primary" link size="small" @click="goToDetail(row.id)">
            详情
          </el-button>
          <el-button type="primary" link size="small" @click="handleDownload(row)">
            下载
          </el-button>
          <el-button type="danger" link size="small" @click="handleDelete(row)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

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

    <!-- 上传文档弹窗（仅上传，不处理） -->
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
            accept=".pdf,.docx,.doc,.txt,.md,.csv,.xlsx,.xls,.pptx,.ppt,.html,.json"
            drag
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">
              拖拽文件到此处，或 <em>点击上传</em>
            </div>
            <template #tip>
              <div class="el-upload__tip">
                支持 PDF、Word、TXT、Markdown、Excel、PPT、HTML、JSON 格式，单个最大 100MB，最多 20 个文件
              </div>
            </template>
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
      <el-form label-width="120px">
        <el-form-item label="生成假设问题">
          <el-switch v-model="processForm.enable_question_generation" />
          <span class="form-tip">为每个分块生成相关问题</span>
        </el-form-item>
        <el-form-item v-if="processForm.enable_question_generation" label="每块问题数量">
          <el-input-number
            v-model="processForm.question_count"
            :min="1"
            :max="10"
          />
        </el-form-item>
      </el-form>
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
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Document, UploadFilled } from '@element-plus/icons-vue'
import { documentApi } from '@/api/document'
import StatusTag from '@/components/common/StatusTag.vue'
import Pagination from '@/components/common/Pagination.vue'
import BreadcrumbNav from '@/components/common/BreadcrumbNav.vue'
import type { Document as DocType, BatchUploadResponse } from '@/api/types'
import type { UploadFile } from 'element-plus'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))
const kbId = computed(() => Number(route.params.kbId))

const loading = ref(false)
const uploadLoading = ref(false)
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
const processForm = reactive({
  enable_question_generation: false,
  question_count: 5,
})

const docStatusMap: Record<string, { text: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
  uploaded: { text: '待处理', type: 'info' },
  processing: { text: '处理中', type: 'warning' },
  completed: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  '0': { text: '待处理', type: 'info' },
  '1': { text: '处理中', type: 'warning' },
  '2': { text: '已完成', type: 'success' },
  '3': { text: '失败', type: 'danger' },
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(date: string): string {
  try {
    return new Date(date).toLocaleDateString('zh-CN') + ' ' +
      new Date(date).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return '-'
  }
}

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
    if (file.raw.size > 100 * 1024 * 1024) {
      ElMessage.error(`文件 "${file.name}" 大小不能超过 100MB`)
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
      // 批量上传响应
      const batchRes = res as BatchUploadResponse
      if (batchRes.success.length > 0) {
        ElMessage.success(`${batchRes.success.length} 个文件上传成功`)
      }
      if (batchRes.failed.length > 0) {
        batchRes.failed.forEach((f) => ElMessage.error(`${f.filename}: ${f.error}`))
      }
    } else {
      // 单文件上传响应
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

function showProcessDialog(ids: number[]) {
  processTargetIds.value = ids
  processForm.enable_question_generation = false
  processForm.question_count = 5
  processDialogVisible.value = true
}

async function handleProcess() {
  processLoading.value = true
  try {
    const body: { document_ids?: number[]; enable_question_generation?: boolean; question_count?: number } = {
      document_ids: processTargetIds.value,
    }
    if (processForm.enable_question_generation) {
      body.enable_question_generation = true
      body.question_count = processForm.question_count
    }
    await documentApi.batchProcessDocuments(spaceId.value, kbId.value, body)
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

async function handleDownload(doc: DocType) {
  try {
    await documentApi.downloadDocument(spaceId.value, kbId.value, doc.id, doc.filename)
    ElMessage.success('下载成功')
  } catch {
    // Error already shown by response interceptor
  }
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

onMounted(() => {
  fetchDocuments()
})
</script>

<style scoped>
.document-view {
  padding: var(--space-5);
}

.page-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.nav-tabs {
  display: flex;
  gap: var(--space-2);
}

.nav-tab {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  text-decoration: none;
  transition: all var(--transition-fast);
}

.nav-tab:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.nav-tab.active {
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  font-weight: var(--weight-medium);
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
  gap: 10px;
}

.filename {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.filename .el-icon {
  color: var(--color-primary);
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
  line-height: 1.5;
}

.document-view :deep(.el-upload-list) {
  max-height: 300px;
  overflow-y: auto;
}
</style>
