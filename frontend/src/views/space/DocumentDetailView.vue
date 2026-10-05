<template>
  <div class="document-detail-view">
    <!-- 文档信息头 -->
    <div v-loading="loading" class="info-section">
      <div class="info-header">
        <div class="info-title-row">
          <div class="file-type-badge" :style="{ background: getFileTypeStyle(document?.file_type || '').bg, color: getFileTypeStyle(document?.file_type || '').color }">
            {{ (document?.file_type || 'FILE').toUpperCase() }}
          </div>
          <h3 class="doc-filename" :title="document?.filename">
            {{ document?.filename || (loadFailed ? '文档不存在或已删除' : '加载中...') }}
          </h3>
          <!-- 状态随标题行：比埋在元信息网格里更先被看到 -->
          <el-tag
            v-if="document"
            class="doc-status-tag"
            :type="currentStatusConfig.type"
            effect="plain"
            size="small"
          >
            {{ currentStatusConfig.text }}
          </el-tag>
        </div>
        <p
          v-if="latestTask?.error_message && docStatus !== 2"
          class="error-line"
          :title="latestTask.error_message"
          @click="errorExpanded = !errorExpanded"
        >
          {{ errorDisplayText }}
        </p>
      </div>

      <!-- Meta grid：规模/媒体/解析产出统一行内 label 随值，比上标签下值的格子更紧凑扫读 -->
      <div v-if="document" class="meta-grid">
        <div class="meta-item">
          <span class="meta-label">文件大小</span>
          <span class="meta-value">{{ formatFileSize(document.file_size || 0) }}</span>
        </div>
        <div v-if="(document.chunk_count ?? 0) > 0" class="meta-item">
          <span class="meta-label">分块数</span>
          <span class="meta-value">{{ document.chunk_count }}</span>
        </div>
        <div v-if="(document.token_count ?? 0) > 0" class="meta-item">
          <span class="meta-label">Token 数</span>
          <span class="meta-value">{{ document.token_count }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">上传时间</span>
          <span class="meta-value">{{ formatDate(document.created_at) }}</span>
        </div>
        <div v-if="document.duration_seconds != null" class="meta-item">
          <span class="meta-label">时长</span>
          <span class="meta-value">{{ formatDuration(document.duration_seconds) }}</span>
        </div>
        <div v-if="document.chunk_type" class="meta-item">
          <span class="meta-label">内容类型</span>
          <span class="meta-value">{{ chunkTypeLabels[document.chunk_type] || document.chunk_type }}</span>
        </div>
        <div v-if="document.frame_count != null" class="meta-item">
          <span class="meta-label">视频帧数</span>
          <span class="meta-value">{{ document.frame_count }}</span>
        </div>
        <div v-if="document.segment_count != null" class="meta-item">
          <span class="meta-label">音频分段数</span>
          <span class="meta-value">{{ document.segment_count }}</span>
        </div>
        <div v-if="document.page_count != null" class="meta-item">
          <span class="meta-label">页数</span>
          <span class="meta-value">{{ document.page_count }}</span>
        </div>
        <div v-if="document.char_count != null" class="meta-item">
          <span class="meta-label">字符数</span>
          <span class="meta-value">{{ document.char_count.toLocaleString() }}</span>
        </div>
        <div v-if="document.outline_count != null" class="meta-item">
          <span class="meta-label">书签数</span>
          <span class="meta-value">{{ document.outline_count }}</span>
        </div>
        <div v-if="document.section_count != null" class="meta-item">
          <span class="meta-label">段落数</span>
          <span class="meta-value">{{ document.section_count }}</span>
        </div>
        <div v-if="document.table_count != null" class="meta-item">
          <span class="meta-label">表格数</span>
          <span class="meta-value">{{ document.table_count }}</span>
        </div>
        <div v-if="document.image_count != null" class="meta-item">
          <span class="meta-label">图片数</span>
          <span class="meta-value">{{ document.image_count }}</span>
        </div>
        <div v-if="document.embedding_model" class="meta-item">
          <span class="meta-label">Embedding</span>
          <span class="meta-value meta-value-long" :title="document.embedding_model + (document.embedding_dim != null ? ` · ${document.embedding_dim} 维` : '')">
            {{ document.embedding_model }}<template v-if="document.embedding_dim != null"> · {{ document.embedding_dim }} 维</template>
          </span>
        </div>
        <div v-if="document.parse_duration_ms != null" class="meta-item">
          <span class="meta-label">解析耗时</span>
          <span class="meta-value">{{ formatDuration(document.parse_duration_ms / 1000) }}</span>
        </div>
      </div>

      <!-- 处理流程：节点级时间线（数据来自 task.step_progress） -->
      <div v-if="hasNodeLogs" class="pipeline-timeline-section">
        <div class="timeline-header" @click="timelineExpanded = !timelineExpanded">
          <h4>处理流程</h4>
          <el-icon class="timeline-toggle" :class="{ 'is-expanded': timelineExpanded }">
            <ArrowRight />
          </el-icon>
        </div>
        <el-collapse-transition>
          <div v-show="timelineExpanded">
            <TaskNodeLogTable :step-progress="latestTask?.step_progress ?? null" />
          </div>
        </el-collapse-transition>
      </div>
    </div>

    <!-- 双栏内容区 -->
    <div class="content-layout">
      <!-- 左栏：分块列表 -->
      <div class="content-main">
        <!-- 分块列表 -->
        <div class="chunks-section">
          <div class="section-header">
            <h4>文档分块</h4>
            <div class="section-header-right">
              <el-button
                v-if="!showOriginalPanel"
                text
                size="small"
                @click="showOriginalPanel = true"
              >
                <el-icon class="section-action-icon"><View /></el-icon>
                预览
              </el-button>
              <span class="chunk-count">{{ totalChunks }} 个分块</span>
            </div>
          </div>

          <!-- 无分块空态：未处理/解析失败时不再整块消失，给出明确的下一步引导 -->
          <EmptyState
            v-if="totalChunks === 0 && !loading"
            variant="data"
            headline="暂无分块"
            :description="emptyChunkDescription"
          >
            <el-button @click="router.back()">返回文档列表</el-button>
          </EmptyState>

          <div v-if="chunks.length > 0" class="chunks-list">
            <div
              v-for="chunk in chunks"
              :key="chunk.chunk_id"
              class="chunk-card"
              :class="{ 'chunk-expanded': expandedChunks[chunk.chunk_index] }"
            >
              <div class="chunk-header" @click="toggleChunk(chunk.chunk_index)">
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
                <el-icon class="chunk-toggle" :class="{ 'is-expanded': expandedChunks[chunk.chunk_index] }">
                  <ArrowRight />
                </el-icon>
              </div>
              <!-- 折叠态：截断预览 -->
              <div v-if="!expandedChunks[chunk.chunk_index]" class="chunk-preview" @click="toggleChunk(chunk.chunk_index)">
                <template v-if="chunk.chunk_type === 'image'">🖼 图片分块</template>
                <template v-else>{{ truncateContent(chunk.content) }}</template>
              </div>
              <!-- 展开态：完整内容（Markdown 渲染：figure 图片 + TSR 表格 HTML 可视化） -->
              <template v-else>
                <div class="chunk-content">
                  <template v-if="chunk.chunk_type === 'image'">
                    <img
                      v-if="chunk.media_url || chunk.image_url"
                      :src="chunk.media_url || chunk.image_url"
                      :alt="chunk.content"
                      loading="lazy"
                      class="chunk-image"
                      @click="previewUrl = (chunk.media_url || chunk.image_url)!; previewVisible = true"
                    />
                    <div class="chunk-image-desc">{{ chunk.content }}</div>
                  </template>
                  <!-- content 里的 figure 短文件名已由后端 chunks 端点换成即时预签名 URL -->
                  <MarkdownRenderer
                    v-else-if="document"
                    :content="chunk.content"
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
              </template>
            </div>
          </div>

          <div v-if="totalChunks > 0" class="chunks-pagination">
            <Pagination
              :page="chunkCurrentPage"
              :page-size="chunkPageSize"
              :total="totalChunks"
              :page-sizes="[10, 20, 50, 100]"
              layout="total, sizes, prev, pager, next"
              @update:page="(p: number) => { chunkCurrentPage = p; fetchChunks() }"
              @update:page-size="(s: number) => { chunkPageSize = s; chunkCurrentPage = 1; fetchChunks() }"
            />
          </div>
        </div>
      </div>

      <!-- 右栏：原文预览（sticky 跟随滚动；关闭后经左栏头部「预览」钮召回） -->
      <div v-if="showOriginalPanel" class="content-sidebar">
        <div class="sidebar-header">
          <h4>预览与导出</h4>
          <el-button text size="small" @click="showOriginalPanel = false">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
        <DocumentOriginalPreview
          :space-id="spaceId"
          :kb-id="kbId"
          :document="document"
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
/**
 * 文档详情页。
 *
 * 对应路由 /home/spaces/:id/documents/:docId，展示文档元信息、解析失败/处理中的节点级
 * 流程时间线、分块列表（折叠预览 + 展开渲染 Markdown/图片）与右侧原文预览面板。
 * kbId 优先取 query，缺失时先反查归属知识库再加载，失败落「文档不存在」空态。
 */

import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Close, ArrowRight, View } from '@element-plus/icons-vue'
import { documentApi } from '@/api/knowledge'
import Pagination from '@/components/common/Pagination.vue'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import DocumentOriginalPreview from '@/components/knowledge/DocumentOriginalPreview.vue'
import { TaskNodeLogTable } from '@/components/knowledge'
import type { DocumentDetail, Chunk, DocumentTaskItem } from '@/api/types'
import { chunkTypeLabels, getFileTypeStyle, taskStatusMap } from '@/components/knowledge'
import { formatFileSize, formatDate, formatDuration } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))
const docId = computed(() => Number(route.params.docId))
// kbId 优先取 URL query；缺失（裸链接/收藏夹进入）时先反查归属知识库再加载，
// 反查失败按 0 处理（各加载函数已有 0 短路，不再打出 /knowledge-bases/0/... 请求）
const resolvedKbId = ref(Number(route.query.kbId) || 0)
const kbId = computed(() => resolvedKbId.value)

const loading = ref(false)
const loadFailed = ref(false)
const document = ref<DocumentDetail | null>(null)
const latestTask = ref<DocumentTaskItem | null>(null)
const chunks = ref<Chunk[]>([])
const totalChunks = ref(0)
const chunkCurrentPage = ref(1)
const chunkPageSize = ref(10)
const previewVisible = ref(false)
const previewUrl = ref('')

// 分块展开/折叠
const expandedChunks = ref<Record<number, boolean>>({})

// 原文预览面板
const showOriginalPanel = ref(true)

// 节点级时间线 / 错误全文展开
const timelineExpanded = ref(false)
const errorExpanded = ref(false)

// 处理状态失败/处理中时默认展开时间线，便于直接看到卡在哪个节点
const hasNodeLogs = computed(() => {
  const progress = latestTask.value?.step_progress
  return !!progress && Object.keys(progress).length > 0
})

const errorDisplayText = computed(() => {
  const msg = latestTask.value?.error_message
  if (!msg) return ''
  if (errorExpanded.value || msg.length <= 60) return msg
  return msg.slice(0, 60) + '...'
})

// 状态辅助
const docStatus = computed(() => document.value?.status ?? 0)
const currentStatusConfig = computed(() => taskStatusMap[docStatus.value] ?? { text: '未知', type: 'info' as const })

/** 分块空态描述：按文档状态区分「还没处理」与「处理失败」两种成因 */
const emptyChunkDescription = computed(() => {
  if (docStatus.value === 3) return '解析失败，没有产出分块；可在文档列表重试处理'
  if (docStatus.value === 1 || docStatus.value === 0) return '文档尚未完成解析，处理完成后这里会展示分块'
  return '该文档没有产出任何分块'
})

function toggleChunk(index: number): void {
  expandedChunks.value[index] = !expandedChunks.value[index]
}

function truncateContent(content: string, maxLen = 80): string {
  if (!content) return ''
  const firstLine = content.split('\n')[0] || ''
  if (firstLine.length <= maxLen) return firstLine
  return firstLine.slice(0, maxLen) + '...'
}

/** 加载文档详情（含分块总数）并联动首页分块列表；kbId 为 0 时短路不发请求。 */
async function fetchDocument() {
  if (kbId.value === 0) return
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
        skip: (chunkCurrentPage.value - 1) * chunkPageSize.value,
        limit: chunkPageSize.value,
      }
    )
    chunks.value = data.items || []
    totalChunks.value = data.total ?? totalChunks.value
  } catch {
    // 分块获取失败不影响页面展示
  }
}

/** 拉取最近一次处理任务，供状态展示与时间线数据（step_progress）使用。 */
async function fetchLatestTask() {
  if (kbId.value === 0) return
  try {
    const res = await documentApi.getDocumentTasks(spaceId.value, kbId.value, docId.value)
    if (res.items && res.items.length > 0 && res.items[0]) {
      latestTask.value = res.items[0]
      maybeAutoExpandTimeline()
    }
  } catch {
    // 任务信息获取失败不影响主页面
  }
}

onMounted(async () => {
  if (resolvedKbId.value === 0) {
    try {
      const { kb_id } = await documentApi.getDocumentKbId(spaceId.value, docId.value)
      resolvedKbId.value = kb_id
    } catch {
      // 反查失败（文档不存在/跨空间）落到明确的空态，不留「加载中」挂死
      loadFailed.value = true
      return
    }
  }
  fetchDocument()
  fetchLatestTask()
})

// 任务到达后：失败/处理中的任务默认展开时间线（直接看到卡在哪个节点）
function maybeAutoExpandTimeline() {
  if (docStatus.value === 3 || docStatus.value === 1) {
    timelineExpanded.value = true
  }
}
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
  margin-bottom: var(--space-4);
}

.info-header {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}

.info-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.file-type-badge {
  min-width: 44px;
  height: 34px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: var(--weight-bold);
  letter-spacing: 0.04em;
  flex-shrink: 0;
  user-select: none;
}

.doc-filename {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  font-family: var(--font-display);
  /* 长文件名单行收敛，悬停 title 看全名 */
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 状态随标题：紧随文件名，不可被压缩 */
.doc-status-tag {
  flex-shrink: 0;
}

/* 失败原因独立一行：不再挤在元信息格子里截断 60px，可展开看全文 */
.error-line {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--color-danger);
  background: var(--color-danger-subtle);
  border-radius: var(--radius-md);
  cursor: pointer;
  word-break: break-word;
}

/* ===== Meta grid ===== */

.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: var(--space-2) var(--space-4);
}

.meta-item {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  min-width: 0;
  /* 行内 label 随值：label 固定宽对齐成列，值收敛省略 */
}

.meta-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  flex-shrink: 0;
  white-space: nowrap;
}

.meta-value {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== Pipeline Timeline Section ===== */

.pipeline-timeline-section {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border-light);
}

.timeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  margin-bottom: var(--space-2);
  user-select: none;
}

.timeline-header h4 {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.timeline-toggle {
  color: var(--color-text-muted);
  transition: transform var(--transition-fast);
}

.timeline-toggle.is-expanded {
  transform: rotate(90deg);
}

/* ===== Content Layout ===== */

.content-layout {
  display: flex;
  gap: var(--space-4);
  align-items: flex-start;
}

.content-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.content-sidebar {
  width: 360px;
  flex-shrink: 0;
  /* 侧栏 sticky 跟随：长分块列表滚动时预览/导出始终在视口内 */
  position: sticky;
  top: var(--space-4);
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
}

.sidebar-header h4 {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
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
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}

.section-header h4 {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  font-family: var(--font-display);
}

.section-header-right {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.section-action-icon {
  margin-right: var(--space-1);
}

.chunk-count {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  white-space: nowrap;
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

.chunk-card.chunk-expanded {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 1px var(--color-primary-muted);
}

.chunk-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  cursor: pointer;
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
  flex: 1;
  min-width: 0;
}

.chunk-toggle {
  margin-left: auto;
  color: var(--color-text-muted);
  transition: transform var(--transition-fast);
  flex-shrink: 0;
}

.chunk-toggle.is-expanded {
  transform: rotate(90deg);
}

.chunk-preview {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  line-height: 1.5;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
  padding-top: var(--space-2);
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
  /* 320px 视口可读高度下限；纯文本超长滚动，Markdown 图片类不受 max-height 限制自然撑开 */
  max-height: 420px;
  overflow-y: auto;
  border: 1px solid var(--color-border-light);
  margin-top: var(--space-3);
}

/* Markdown 渲染的展开态不做内部滚动（图片/表格在受限内滚区里体验差），交给页面滚动 */
.chunk-content :deep(.markdown-body) {
  font-family: var(--font-body);
  white-space: normal;
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

.chunk-image-desc {
  margin-top: var(--space-2);
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text-secondary);
  font-family: var(--font-mono);
  white-space: pre-wrap;
  word-break: break-word;
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

/* ===== Responsive ===== */

@media (max-width: 1100px) {
  .content-layout {
    flex-direction: column;
  }

  .content-sidebar {
    width: 100%;
    /* 纵向堆叠后不再 sticky（会遮住内容尾部） */
    position: static;
  }
}

@media (max-width: 640px) {
  .info-section,
  .chunks-section {
    padding: var(--space-4);
  }

  /* 标题行降级：徽章 + 名字换行，状态标签随行 */
  .info-title-row {
    flex-wrap: wrap;
  }

  .doc-filename {
    white-space: normal;
    word-break: break-all;
  }

  .meta-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  /* Embedding 这类长值在 2 列网格里放不下，单独占满整行 */
  .meta-item:has(.meta-value-long) {
    grid-column: 1 / -1;
  }
}

@media (max-width: 480px) {
  /* 极窄视口 2 列放不下值（"2.6 KB" 都被截断），降单列保读性 */
  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>