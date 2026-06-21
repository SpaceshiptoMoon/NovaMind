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
            <StatusTag v-if="document" :status="String(document.status)" :status-map="docStatusMap" size="small" />
          </div>
        </div>
        <div class="header-actions">
          <el-button
            v-if="isProcessing"
            size="small"
            :loading="cancelLoading"
            @click="handleCancel"
          >
            取消处理
          </el-button>
          <el-button
            v-if="isFailed"
            size="small"
            :loading="retryLoading"
            @click="handleRetry"
          >
            重试
          </el-button>
          <el-button
            v-if="canReprocess"
            size="small"
            :loading="reprocessLoading"
            @click="handleReprocess"
          >
            重新解析
          </el-button>
          <el-button type="primary" size="small" @click="handleDownload">
            下载
          </el-button>
          <el-button type="danger" size="small" @click="handleDelete">
            删除
          </el-button>
        </div>
      </div>

      <!-- Meta grid -->
      <div v-if="document" class="meta-grid">
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
              <span v-if="(chunk.metadata as Record<string, unknown>)?.page" class="meta-tag">第 {{ (chunk.metadata as Record<string, unknown>).page }} 页</span>
              <span v-if="(chunk.metadata as Record<string, unknown>)?.section_title" class="meta-tag">{{ (chunk.metadata as Record<string, unknown>).section_title }}</span>
              <span v-if="chunk.has_embedding" class="meta-tag embedded">已向量化</span>
            </div>
          </div>
          <div class="chunk-content">
            <img
              v-if="chunk.chunk_type === 'image' && chunk.image_url"
              :src="chunk.image_url"
              :alt="chunk.content"
              loading="lazy"
              class="chunk-image"
              @click="previewUrl = chunk.image_url!; previewVisible = true"
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
import { documentApi } from '@/api/document'
import StatusTag from '@/components/common/StatusTag.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import type { DocumentDetail, Chunk } from '@/api/types'
import { docStatusMap, getFileTypeStyle } from '@/utils/document'
import { formatFileSize, formatDate } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))
const docId = computed(() => Number(route.params.docId))
const kbId = computed(() => Number(route.query.kbId) || 0)

// 空状态返回目标：有 kbId 回文档管理，否则回知识库列表（兜底直接访问详情页无 query 的情况）
const backTarget = computed(() =>
  kbId.value
    ? `/home/spaces/${spaceId.value}/knowledge-bases/${kbId.value}/documents`
    : `/home/spaces/${spaceId.value}/knowledge-bases`,
)
const backLabel = computed(() => (kbId.value ? '返回文档管理' : '返回知识库'))

const loading = ref(false)
const reprocessLoading = ref(false)
const cancelLoading = ref(false)
const retryLoading = ref(false)
const document = ref<DocumentDetail | null>(null)
const chunks = ref<Chunk[]>([])
const totalChunks = ref(0)
const chunkCurrentPage = ref(1)
const chunkPageSize = 10
const previewVisible = ref(false)
const previewUrl = ref('')

const canReprocess = computed(() => {
  const s = document.value?.status
  return s === 'completed' || s === 2
})

const isProcessing = computed(() => {
  const s = document.value?.status
  return s === 'processing' || s === 1
})

const isFailed = computed(() => {
  const s = document.value?.status
  return s === 'failed' || s === 3
})

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

async function handleReprocess() {
  try {
    await ElMessageBox.confirm(
      '确定要重新解析该文档吗？将清除旧的分块数据并重新切分。',
      '重新解析',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' },
    )
    reprocessLoading.value = true
    await documentApi.reprocessDocument(spaceId.value, kbId.value, docId.value)
    ElMessage.success('已提交重新解析任务')
    fetchDocument()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      const err = error as { response?: { data?: { error?: { message?: string } } } }
      ElMessage.error(err.response?.data?.error?.message || '重新解析失败')
    }
  } finally {
    reprocessLoading.value = false
  }
}

async function handleCancel() {
  try {
    await ElMessageBox.confirm(
      '确定要取消该文档的处理吗？',
      '取消处理',
      { confirmButtonText: '确定取消', cancelButtonText: '返回', type: 'warning' },
    )
    cancelLoading.value = true
    await documentApi.cancelDocument(spaceId.value, kbId.value, docId.value)
    ElMessage.success('取消请求已发送')
    fetchDocument()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      const err = error as { response?: { data?: { error?: { message?: string } } } }
      ElMessage.error(err.response?.data?.error?.message || '取消失败')
    }
  } finally {
    cancelLoading.value = false
  }
}

async function handleRetry() {
  try {
    await ElMessageBox.confirm(
      '确定要重试该文档的处理吗？将清除旧的分块数据并重新解析。',
      '重试处理',
      { confirmButtonText: '确定重试', cancelButtonText: '取消', type: 'info' },
    )
    retryLoading.value = true
    await documentApi.retryDocument(spaceId.value, kbId.value, docId.value)
    ElMessage.success('已提交重试任务')
    fetchDocument()
  } catch (error: unknown) {
    if ((error as string) !== 'cancel') {
      const err = error as { response?: { data?: { error?: { message?: string } } } }
      ElMessage.error(err.response?.data?.error?.message || '重试失败')
    }
  } finally {
    retryLoading.value = false
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

onMounted(() => {
  fetchDocument()
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
