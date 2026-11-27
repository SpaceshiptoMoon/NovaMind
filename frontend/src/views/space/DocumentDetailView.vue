<template>
  <div v-loading="loading" class="document-detail-view">
    <!-- 顶栏：类型徽标 + 文件名 + 状态 + 关键统计 + 操作（元数据/标签/流程时间线收进可折叠详情） -->
    <header class="detail-header">
      <div class="header-row">
        <div
          class="file-type-badge"
          :style="{
            background: getFileTypeStyle(document?.file_type || '').bg,
            color: getFileTypeStyle(document?.file_type || '').color,
          }"
        >
          {{ (document?.file_type || 'FILE').toUpperCase() }}
        </div>
        <div class="header-text">
          <div class="header-title-row">
            <h2 class="doc-name" :title="document?.filename">
              {{ document?.filename || (loadFailed ? '文档不存在或已删除' : '加载中...') }}
            </h2>
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
          <!-- 关键统计 chips：只留最常看的数字，其余收进折叠详情 -->
          <div v-if="document" class="stat-chips">
            <span class="stat-chip">
              <span class="stat-label">大小</span>{{ formatFileSize(document.file_size || 0) }}
            </span>
            <span v-if="document.page_count != null" class="stat-chip">
              <span class="stat-label">页数</span>{{ document.page_count }}
            </span>
            <span v-if="(document.chunk_count ?? 0) > 0" class="stat-chip">
              <span class="stat-label">分块</span>{{ document.chunk_count }}
            </span>
            <span v-if="(document.token_count ?? 0) > 0" class="stat-chip">
              <span class="stat-label">Token</span>{{ document.token_count.toLocaleString() }}
            </span>
            <span v-if="document.char_count != null" class="stat-chip">
              <span class="stat-label">字符</span>{{ document.char_count.toLocaleString() }}
            </span>
            <span class="stat-chip">
              <span class="stat-label">上传</span>{{ formatDate(document.created_at) }}
            </span>
          </div>
        </div>
        <div class="header-actions">
          <el-button size="small" @click="showCompareDialog = true">
            <el-icon class="section-action-icon"><CopyDocument /></el-icon>
            对比预览
          </el-button>
          <el-tooltip content="详细信息（元数据 / 标签 / 流程时间线）" placement="top">
            <el-button
              size="small"
              :type="infoExpanded ? 'primary' : 'default'"
              @click="infoExpanded = !infoExpanded"
            >
              详情
            </el-button>
          </el-tooltip>
        </div>
      </div>

      <!-- 失败原因独立一行：可展开看全文 -->
      <p
        v-if="latestTask?.error_message && docStatus !== 2"
        class="error-line"
        :title="latestTask.error_message"
        @click="errorExpanded = !errorExpanded"
      >
        {{ errorDisplayText }}
      </p>

      <!-- 可折叠详细信息（原 info-section 全量内容收纳于此） -->
      <el-collapse-transition>
        <div v-show="infoExpanded" class="meta-detail">
          <div v-if="document" class="meta-grid">
            <div v-if="document.duration_seconds != null" class="meta-item">
              <span class="meta-label">时长</span>
              <span class="meta-value">{{ formatDuration(document.duration_seconds) }}</span>
            </div>
            <div v-if="document.chunk_type" class="meta-item">
              <span class="meta-label">内容类型</span>
              <span class="meta-value">{{
                chunkTypeLabels[document.chunk_type] || document.chunk_type
              }}</span>
            </div>
            <div v-if="document.frame_count != null" class="meta-item">
              <span class="meta-label">视频帧数</span>
              <span class="meta-value">{{ document.frame_count }}</span>
            </div>
            <div v-if="document.segment_count != null" class="meta-item">
              <span class="meta-label">音频分段数</span>
              <span class="meta-value">{{ document.segment_count }}</span>
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
              <span
                class="meta-value meta-value-long"
                :title="
                  document.embedding_model +
                  (document.embedding_dim != null ? ` · ${document.embedding_dim} 维` : '')
                "
              >
                {{ document.embedding_model
                }}<template v-if="document.embedding_dim != null">
                  · {{ document.embedding_dim }} 维</template
                >
              </span>
            </div>
            <div v-if="document.parse_duration_ms != null" class="meta-item">
              <span class="meta-label">解析耗时</span>
              <span class="meta-value">{{ formatDuration(document.parse_duration_ms / 1000) }}</span>
            </div>
            <div v-if="parseQualityWarnings.length > 0" class="meta-item">
              <span class="meta-label">解析质量</span>
              <span class="meta-value quality-warnings" :title="parseQualityWarnings.join('\n')"
                >⚠ {{ parseQualityWarnings.length }} 条降级警告</span
              >
            </div>
            <div v-else-if="document.quality" class="meta-item">
              <span class="meta-label">解析质量</span>
              <span class="meta-value">无警告</span>
            </div>
            <!-- 已纳入 Wiki 反向条：读完原文一步跳到 AI 综合页 -->
            <div v-if="wikiRefs.length > 0" class="meta-item">
              <span class="meta-label">Wiki</span>
              <span class="meta-value wiki-refs-value">
                <template v-for="(r, i) in wikiRefs.slice(0, 3)" :key="r.slug">
                  <RouterLink
                    class="wiki-ref-link"
                    :to="`/home/spaces/${spaceId}/knowledge-bases/${kbId}/wiki?page=${encodeURIComponent(r.slug)}`"
                    :title="r.title"
                    >《{{ r.title.length > 18 ? r.title.slice(0, 18) + '…' : r.title }}》</RouterLink
                  ><span v-if="i < Math.min(wikiRefs.length, 3) - 1">、</span>
                </template>
                <span v-if="wikiRefs.length > 3" class="wiki-refs-more">
                  等 {{ wikiRefs.length }} 页 →
                </span>
              </span>
            </div>
            <!-- 用户自定义标签：行内编辑 -->
            <div class="meta-item">
              <span class="meta-label">标签</span>
              <span v-if="!tagsEditing" class="meta-value tags-value">
                <template v-if="(document.tags || []).length > 0">
                  <el-tag
                    v-for="t in document.tags"
                    :key="t"
                    size="small"
                    effect="plain"
                    round
                    class="tag-chip"
                    >{{ t }}</el-tag
                  >
                  <el-button
                    text
                    size="small"
                    class="tags-edit-btn"
                    aria-label="编辑标签"
                    title="编辑标签"
                    @click="startEditTags"
                  >
                    <el-icon><Edit /></el-icon>
                  </el-button>
                </template>
                <el-button v-else text size="small" class="tags-add-btn" @click="startEditTags">
                  <el-icon><Plus /></el-icon>
                  打标签
                </el-button>
              </span>
              <span v-else class="meta-value tags-value">
                <el-select
                  v-model="tagsInput"
                  multiple
                  filterable
                  allow-create
                  default-first-option
                  placeholder="输入标签回车，可多个"
                  size="small"
                  class="tags-editor"
                  :max-collapse-tags="10"
                />
                <el-button size="small" type="primary" :loading="tagsSaving" @click="saveTags">
                  保存
                </el-button>
                <el-button size="small" @click="tagsEditing = false">取消</el-button>
              </span>
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
      </el-collapse-transition>
    </header>

    <!-- 左右分栏：左原文预览 / 右分块（可拖拽调宽） -->
    <el-splitter class="detail-split">
      <el-splitter-panel size="38" min="20" max="65" class="pane pane-preview">
        <div class="pane-header">
          <h4>原文预览</h4>
        </div>
        <DocumentOriginalPreview :space-id="spaceId" :kb-id="kbId" :document="document" />
      </el-splitter-panel>

      <el-splitter-panel size="62" min="35" class="pane pane-chunks">
        <!-- 叙事文档（视频专属）：章节化连贯文档，与碎片块并存；按需生成 -->
        <div v-if="isVideoDoc" class="narrative-section chunks-section">
          <div class="section-header">
            <h4>叙事文档</h4>
            <div class="section-header-right">
              <el-tag :type="narrativeTagType" effect="plain" size="small">
                {{ narrativeStatusText }}
              </el-tag>
              <el-button
                v-if="narrativeStatus === 'completed'"
                text
                size="small"
                @click="narrativeExpanded = !narrativeExpanded"
              >
                <el-icon class="section-action-icon"><View /></el-icon>
                {{ narrativeExpanded ? '收起' : '查看章节' }}
              </el-button>
              <el-button
                text
                size="small"
                :loading="narrativeGenerating"
                @click="handleGenerateNarrative"
              >
                {{ narrativeStatus === 'completed' ? '重新生成' : '生成章节文档' }}
              </el-button>
            </div>
          </div>
          <p class="narrative-desc">
            用 LLM 把碎片帧描述合成为章节化连贯叙事（全片梗概 +
            章节时间轴）；问答命中本视频内容时会自动附带章节摘要。
          </p>
          <div v-if="narrativeStatus === 'completed' && narrativeExpanded" class="narrative-body">
            <p v-if="narrative?.overview" class="narrative-overview">{{ narrative.overview }}</p>
            <div v-for="(ch, i) in narrative?.chapters ?? []" :key="i" class="narrative-chapter">
              <div class="chapter-title">
                <span class="chapter-index-badge">{{ i + 1 }}</span>
                <strong>{{ ch.title }}</strong>
                <span v-if="ch.start_time != null" class="meta-tag time-tag">
                  {{ formatDuration(ch.start_time) }}
                  -
                  {{ ch.end_time != null ? formatDuration(ch.end_time) : '末尾' }}
                </span>
              </div>
              <p class="chapter-summary">{{ ch.summary }}</p>
            </div>
          </div>
          <p v-if="narrativeStatus === 'failed'" class="narrative-error">
            {{ narrative?.error_message || '合成失败，可重试' }}
          </p>
        </div>

        <!-- 分块列表 -->
        <div class="chunks-section">
          <div class="chunks-toolbar">
            <el-input
              v-model="searchText"
              placeholder="搜索本页分块内容"
              clearable
              size="small"
              class="chunk-search"
            />
            <el-radio-group v-model="textMode" size="small">
              <el-radio-button value="ellipse">省略</el-radio-button>
              <el-radio-button value="full">全文</el-radio-button>
            </el-radio-group>
            <span class="chunk-count">{{ totalChunks }} 个分块</span>
            <div class="toolbar-right">
              <el-button size="small" @click="showCompareDialog = true">
                <el-icon class="section-action-icon"><CopyDocument /></el-icon>
                对比预览
              </el-button>
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

          <div v-if="filteredChunks.length > 0" class="chunks-list">
            <div
              v-for="chunk in filteredChunks"
              :key="chunk.chunk_id"
              class="chunk-card"
              :class="{ 'chunk-expanded': expandedChunks[chunk.chunk_index] }"
            >
              <div class="chunk-header" @click="toggleChunk(chunk.chunk_index)">
                <span class="chunk-index-badge">{{ chunk.chunk_index + 1 }}</span>
                <div class="chunk-meta">
                  <span
                    v-if="chunkMetaOf(chunk).chunk_role === 'parent'"
                    class="meta-tag chunk-role-tag parent"
                    >父块</span
                  >
                  <span
                    v-else-if="chunkMetaOf(chunk).chunk_role === 'child'"
                    class="meta-tag chunk-role-tag child"
                    >子块</span
                  >
                  <span
                    v-if="chunk.chunk_type && chunk.chunk_type !== 'text'"
                    class="meta-tag chunk-type-tag"
                    >{{ chunkTypeLabels[chunk.chunk_type] || chunk.chunk_type }}</span
                  >
                  <span v-if="chunkMetaOf(chunk).page" class="meta-tag"
                    >第 {{ chunkMetaOf(chunk).page }} 页</span
                  >
                  <span v-if="chunkMetaOf(chunk).section_title" class="meta-tag">{{
                    chunkMetaOf(chunk).section_title
                  }}</span>
                  <span v-if="chunkMetaOf(chunk).start_time != null" class="meta-tag time-tag">
                    {{ formatDuration(chunkMetaOf(chunk).start_time as number) }}
                    -
                    {{ formatDuration(chunkMetaOf(chunk).end_time as number) }}
                  </span>
                  <span v-if="chunk.has_embedding" class="meta-tag embedded">已向量化</span>
                </div>
                <el-icon
                  class="chunk-toggle"
                  :class="{ 'is-expanded': expandedChunks[chunk.chunk_index] }"
                >
                  <ArrowRight />
                </el-icon>
              </div>
              <!-- 折叠态：省略模式 3 行钳制 / 全文模式平铺（限高滚动） -->
              <div
                v-if="!expandedChunks[chunk.chunk_index]"
                class="chunk-preview"
                :class="{ 'is-full': textMode === 'full' }"
                @click="toggleChunk(chunk.chunk_index)"
              >
                <template v-if="chunk.chunk_type === 'image'">🖼 图片分块</template>
                <template v-else-if="textMode === 'full'">{{ chunk.content }}</template>
                <template v-else>{{ truncateContent(chunk.content, 160) }}</template>
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
                      @click="previewImage(chunk)"
                    />
                    <div class="chunk-image-desc">{{ chunk.content }}</div>
                  </template>
                  <!-- 视频帧图缩略图：后端把 metadata.frame_paths 预签名成 frame_urls（与检索
                       结果页同约定）；media_url 指向原视频文件，<img> 渲染不了，不能混用。
                       帧图与正文里的 VLM 描述一一对应，点击放大可翻帧 -->
                  <template v-else-if="frameThumbsOf(chunk).length">
                    <div class="chunk-frames">
                      <el-image
                        v-for="(url, fi) in frameThumbsOf(chunk)"
                        :key="fi"
                        :src="url"
                        :preview-src-list="frameThumbsOf(chunk)"
                        :initial-index="fi"
                        fit="cover"
                        loading="lazy"
                        hide-on-click-modal
                        preview-teleported
                        class="chunk-frame-thumb"
                      />
                    </div>
                    <MarkdownRenderer v-if="document" :content="chunk.content" />
                    <template v-else>{{ chunk.content }}</template>
                  </template>
                  <!-- content 里的 figure 短文件名已由后端 chunks 端点换成即时预签名 URL -->
                  <MarkdownRenderer v-else-if="document" :content="chunk.content" />
                  <template v-else>{{ chunk.content }}</template>
                </div>
                <div v-if="chunk.questions?.length > 0" class="chunk-questions">
                  <el-tag v-for="q in chunk.questions" :key="q" size="small" effect="plain" round>
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
              @update:page="
                (p: number) => {
                  chunkCurrentPage = p
                  fetchChunks()
                }
              "
              @update:page-size="
                (s: number) => {
                  chunkPageSize = s
                  chunkCurrentPage = 1
                  fetchChunks()
                }
              "
            />
          </div>
        </div>
      </el-splitter-panel>
    </el-splitter>

    <!-- 原文 / 解析MD 左右对比 -->
    <el-dialog
      v-model="showCompareDialog"
      @close="showCompareDialog = false"
      :title="`对比预览：${document?.filename || ''}`"
      width="95vw"
      destroy-on-close
      class="compare-dialog"
      align-center
    >
      <div class="compare-dialog-body">
        <DocumentCompareView
          :space-id="spaceId"
          :kb-id="kbId"
          :doc-id="docId"
          :filename="document?.filename || ''"
          @close="showCompareDialog = false"
        />
      </div>
    </el-dialog>

    <!-- 图片预览弹窗 -->
    <el-dialog
      v-model="previewVisible"
      :show-close="true"
      width="auto"
      class="image-preview-dialog"
      destroy-on-close
    >
      <img
        :src="previewUrl"
        style="max-width: 90vw; max-height: 80vh; object-fit: contain; display: block; margin: auto"
      />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 文档详情页。
 *
 * 对应路由 /home/spaces/:id/documents/:docId，顶栏收文件关键信息（元数据/标签/
 * 流程时间线折叠于「详情」），下方左右分栏：左原文预览、右分块列表（密度双态 +
 * 本页搜索）。分块列表（折叠预览 + 展开渲染 Markdown/图片）与右侧原文预览面板。
 * kbId 优先取 query，缺失时先反查归属知识库再加载，失败落「文档不存在」空态。
 */

import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, ArrowRight, View, Edit, Plus, CopyDocument } from '@element-plus/icons-vue'
import { documentApi } from '@/api/knowledge'
import Pagination from '@/components/common/Pagination.vue'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import DocumentOriginalPreview from '@/components/knowledge/DocumentOriginalPreview.vue'
import DocumentCompareView from '@/components/knowledge/DocumentCompareView.vue'
import { TaskNodeLogTable } from '@/components/knowledge'
import type { DocumentDetail, Chunk, DocumentTaskItem, VideoNarrativeResponse } from '@/api/types'
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

const showCompareDialog = ref(false)

// 详细信息折叠区（元数据网格/标签/流程时间线整体收纳，顶栏只留关键统计）
const infoExpanded = ref(false)

// 分块文本密度：ellipse=3 行省略（默认）/ full=全文平铺（RAGFlow 同款双态）
const textMode = ref<'full' | 'ellipse'>('ellipse')

// 本页分块搜索（服务端分页：过滤仅作用于当前页）
const searchText = ref('')

const filteredChunks = computed(() => {
  const kw = searchText.value.trim().toLowerCase()
  if (!kw) return chunks.value
  return chunks.value.filter((c) => (c.content || '').toLowerCase().includes(kw))
})

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

/** 解析质量警告明细（engine 层 quality 元数据，截断 50 条由后端保证） */
const parseQualityWarnings = computed(() => document.value?.quality?.warnings ?? [])

// 状态辅助
const docStatus = computed(() => document.value?.status ?? 0)
const currentStatusConfig = computed(
  () => taskStatusMap[docStatus.value] ?? { text: '未知', type: 'info' as const },
)

/** 分块空态描述：按文档状态区分「还没处理」与「处理失败」两种成因 */
const emptyChunkDescription = computed(() => {
  if (docStatus.value === 3) return '解析失败，没有产出分块；可在文档列表重试处理'
  if (docStatus.value === 1 || docStatus.value === 0)
    return '文档尚未完成解析，处理完成后这里会展示分块'
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
    // 文档类型就绪后才能判定视频文档，再拉叙事状态；已在合成中则续上轮询
    await fetchNarrative()
    void fetchWikiReferences()
    if (narrative.value?.status === 'running') scheduleNarrativePolling()
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
    const data = await documentApi.getDocumentChunks(spaceId.value, kbId.value, docId.value, {
      skip: (chunkCurrentPage.value - 1) * chunkPageSize.value,
      limit: chunkPageSize.value,
    })
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

// ===== 视频叙事文档（章节化连贯文档，按需生成） =====

// 与后端 _attach_narrative_chapters 的视频族判定同源（小写扩展名）
const VIDEO_FILE_TYPES = new Set(['mp4', 'mov', 'avi', 'mkv', 'webm'])

const narrative = ref<VideoNarrativeResponse | null>(null)
const narrativeExpanded = ref(false)
const narrativeGenerating = ref(false)
// 轮询句柄：running 状态下 3s 间隔查询直至 completed/failed；卸载时清理
let narrativePollTimer: ReturnType<typeof setTimeout> | null = null

// 已纳入 Wiki 反向条：按来源文档反查引用它的 wiki 页（失败静默，无引用不显示）
const wikiRefs = ref<{ slug: string; title: string; page_type: string }[]>([])

async function fetchWikiReferences() {
  if (kbId.value === 0 || !document.value) return
  try {
    const data = await documentApi.getWikiReferences(spaceId.value, kbId.value, document.value.id)
    wikiRefs.value = data.items || []
  } catch {
    wikiRefs.value = []
  }
}

// 用户自定义标签：行内编辑状态（保存走 PUT tags，后端规范化并即时同步 ES chunk）
const tagsEditing = ref(false)
const tagsSaving = ref(false)
const tagsInput = ref<string[]>([])

/** chunk 元数据读取：模板侧收敛 as 泛型断言（prettier 3.8.1 无法解析
    mustache 文本里的 `as Record<...>`，属性表达式不受影响） */
function chunkMetaOf(chunk: Chunk): Record<string, unknown> {
  return chunk.metadata ?? {}
}

/** 视频帧图缩略图：后端把 metadata.frame_paths（MinIO 路径）预签名成 frame_urls
    （响应层派生字段，与检索结果页同约定）；无帧图返回空数组不渲染 */
function frameThumbsOf(chunk: Chunk): string[] {
  const raw = chunkMetaOf(chunk).frame_urls
  return Array.isArray(raw) ? raw.filter((u): u is string => typeof u === 'string') : []
}

/** 分块图片点击放大：多语句行内 handler 会被 prettier 重排掉语句分隔符
    （编译报错），一律走方法 */
function previewImage(chunk: Chunk) {
  const url = chunk.media_url || chunk.image_url
  if (!url) return
  previewUrl.value = url
  previewVisible.value = true
}

function startEditTags() {
  tagsInput.value = [...(document.value?.tags || [])]
  tagsEditing.value = true
}

async function saveTags() {
  if (!document.value) return
  tagsSaving.value = true
  try {
    const data = await documentApi.setDocumentTags(
      spaceId.value,
      kbId.value,
      document.value.id,
      tagsInput.value,
    )
    document.value.tags = data.tags
    tagsEditing.value = false
    ElMessage.success('标签已保存，检索过滤即时生效')
  } catch (err: unknown) {
    const message =
      (err as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error
        ?.message || '标签保存失败'
    ElMessage.error(message)
  } finally {
    tagsSaving.value = false
  }
}

const isVideoDoc = computed(() =>
  VIDEO_FILE_TYPES.has((document.value?.file_type || '').toLowerCase()),
)

const narrativeStatus = computed(() => narrative.value?.status ?? 'not_generated')

const narrativeStatusText = computed(
  () =>
    (
      ({
        not_generated: '未生成',
        running: '合成中',
        completed: '已完成',
        failed: '失败',
        unknown: '未知',
      }) as Record<string, string>
    )[narrativeStatus.value] || '未知',
)

const narrativeTagType = computed(() => {
  if (narrativeStatus.value === 'completed') return 'success' as const
  if (narrativeStatus.value === 'failed') return 'danger' as const
  if (narrativeStatus.value === 'running') return 'warning' as const
  return 'info' as const
})

/** 拉取叙事文档状态；视频文档才发请求。 */
async function fetchNarrative() {
  if (kbId.value === 0 || !isVideoDoc.value) return
  try {
    narrative.value = await documentApi.getNarrative(spaceId.value, kbId.value, docId.value)
  } catch {
    // 状态获取失败不阻塞页面（保持未生成态，按钮仍可触发）
  }
}

/** 停止叙事轮询。 */
function stopNarrativePolling() {
  if (narrativePollTimer !== null) {
    clearTimeout(narrativePollTimer)
    narrativePollTimer = null
  }
}

/** 合成中轮询：直到终态或页面卸载；上限 15 分钟（10min 视频硬限 + 合成裕量）。 */
function scheduleNarrativePolling() {
  stopNarrativePolling()
  const deadline = Date.now() + 15 * 60 * 1000
  const tick = async () => {
    await fetchNarrative()
    void fetchWikiReferences()
    const status = narrative.value?.status
    if (status === 'completed' || status === 'failed' || Date.now() > deadline) {
      narrativePollTimer = null
      return
    }
    narrativePollTimer = setTimeout(tick, 3000)
  }
  narrativePollTimer = setTimeout(tick, 3000)
}

/** 触发叙事合成；重复生成覆盖旧文档（后端语义），弹确认防误覆盖。 */
async function handleGenerateNarrative() {
  if (kbId.value === 0) return
  if (narrativeStatus.value === 'completed') {
    try {
      await ElMessageBox.confirm('重新生成将覆盖现有章节文档，确定继续？', '重新生成叙事文档', {
        type: 'warning',
        confirmButtonText: '重新生成',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
  }
  narrativeGenerating.value = true
  try {
    await documentApi.generateNarrative(spaceId.value, kbId.value, docId.value)
    narrative.value = {
      ...(narrative.value ?? { document_id: docId.value, exists: true }),
      status: 'running',
    }
    ElMessage.success('叙事合成已入队')
    scheduleNarrativePolling()
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '触发叙事合成失败')
  } finally {
    narrativeGenerating.value = false
  }
}

onUnmounted(stopNarrativePolling)

// 任务到达后：失败/处理中的任务默认展开时间线（直接看到卡在哪个节点）
function maybeAutoExpandTimeline() {
  if (docStatus.value === 3 || docStatus.value === 1) {
    timelineExpanded.value = true
  }
}
</script>

<style scoped>
.document-detail-view {
  display: flex;
  flex-direction: column;
  /* 顶栏 + 分栏占满可视高度，分栏内部各自滚动（RAGFlow 同款全屏工作台形态） */
  height: calc(100vh - 120px);
  min-height: 480px;
}

/* ===== 顶栏 ===== */

.detail-header {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  padding: var(--space-3) var(--space-5);
  margin-bottom: var(--space-3);
  flex-shrink: 0;
}

.header-row {
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

.header-text {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.header-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.doc-name {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  font-family: var(--font-display);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-status-tag {
  flex-shrink: 0;
}

/* 关键统计 chips：行内 label 随值的紧凑药丸 */
.stat-chips {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  min-width: 0;
  overflow: hidden;
}

.stat-chip {
  font-size: var(--text-xs);
  color: var(--color-text);
  background: var(--color-bg-hover);
  border-radius: var(--radius-sm);
  padding: 2px 8px;
  white-space: nowrap;
}

.stat-label {
  color: var(--color-text-muted);
  margin-right: 4px;
}

.header-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

/* 失败原因独立一行：可展开看全文 */
.error-line {
  margin: var(--space-2) 0 0;
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--color-danger);
  background: var(--color-danger-subtle);
  border-radius: var(--radius-md);
  cursor: pointer;
  word-break: break-word;
}

/* ===== 可折叠详细信息（原 meta-grid + 标签 + Wiki + 流程时间线） ===== */

.meta-detail {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border-light);
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: var(--space-2) var(--space-4);
}

.meta-item:has(.meta-value-long) {
  grid-column: span 2;
}

.meta-item {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  min-width: 0;
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

.quality-warnings {
  color: var(--color-warning, #b45309);
  cursor: help;
}

.tags-value {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.tag-chip {
  margin-right: 0;
}

.tags-add-btn {
  height: 22px;
  padding: 0 10px;
  border: 1px dashed var(--color-border);
  border-radius: 999px;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-weight: var(--weight-regular);
}

.tags-add-btn:hover {
  color: var(--color-primary);
  border-color: var(--color-primary);
  background: transparent;
}

.tags-edit-btn {
  padding: 2px 4px;
  color: var(--color-text-muted);
}

.tags-edit-btn:hover {
  color: var(--color-primary);
}

.tags-editor {
  min-width: 260px;
}

.wiki-refs-value {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
}

.wiki-ref-link {
  color: var(--color-primary);
  text-decoration: none;
}

.wiki-ref-link:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

.wiki-refs-more {
  color: var(--color-text-muted);
}

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
  font-size: var(--text-sm);
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

/* ===== 左右分栏 ===== */

.detail-split {
  flex: 1;
  min-height: 0;
}

.pane {
  height: 100%;
  overflow-y: auto;
  padding: var(--space-4);
}

.pane-preview {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
}

.pane-header {
  margin-bottom: var(--space-3);
}

.pane-header h4 {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

/* ===== 分块区 ===== */

.chunks-section {
  background: transparent;
  border: none;
  padding: 0;
}

/* chunks 工具栏：sticky 跟随滚动（搜索/密度切换/计数常驻） */
.chunks-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--color-bg-page, transparent);
  padding: var(--space-2) 0;
  margin-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border-light);
}

.chunk-search {
  width: 220px;
}

.chunk-count {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  white-space: nowrap;
  margin-left: auto;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.section-header h4 {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.section-header-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.section-action-icon {
  margin-right: var(--space-1);
}

/* ===== 叙事文档（视频） ===== */

.narrative-desc {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.narrative-overview {
  margin: 0 0 var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-hover);
  border-radius: var(--radius-lg);
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text);
}

.narrative-chapter {
  padding: var(--space-3) 0;
  border-top: 1px solid var(--color-border-light);
}

.chapter-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
}

.chapter-summary {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text-secondary);
}

.narrative-error {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-danger);
}

/* ===== 分块卡片（RAGFlow 风格重绘） ===== */

.chunks-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.chunk-card {
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  padding: var(--space-3) var(--space-4);
  transition:
    border-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.chunk-card:hover {
  border-color: var(--color-border);
  background: var(--color-bg-hover);
}

.chunk-card.chunk-expanded {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 1px var(--color-primary-muted);
  background: var(--color-bg-card-elevated);
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

/* 折叠态预览：省略模式 3 行钳制；全文模式平铺限高滚动 */
.chunk-preview {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: 1.6;
  cursor: pointer;
  padding-top: var(--space-2);
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
  white-space: pre-wrap;
  word-break: break-word;
}

.chunk-preview.is-full {
  display: block;
  -webkit-line-clamp: unset;
  max-height: 420px;
  overflow-y: auto;
  font-family: var(--font-mono);
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

/* 父子分块角色徽标：父块=回带容器（无向量不召回），子块=检索单元 */
.meta-tag.chunk-role-tag.parent {
  color: var(--color-warning);
  background: var(--color-warning-subtle);
  font-weight: var(--weight-medium);
}

.meta-tag.chunk-role-tag.child {
  color: var(--color-info);
  background: var(--color-info-subtle);
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

/* 视频帧图缩略图条：规格同 SearchView .result-frames（16:9 缩略图），置于帧描述正文之上 */
.chunk-frames {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.chunk-frame-thumb {
  width: 120px;
  height: 68px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
  cursor: zoom-in;
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

/* ===== 对比预览对话框 ===== */

.compare-dialog-body {
  height: 78vh;
  display: flex;
  flex-direction: column;
}

.compare-dialog-body > * {
  flex: 1;
  min-height: 0;
}
</style>
