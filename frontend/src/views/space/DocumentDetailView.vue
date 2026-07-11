<template>
  <div class="document-detail-view">
    <!-- 文档信息 -->
    <div v-loading="loading" class="info-section">
      <div class="info-header">
        <div class="info-title-row">
          <div class="file-type-badge" :style="{ background: getFileTypeStyle(document?.file_type || '').bg, color: getFileTypeStyle(document?.file_type || '').color }">
            {{ (document?.file_type || 'FILE').toUpperCase().slice(0, 3) }}
          </div>
          <div class="info-title-text">
            <h3 class="doc-filename">{{ document?.filename || '加载中...' }}</h3>
          </div>
        </div>
        <div class="header-actions">
          <el-button v-if="canProcess" type="primary" size="small" :loading="actionLoading" @click="handleProcessDoc">
            处理
          </el-button>
          <el-button v-if="canCancel" type="warning" size="small" :loading="actionLoading" @click="handleCancelDoc">
            取消
          </el-button>
          <el-button v-if="canRetry" type="success" size="small" :loading="actionLoading" @click="handleRetryDoc">
            重试
          </el-button>
          <el-button type="primary" size="small" plain @click="handleDownload">
            下载
          </el-button>
          <el-button type="danger" size="small" plain @click="handleDelete">
            删除
          </el-button>
        </div>
      </div>

      <!-- Meta grid -->
      <div v-if="document" class="meta-grid">
        <div class="meta-item">
          <span class="meta-label">处理状态</span>
          <span class="meta-value">
            <el-tag :type="currentStatusConfig.type" effect="plain" size="small">
              {{ currentStatusConfig.text }}
            </el-tag>
            <span v-if="latestTask?.error_message" class="error-hint" :title="latestTask.error_message">
              {{ latestTask.error_message.slice(0, 60) }}{{ latestTask.error_message.length > 60 ? '...' : '' }}
            </span>
          </span>
        </div>
        <div class="meta-item">
          <span class="meta-label">文件类型</span>
          <span class="meta-value">{{ document.file_type?.toUpperCase() || '-' }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">文件大小</span>
          <span class="meta-value">{{ formatFileSize(document.file_size || 0) }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">分块数</span>
          <span class="meta-value">{{ document.chunk_count || 0 }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Token 数</span>
          <span class="meta-value">{{ document.token_count || 0 }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">上传时间</span>
          <span class="meta-value">{{ formatDate(document.created_at) }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">更新时间</span>
          <span class="meta-value">{{ formatDate(document.updated_at) }}</span>
        </div>
        <div v-if="(document.doc_metadata as Record<string, unknown>)?.chunk_type" class="meta-item">
          <span class="meta-label">内容类型</span>
          <span class="meta-value">{{ chunkTypeLabels[(document.doc_metadata as Record<string, unknown>).chunk_type as string] || (document.doc_metadata as Record<string, unknown>).chunk_type }}</span>
        </div>
        <div v-if="(document.doc_metadata as Record<string, unknown>)?.frame_count != null" class="meta-item">
          <span class="meta-label">视频帧数</span>
          <span class="meta-value">{{ (document.doc_metadata as Record<string, unknown>).frame_count }}</span>
        </div>
        <div v-if="(document.doc_metadata as Record<string, unknown>)?.segment_count != null" class="meta-item">
          <span class="meta-label">音频分段数</span>
          <span class="meta-value">{{ (document.doc_metadata as Record<string, unknown>).segment_count }}</span>
        </div>
      </div>
    </div>

    <!-- 分块列表 -->
    <div class="chunks-section">
      <div class="section-header">
        <h4>文档分块</h4>
        <span class="chunk-count">{{ document?.chunk_count || 0 }} 个分块</span>
      </div>

      <div v-if="chunks.length > 0" class="chunks-list">
        <div
          v-for="chunk in chunks"
          :key="chunk.chunk_id"
          class="chunk-card"
        >
          <div class="chunk-header">
            <span class="chunk-index-badge">{{ chunk.chunk_index + 1 }}</span>
            <div class="chunk-meta">
              <span v-if="chunk.chunk_type && chunk.chunk_type !== 'text'" class="meta-tag chunk-type-tag">{{ chunkTypeLabels[chunk.chunk_type] || chunk.chunk_type }}</span>
              <span v-if="(chunk.metadata as Record<string, unknown>)?.page" class="meta-tag">第 {{ (chunk.metadata as Record<string, unknown>).page }} 页</span>
              <span v-if="(chunk.metadata as Record<string, unknown>)?.section_title" class="meta-tag">{{ (chunk.metadata as Record<string, unknown>).section_title }}</span>
              <span v-if="(chunk.metadata as Record<string, unknown>)?.start_time != null" class="meta-tag time-tag">
                {{ formatDuration((chunk.metadata as Record<string, unknown>).start_time as number) }}
                -
                {{ formatDuration((chunk.metadata as Record<string, unknown>).end_time as number) }}
              </span>
              <span v-if="chunk.has_embedding" class="meta-tag embedded">已向量化</span>
            </div>
          </div>
          <div class="chunk-content">
            <img
              v-if="chunk.chunk_type === 'image' && (chunk.media_url || chunk.image_url)"
              :src="chunk.media_url || chunk.image_url"
              :alt="chunk.content"
              loading="lazy"
              class="chunk-image"
              @click="previewUrl = (chunk.media_url || chunk.image_url)!; previewVisible = true"
            />
            <template v-else>{{ chunk.content }}</template>
          </div>
          <div v-if="chunk.questions?.length > 0" class="chunk-questions">
            <el-tag
              v-for="q in chunk.questions"
              :key="q"
              size="small"
              effect="plain"
              round
            >
              {{ q }}
            </el-tag>
          </div>
        </div>
      </div>
      <EmptyState v-else description="暂无分块数据">
        <el-button @click="router.push(backTarget)">
          {{ backLabel }}
        </el-button>
      </EmptyState>

      <div v-if="totalChunks > chunkPageSize" class="chunks-pagination">
        <el-pagination
          v-model:current-page="chunkCurrentPage"
          :page-size="chunkPageSize"
          :total="totalChunks"
          layout="total, prev, pager, next"
          @current-change="fetchChunks"
        />
      </div>
    </div>

    <!-- 图片预览弹窗 -->
    <el-dialog
      v-model="previewVisible"
      :show-close="true"
      width="auto"
      class="image-preview-dialog"
      destroy-on-close
    >
      <img :src="previewUrl" style="max-width: 90vw; max-height: 80vh; object-fit: contain; display: block; margin: auto" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { documentApi } from '@/api/knowledge'
import EmptyState from '@/components/common/EmptyState.vue'
import type { DocumentDetail, Chunk, DocumentTaskItem } from '@/api/types'
import { chunkTypeLabels, getFileTypeStyle, taskStatusMap } from '@/components/knowledge'
import { formatFileSize, formatDate, formatDuration } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))
const docId = computed(() => Number(route.params.docId))
const kbId = computed(() => Number(route.query.kbId) || 0)

// 空状态返回目标：有 kbId 时回文档管理，否则回知识库列表。
const backTarget = computed(() =>
  kbId.value
    ? `/home/spaces/${spaceId.value}/knowledge-bases/${kbId.value}/documents`
    : `/home/spaces/${spaceId.value}/knowledge-bases`,
)
const backLabel = computed(() => (kbId.value ? '返回文档管理' : '返回知识库'))

const loading = ref(false)
const actionLoading = ref(false)
const document = ref<DocumentDetail | null>(null)
const latestTask = ref<DocumentTaskItem | null>(null)
const chunks = ref<Chunk[]>([])
const totalChunks = ref(0)
const chunkCurrentPage = ref(1)
const chunkPageSize = 10
const previewVisible = ref(false)
const previewUrl = ref('')

// 状态辅助：基于最新 DocumentTask 派生页面状态。

const docStatus = computed(() => document.value?.status ?? 0)
const currentStatusConfig = computed(() => taskStatusMap[docStatus.value] ?? { text: '未知', type: 'info' as const })
const canProcess = computed(() => docStatus.value === 0 || docStatus.value === 3)  // PENDING or FAILED
const canCancel = computed(() => docStatus.value === 0 || docStatus.value === 1)   // PENDING or PROCESSING
const canRetry = computed(() => docStatus.value === 3)                              // FAILED

async function fetchDocument() {
  loading.value = true
  try {
    const data = await documentApi.getDocument(spaceId.value, kbId.value, docId.value)
    document.value = data
    totalChunks.value = data.chunk_count || 0
    chunkCurrentPage.value = 1
    await fetchChunks()
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '获取文档详情失败')
  } finally {
    loading.value = false
  }
}

async function fetchChunks() {
  if (kbId.value === 0) return
  try {
    const data = await documentApi.getDocumentChunks(
      spaceId.value,
      kbId.value,
      docId.value,
      {
        skip: (chunkCurrentPage.value - 1) * chunkPageSize,
        limit: chunkPageSize,
      }
    )
    chunks.value = data || []
  } catch {
    // 分块获取失败不影响页面展示
  }
}

async function handleDownload() {
  if (!document.value) return
  try {
    await documentApi.downloadDocument(
      spaceId.value,
      kbId.value,
      docId.value,
      document.value.filename
    )
    ElMessage.success('下载成功')
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '下载失败')
  }
}

async function handleDelete() {
  if (!document.value) return
  try {
    await ElMessageBox.confirm(
      `确定要删除文档 "${document.value.filename}" 吗？此操作不可恢复。`,
      '警告',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'error',
      }
    )
    await documentApi.deleteDocument(
      spaceId.value,
      kbId.value,
      docId.value
    )
    ElMessage.success('文档已删除')
    router.back()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      const err = error as { response?: { data?: { error?: { message?: string } } } }
      ElMessage.error(err.response?.data?.error?.message || '删除失败')
    }
  }
}

// 处理操作：基于 Task 接口执行处理、取消和重试。

async function fetchLatestTask() {
  if (kbId.value === 0) return
  try {
    const res = await documentApi.getDocumentTasks(spaceId.value, kbId.value, docId.value)
    if (res.items && res.items.length > 0 && res.items[0]) {
      latestTask.value = res.items[0]
    }
  } catch {
    // 浠诲姟淇℃伅鑾峰彇澶辫触涓嶅奖鍝嶄富椤甸潰
  }
}

async function handleProcessDoc() {
  actionLoading.value = true
  try {
    const res = await documentApi.processDocument(spaceId.value, kbId.value, docId.value)
    ElMessage.success(`已提交到任务项 #${res.task_item_id ?? '-'}`)
    await fetchDocument()
    await fetchLatestTask()
  } catch {
    // Error already shown by interceptor
  } finally {
    actionLoading.value = false
  }
}

async function handleCancelDoc() {
  actionLoading.value = true
  try {
    await documentApi.cancelDocument(spaceId.value, kbId.value, docId.value)
    ElMessage.success('已取消处理')
    await fetchDocument()
    await fetchLatestTask()
  } catch {
    // Error already shown by interceptor
  } finally {
    actionLoading.value = false
  }
}

async function handleRetryDoc() {
  actionLoading.value = true
  try {
    const res = await documentApi.retryDocument(spaceId.value, kbId.value, docId.value)
    ElMessage.success(`已重新提交到任务项 #${res.task_item_id ?? '-'}`)
    await fetchDocument()
    await fetchLatestTask()
  } catch {
    // Error already shown by interceptor
  } finally {
    actionLoading.value = false
  }
}

onMounted(() => {
  fetchDocument()
  fetchLatestTask()
})
</script>

<style scoped>
.document-detail-view {
  padding-top: var(--space-2);
}

/* ===== Info Section ===== */

.info-section {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  padding: var(--space-5);
  margin-bottom: var(--space-5);
}

.info-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-4);
}

.info-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.file-type-badge {
  width: 44px;
  height: 34px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: var(--weight-bold);
  flex-shrink: 0;
}

.info-title-text {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.doc-filename {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  font-family: var(--font-display);
}

.header-actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: var(--space-3);
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  background: var(--color-bg-card-elevated);
  border-radius: var(--radius-md);
}

.meta-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.meta-value {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-wrap: wrap;
}

.error-hint {
  font-size: var(--text-xs);
  color: var(--color-danger);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== Chunks Section ===== */

.chunks-section {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  padding: var(--space-5);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.section-header h4 {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  font-family: var(--font-display);
}

.chunk-count {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.chunks-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.chunk-card {
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  transition: all var(--transition-fast);
}

.chunk-card:hover {
  border-color: var(--color-border);
}

.chunk-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.chunk-index-badge {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-full);
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: var(--weight-bold);
  flex-shrink: 0;
}

.chunk-meta {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.meta-tag {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  background: var(--color-bg-hover);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
}

.meta-tag.embedded {
  color: var(--color-success);
  background: var(--color-success-subtle);
}

.meta-tag.chunk-type-tag {
  color: var(--color-primary);
  background: var(--color-primary-subtle);
  font-weight: var(--weight-medium);
}

.meta-tag.time-tag {
  color: var(--color-text-secondary);
  background: var(--color-bg-hover);
  font-family: var(--font-mono);
}

.chunk-content {
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text);
  font-family: var(--font-mono);
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--color-bg-hover);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid var(--color-border-light);
}

.chunk-image {
  max-width: 100%;
  max-height: 400px;
  border-radius: var(--radius-md);
  object-fit: contain;
  cursor: pointer;
  transition: opacity var(--transition-fast);
}

.chunk-image:hover {
  opacity: 0.9;
}

.image-preview-dialog :deep(.el-dialog__body) {
  padding: 0;
}

.chunk-questions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border-light);
}

.chunks-pagination {
  display: flex;
  justify-content: center;
  margin-top: var(--space-4);
}
</style>



