<template>
  <div class="document-detail-view">
    <div class="back-row">
      <el-button size="small" @click="goBackToDocuments">
        <el-icon><ArrowLeft /></el-icon>
        返回文档列表
      </el-button>
      <BreadcrumbNav :doc-name="document?.filename" />
    </div>

    <!-- 文档信息 -->
    <el-card v-loading="loading" class="info-card">
      <template #header>
        <div class="card-header">
          <span>文档信息</span>
          <div class="header-actions">
            <el-button
              v-if="canReprocess"
              type="warning"
              size="small"
              :loading="reprocessLoading"
              @click="handleReprocess"
            >
              <el-icon><Refresh /></el-icon>
              重新解析
            </el-button>
            <el-button type="primary" size="small" @click="handleDownload">
              <el-icon><Download /></el-icon>
              下载
            </el-button>
            <el-button type="danger" size="small" @click="handleDelete">
              <el-icon><Delete /></el-icon>
              删除
            </el-button>
          </div>
        </div>
      </template>

      <el-descriptions :column="3" border>
        <el-descriptions-item label="文件名">
          {{ document?.filename || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="文件类型">
          <el-tag size="small">{{ document?.file_type?.toUpperCase() || '-' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="文件大小">
          {{ formatFileSize(document?.file_size || 0) }}
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <StatusTag :status="String(document?.status ?? '')" :status-map="docStatusMap" size="small" />
        </el-descriptions-item>
        <el-descriptions-item label="分块数">
          {{ document?.chunk_count || 0 }}
        </el-descriptions-item>
        <el-descriptions-item label="Token数">
          {{ document?.token_count || 0 }}
        </el-descriptions-item>
        <el-descriptions-item label="上传时间">
          {{ formatDate(document?.created_at) }}
        </el-descriptions-item>
        <el-descriptions-item label="更新时间">
          {{ formatDate(document?.updated_at) }}
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 分块列表 -->
    <el-card class="chunks-card">
      <template #header>
        <div class="card-header">
          <span>文档分块 ({{ document?.chunk_count || 0 }})</span>
        </div>
      </template>

      <div v-if="chunks.length > 0" class="chunks-list">
        <el-card
          v-for="chunk in chunks"
          :key="chunk.chunk_id"
          class="chunk-card"
          shadow="hover"
        >
          <div class="chunk-header">
            <span class="chunk-index">分块 {{ chunk.chunk_index + 1 }}</span>
            <span class="chunk-meta">
              <span v-if="(chunk.metadata as Record<string, unknown>)?.page">页码: {{ (chunk.metadata as Record<string, unknown>).page }}</span>
              <span v-if="(chunk.metadata as Record<string, unknown>)?.section_title">章节: {{ (chunk.metadata as Record<string, unknown>).section_title }}</span>
              <span v-if="chunk.has_embedding">已向量化</span>
            </span>
          </div>
          <div class="chunk-content">
            {{ chunk.content }}
          </div>
          <div v-if="chunk.questions?.length > 0" class="chunk-questions">
            <span class="questions-label">相关问题:</span>
            <el-tag
              v-for="q in chunk.questions"
              :key="q"
              size="small"
              type="info"
            >
              {{ q }}
            </el-tag>
          </div>
        </el-card>
      </div>
      <EmptyState v-else description="暂无分块数据" />

      <div v-if="totalChunks > chunkPageSize" class="chunks-pagination">
        <el-pagination
          v-model:current-page="chunkCurrentPage"
          :page-size="chunkPageSize"
          :total="totalChunks"
          layout="total, prev, pager, next"
          @current-change="fetchChunks"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Delete, Refresh, ArrowLeft } from '@element-plus/icons-vue'
import { documentApi } from '@/api/document'
import StatusTag from '@/components/common/StatusTag.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import BreadcrumbNav from '@/components/common/BreadcrumbNav.vue'
import type { DocumentDetail, Chunk } from '@/api/types'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))
const docId = computed(() => Number(route.params.docId))
const kbId = computed(() => Number(route.query.kbId) || 0)

const loading = ref(false)
const reprocessLoading = ref(false)
const document = ref<DocumentDetail | null>(null)
const chunks = ref<Chunk[]>([])
const totalChunks = ref(0)
const chunkCurrentPage = ref(1)
const chunkPageSize = 10

// 状态映射
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

function formatDate(date?: string | null): string {
  if (!date) return '-'
  try {
    return new Date(date).toLocaleDateString('zh-CN') + ' ' +
      new Date(date).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return '-'
  }
}

const canReprocess = computed(() => {
  const s = document.value?.status
  return s === 'failed' || s === 'completed' || s === 3 || s === 2
})

function goBackToDocuments() {
  router.push(`/home/spaces/${spaceId.value}/knowledge-bases/${kbId.value}/documents`)
}

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
  padding: var(--space-5);
}

.back-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.breadcrumb-nav {
  display: block;
}

.info-card {
  margin-bottom: var(--space-5);
  border-radius: var(--radius-xl);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: var(--space-2);
}

.chunks-card {
  margin-bottom: var(--space-5);
  border-radius: var(--radius-xl);
}

.chunks-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.chunk-card {
  cursor: default;
  border-radius: var(--radius-lg);
}

.chunk-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-2);
}

.chunk-index {
  font-weight: var(--weight-semibold);
  color: var(--color-primary);
  font-size: 13px;
}

.chunk-meta {
  display: flex;
  gap: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.chunk-content {
  font-size: var(--text-base);
  line-height: 1.6;
  color: var(--color-text);
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--color-bg-hover);
  padding: 14px;
  border-radius: var(--radius-md);
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid var(--color-border-light);
}

.chunk-questions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border-light);
}

.questions-label {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.chunks-pagination {
  display: flex;
  justify-content: center;
  margin-top: var(--space-4);
}
</style>
