<template>
  <div class="search-view">
    <div class="kb-layout">
      <KbSidebar :nav-items="kbNavItems" />

      <!-- 右侧内容 -->
      <div class="kb-content">
        <!-- 顶部：检索问题栏 -->
        <div class="search-query-bar">
          <el-input
            v-model="searchForm.query"
            type="textarea"
            :rows="1"
            placeholder="输入查询内容，按 Enter 检索..."
            maxlength="2000"
            resize="none"
            class="query-input"
            @keydown.enter.exact.prevent="handleSearch"
          />
          <el-button
            type="primary"
            :loading="searching || imageSearching"
            :disabled="!searchForm.kb_id || !searchForm.query.trim()"
            class="query-search-btn"
            @click="handleSearch"
          >
            <el-icon><Search /></el-icon>
            {{ searching ? '检索中...' : '检索' }}
          </el-button>
        </div>

        <!-- 下方：结果 + 参数 -->
        <div class="search-body">
          <!-- ====== 中间：检索结果 ====== -->
          <main class="search-main">
            <!-- 有结果 -->
            <template v-if="searchResults.length > 0">
              <!-- 结果头部 -->
              <div class="results-header">
                <h3>检索结果</h3>
                <span class="results-meta">
                  共 {{ totalResults }} 条 · {{ elapsedMs }}ms
                  <el-tag v-if="cached" type="success" size="small" effect="plain">缓存</el-tag>
                  <el-tag v-if="modeFallback" type="warning" size="small" effect="plain">降级: {{ originalMode }}</el-tag>
                </span>
              </div>

              <!-- 查询改写 -->
              <div v-if="rewrittenQueries?.length" class="rewritten-section">
                <span class="rewritten-label">查询改写:</span>
                <el-tag v-for="q in rewrittenQueries" :key="q" size="small" type="primary" effect="plain">
                  {{ q }}
                </el-tag>
              </div>

              <!-- AI 回答 -->
              <div v-if="llmAnswer" class="llm-answer">
                <div class="llm-answer-header">
                  <span>AI 回答</span>
                  <span class="llm-answer-meta">
                    <span v-if="answerModel" class="llm-answer-model">{{ answerModel }}</span>
                    <span v-if="answerElapsedMs" class="llm-answer-model">{{ answerElapsedMs }}ms</span>
                  </span>
                </div>
                <div class="llm-answer-content">
                  <MarkdownRenderer :content="llmAnswer" />
                </div>
              </div>

              <!-- 多模态：图片网格 -->
              <div v-if="hasImage" class="image-grid">
                <div
                  v-for="(result, index) in searchResults"
                  :key="result.chunk_id"
                  class="image-card"
                  @click="previewUrl = (result.image_url || ''); previewVisible = true"
                >
                  <div class="image-card-img">
                    <img
                      v-if="result.image_url"
                      :src="result.image_url"
                      :alt="(result.file_info as Record<string, string>)?.filename || ''"
                      loading="lazy"
                    />
                    <div v-else class="image-card-placeholder">
                      <el-icon :size="32" color="var(--color-text-faint)"><Upload /></el-icon>
                    </div>
                    <div class="image-card-overlay">
                      <span class="image-card-score" :class="getScoreClass(result.score)">
                        {{ (result.score * 100).toFixed(1) }}%
                      </span>
                      <span class="image-card-name">{{ (result.file_info as Record<string, string>)?.filename || '' }}</span>
                    </div>
                  </div>
                  <div class="image-card-footer">
                    <span class="image-card-index">#{{ index + 1 }}</span>
                  </div>
                </div>
              </div>

              <!-- 文本/视频/音频：结果卡片列表 -->
              <div v-else class="results-list">
                <div
                  v-for="(result, index) in searchResults"
                  :key="result.chunk_id"
                  class="result-card"
                >
                  <div class="result-header">
                    <span class="result-index">{{ index + 1 }}</span>
                    <el-tag
                      v-if="result.chunk_type && result.chunk_type !== 'text'"
                      :type="result.chunk_type === 'image' ? 'warning' : result.chunk_type === 'video' ? 'primary' : 'danger'"
                      size="small"
                      effect="plain"
                    >{{ chunkTypeLabels[result.chunk_type] || result.chunk_type }}</el-tag>
                    <span class="result-doc">{{ (result.file_info as Record<string, string>)?.filename || `文档 #${result.document_id}` }}</span>
                    <span class="result-score" :class="getScoreClass(result.score)">
                      {{ (result.score * 100).toFixed(1) }}%
                    </span>
                  </div>
                  <div class="result-content">
                    <img
                      v-if="result.chunk_type === 'image' && (result.media_url || result.image_url)"
                      :src="result.media_url || result.image_url"
                      class="result-thumbnail"
                      loading="lazy"
                      @click="previewUrl = (result.media_url || result.image_url)!; previewVisible = true"
                    />
                    <template v-else>{{ result.content }}</template>
                  </div>
                  <div class="result-footer">
                    <span v-if="(result.metadata as Record<string, unknown>)?.page">第 {{ (result.metadata as Record<string, unknown>).page }} 页</span>
                    <span v-if="result.chunk_type === 'video' && (result.metadata as Record<string, unknown>)?.start_time != null">
                      {{ formatDuration((result.metadata as Record<string, unknown>).start_time as number) }}
                      -
                      {{ formatDuration((result.metadata as Record<string, unknown>).end_time as number) }}
                    </span>
                    <span v-if="result.chunk_type === 'audio' && (result.metadata as Record<string, unknown>)?.start_time != null">
                      {{ formatDuration((result.metadata as Record<string, unknown>).start_time as number) }}
                      -
                      {{ formatDuration((result.metadata as Record<string, unknown>).end_time as number) }}
                    </span>
                    <span>分块 #{{ result.chunk_index + 1 }}</span>
                  </div>
                  <div v-if="result.questions?.length" class="result-questions">
                    <el-tag
                      v-for="q in result.questions.slice(0, 3)"
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
            </template>

            <!-- 空状态 -->
            <EmptyState
              v-else-if="hasSearched"
              variant="search"
              title="未找到相关结果"
              description="尝试调整查询内容或检索模式"
            >
              <el-button @click="handleReset">重置搜索</el-button>
            </EmptyState>

            <!-- 未搜索时的引导 -->
            <div v-else class="search-empty">
              <el-icon :size="48" color="var(--color-text-faint)"><Search /></el-icon>
              <p class="search-empty-title">输入查询内容开始检索</p>
              <p class="search-empty-desc">在上方输入查询内容并选择知识库，按 Enter 或点击检索按钮开始搜索</p>
            </div>
          </main>

          <!-- ====== 右侧：检索参数 ====== -->
          <aside class="search-params">
            <!-- 知识库选择 -->
            <div class="param-section">
              <label class="param-section-label">知识库</label>
              <el-select
                v-model="searchForm.kb_id"
                placeholder="选择知识库"
                class="param-full-select"
                @change="handleKbChange"
              >
                <el-option
                  v-for="kb in knowledgeBases"
                  :key="kb.id"
                  :label="kb.name"
                  :value="kb.id"
                />
              </el-select>
            </div>

            <!-- 检索模式下拉（非纯图片空间） -->
            <div v-if="!hasImage" class="param-section">
              <label class="param-section-label">检索模式</label>
              <el-select v-model="searchForm.search_mode" size="small" class="param-full-select">
                <el-option
                  v-for="mode in filteredSearchModes"
                  :key="mode.mode"
                  :label="mode.label"
                  :value="mode.mode"
                />
              </el-select>
            </div>

            <!-- 基础参数 -->
            <div class="param-section">
              <div class="param-row">
                <span class="param-label">相似度阈值</span>
                <span class="param-value">{{ (searchForm.score_threshold * 100).toFixed(0) }}%</span>
              </div>
              <el-slider
                v-model="searchForm.score_threshold"
                :min="0"
                :max="1"
                :step="0.05"
                :show-tooltip="false"
              />
              <div class="param-row" style="margin-top: var(--space-3)">
                <span class="param-label">返回数量</span>
                <el-input-number
                  v-model="searchForm.top_k"
                  :min="1"
                  :max="100"
                  size="small"
                  style="width: 100px"
                />
              </div>
            </div>

            <!-- LLM 开关 + 模型选择（非纯图片空间） -->
            <div v-if="!hasImage" class="param-section">
              <div class="param-row">
                <span class="param-label">LLM 回答</span>
                <el-switch v-model="searchForm.llm_enabled" size="small" />
              </div>
              <el-select
                v-model="searchForm.llm_model"
                :disabled="!searchForm.llm_enabled"
                placeholder="默认模型"
                clearable
                size="small"
                class="param-full-select"
                style="margin-top: var(--space-2)"
              >
                <el-option v-for="m in availableLlmModels" :key="m" :label="m" :value="m" />
              </el-select>
            </div>

            <!-- 以图搜图区域（仅多模态空间） -->
            <div v-if="hasImage" class="param-section">
              <label class="param-section-label">以图搜图</label>
              <div
                class="image-drop-zone"
                :class="{ 'is-dragging': isDragging }"
                @dragover.prevent="isDragging = true"
                @dragleave="isDragging = false"
                @drop.prevent="handleImageDrop"
                @click="triggerImageSearch"
              >
                <template v-if="queryImagePreview">
                  <img :src="queryImagePreview" class="drop-zone-preview" />
                  <el-button
                    size="small"
                    circle
                    class="drop-zone-clear"
                    @click.stop="clearQueryImage"
                  >
                    <el-icon><Close /></el-icon>
                  </el-button>
                </template>
                <template v-else>
                  <el-icon :size="28" color="var(--color-text-muted)"><Upload /></el-icon>
                  <span class="drop-zone-text">拖拽或点击上传图片</span>
                </template>
              </div>
              <input
                ref="imageInput"
                type="file"
                accept=".jpg,.jpeg,.png,.gif,.webp"
                style="display: none"
                @change="handleImageFileChange"
              />
            </div>

            <!-- 高级设置折叠（仅文本空间） -->
            <el-collapse v-if="!hasImage" v-model="advancedCollapsed" class="params-collapse">
              <el-collapse-item title="高级设置" name="advanced">
                <!-- 检索参数 -->
                <div class="advanced-section">
                  <div class="section-title">检索参数</div>
                  <div class="adv-row">
                    <span class="adv-label">向量权重</span>
                    <el-slider v-model="searchForm.vector_weight" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
                  </div>
                  <div class="adv-row">
                    <span class="adv-label">BM25权重</span>
                    <el-slider v-model="searchForm.bm25_weight" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
                  </div>
                  <div class="adv-row">
                    <span class="adv-label">内容权重</span>
                    <el-slider v-model="searchForm.content_weight" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
                  </div>
                  <div class="adv-row">
                    <span class="adv-label">问题权重</span>
                    <el-slider v-model="searchForm.question_weight" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
                  </div>
                  <div class="adv-row">
                    <span class="adv-label">RRF K</span>
                    <el-input-number v-model="searchForm.rrf_k" :min="1" :max="200" size="small" />
                  </div>
                  <div class="adv-row">
                    <span class="adv-label">使用缓存</span>
                    <el-switch v-model="searchForm.use_cache" size="small" />
                  </div>
                  <div class="adv-row">
                    <span class="adv-label">模式降级</span>
                    <el-switch v-model="searchForm.fallback_on_unavailable" size="small" />
                  </div>
                </div>

                <!-- Rerank -->
                <div class="advanced-section">
                  <div class="section-title">重排序</div>
                  <div class="adv-row">
                    <span class="adv-label">启用 Rerank</span>
                    <el-switch v-model="searchForm.rerank_enabled" size="small" />
                  </div>
                  <div class="adv-row">
                    <span class="adv-label">数量</span>
                    <el-input-number v-model="searchForm.rerank_top_k" :min="1" :max="20" :disabled="!searchForm.rerank_enabled" size="small" />
                  </div>
                  <div class="adv-row">
                    <span class="adv-label">模型</span>
                    <el-select v-model="searchForm.rerank_model" :disabled="!searchForm.rerank_enabled" placeholder="默认" clearable size="small" style="flex:1">
                      <el-option v-for="m in availableRerankModels" :key="m" :label="m" :value="m" />
                    </el-select>
                  </div>
                </div>

                <!-- LLM -->
                <div class="advanced-section">
                  <div class="section-title">LLM</div>
                  <div class="adv-row">
                    <span class="adv-label">温度</span>
                    <el-slider v-model="searchForm.llm_temperature" :min="0" :max="2" :step="0.1" :disabled="!searchForm.llm_enabled" show-input :show-input-controls="false" />
                  </div>
                  <div class="adv-row">
                    <span class="adv-label">Top P</span>
                    <el-slider v-model="searchForm.llm_top_p" :min="0" :max="1" :step="0.1" :disabled="!searchForm.llm_enabled" show-input :show-input-controls="false" />
                  </div>
                </div>

                <!-- 查询改写 -->
                <div class="advanced-section">
                  <div class="section-title">查询改写</div>
                  <div class="adv-row">
                    <span class="adv-label">策略</span>
                    <el-select v-model="searchForm.qrw_strategy" size="small" style="flex:1">
                      <el-option label="不启用" value="" />
                      <el-option label="HyDE" value="hyde" />
                      <el-option label="子问题拆分" value="sub_query" />
                    </el-select>
                  </div>
                  <div v-if="searchForm.qrw_strategy" class="adv-row">
                    <span class="adv-label">模型</span>
                    <el-input v-model="searchForm.qrw_llm_model" placeholder="默认" size="small" style="flex:1" />
                  </div>
                  <template v-if="searchForm.qrw_strategy === 'sub_query'">
                    <div class="adv-row">
                      <span class="adv-label">子问题数</span>
                      <el-input-number v-model="searchForm.qrw_sub_query_count" :min="2" :max="5" size="small" />
                    </div>
                    <div class="adv-row">
                      <span class="adv-label">合并方式</span>
                      <el-select v-model="searchForm.qrw_sub_query_merge_mode" size="small" style="flex:1">
                        <el-option label="RRF 融合" value="rrf" />
                        <el-option label="分数取最大" value="score" />
                      </el-select>
                    </div>
                  </template>
                  <div v-if="searchForm.qrw_strategy === 'hyde'" class="adv-row" style="flex-direction:column;align-items:stretch">
                    <span class="adv-label" style="margin-bottom:4px">HyDE 提示词</span>
                    <el-input v-model="searchForm.qrw_hyde_prompt" type="textarea" :rows="2" maxlength="2000" placeholder="留空使用默认" size="small" />
                  </div>
                </div>

                <el-button size="small" @click="handleReset" style="width:100%">重置默认</el-button>
              </el-collapse-item>
            </el-collapse>
          </aside>
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
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, ArrowDown, Upload, Close, Document, DataAnalysis } from '@element-plus/icons-vue'
import { searchApi } from '@/api/search'
import { documentApi } from '@/api/document'
import { spaceApi } from '@/api/space'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import KbSidebar from '@/components/common/KbSidebar.vue'
import type { KbNavItem } from '@/components/common/KbSidebar.vue'
import type { KnowledgeBase, SearchMode, SearchResultItem, SearchResponse } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import { normalizeSpaceTypes, hasModality, chunkTypeLabels } from '@/utils/document'
import { formatDuration } from '@/utils/format'

const route = useRoute()

const spaceId = computed(() => Number(route.params.id))
const currentKbId = computed(() => route.query.kbId || '')

const kbNavItems = computed<KbNavItem[]>(() => {
  const sid = spaceId.value
  const kid = currentKbId.value
  return [
    { label: '文档管理', to: `/home/spaces/${sid}/knowledge-bases/${kid}/documents`, route: 'Documents', active: route.name === 'Documents' || route.name === 'DocumentDetail', icon: Document },
    { label: '任务列表', to: `/home/spaces/${sid}/knowledge-bases/${kid}/tasks`, route: 'DocumentTasks', active: route.name === 'DocumentTasks', icon: DataAnalysis },
    { label: '检索', to: `/home/spaces/${sid}/search?kbId=${kid}`, route: 'Search', active: route.name === 'Search', icon: Search },
    { label: '评测', to: `/home/spaces/${sid}/knowledge-bases/${kid}/evaluation`, route: 'KbEvaluation', active: route.name === 'KbEvaluation', icon: DataAnalysis },
  ]
})

const spaceTypes = ref<string[]>(['text'])
const hasImage = computed(() => hasModality(spaceTypes.value, 'image'))
const searching = ref(false)
const hasSearched = ref(false)
const showAdvanced = ref(false)
const advancedCollapsed = ref<string[]>([])
const knowledgeBases = ref<KnowledgeBase[]>([])
const searchModes = ref<SearchMode[]>([])
const filteredSearchModes = computed(() => {
  if (hasImage.value) {
    return searchModes.value.filter(m =>
      m.mode === 'image_vector' || m.mode === 'text_to_image'
    )
  }
  return searchModes.value
})
const searchResults = ref<SearchResultItem[]>([])
const totalResults = ref(0)
const elapsedMs = ref(0)
const cached = ref(false)
const modeFallback = ref(false)
const availableLlmModels = ref<string[]>([])
const availableRerankModels = ref<string[]>([])
const defaultLlmModel = ref('')
const defaultRerankModel = ref('')
const rewrittenQueries = ref<string[] | null>(null)
const llmAnswer = ref<string | null>(null)
const answerModel = ref<string | null>(null)
const answerElapsedMs = ref<number | null>(null)
const originalMode = ref<string | null>(null)

// 图片搜索
const imageSearching = ref(false)
const imageInput = ref<HTMLInputElement | null>(null)
const isDragging = ref(false)
const queryImagePreview = ref<string | null>(null)
const previewVisible = ref(false)
const previewUrl = ref('')

// 默认检索参数
const defaultSearchForm = {
  kb_id: null as number | null,
  query: '',
  search_mode: 'content_hybrid',
  top_k: 10,
  vector_weight: 0.7,
  bm25_weight: 0.3,
  content_weight: 0.6,
  question_weight: 0.4,
  rrf_k: 60,
  score_threshold: 0,
  rerank_enabled: false,
  rerank_top_k: 3,
  rerank_model: '',
  llm_enabled: false,
  llm_model: '',
  llm_temperature: 0.7,
  llm_top_p: 0.9,
  qrw_strategy: '',
  qrw_hyde_prompt: '',
  qrw_sub_query_count: 3,
  qrw_sub_query_merge_mode: 'rrf' as 'rrf' | 'score',
  qrw_llm_model: '',
  filters_json: '',
  use_cache: true,
  fallback_on_unavailable: true,
}

const searchForm = reactive({ ...defaultSearchForm })

function getScoreClass(score: number): string {
  if (score >= 0.8) return 'score-high'
  if (score >= 0.5) return 'score-mid'
  return 'score-low'
}

async function fetchKnowledgeBases() {
  try {
    const data = await knowledgeBaseApi.getKnowledgeBases(spaceId.value)
    knowledgeBases.value = (data.items || []).filter((kb): kb is KnowledgeBase => kb && typeof kb.id !== 'undefined')

    if (knowledgeBases.value.length > 0 && !searchForm.kb_id) {
      searchForm.kb_id = knowledgeBases.value[0]!.id
      fetchSearchModes()
    }
  } catch {
    ElMessage.error('获取知识库列表失败')
  }
}

async function fetchSearchModes() {
  if (!searchForm.kb_id) return

  try {
    const data = await searchApi.getSearchModes(spaceId.value, searchForm.kb_id)
    searchModes.value = data.modes || []

    if (hasImage.value) {
      searchForm.search_mode = 'text_to_image'
    }
  } catch {
    // 忽略错误
  }

  try {
    const config = await searchApi.getModelConfig(spaceId.value, searchForm.kb_id)
    availableLlmModels.value = config.available_llm_models || []
    availableRerankModels.value = config.available_rerank_models || []
    defaultLlmModel.value = config.default_llm_model || ''
    defaultRerankModel.value = config.default_rerank_model || ''
  } catch {
    // 忽略错误
  }
}

function handleKbChange() {
  fetchSearchModes()
}

function handleReset() {
  const kbId = searchForm.kb_id
  Object.assign(searchForm, { ...defaultSearchForm, kb_id: kbId })
}

async function handleSearch() {
  if (!searchForm.kb_id || !searchForm.query.trim()) {
    ElMessage.warning('请选择知识库并输入查询内容')
    return
  }

  searching.value = true
  hasSearched.value = true

  let filters: Record<string, unknown> | undefined
  if (searchForm.filters_json.trim()) {
    try {
      filters = JSON.parse(searchForm.filters_json.trim())
    } catch {
      ElMessage.error('过滤条件 JSON 格式错误')
      searching.value = false
      return
    }
  }

  const queryRewrite = searchForm.qrw_strategy
    ? {
        strategy: searchForm.qrw_strategy as 'hyde' | 'sub_query',
        ...(searchForm.qrw_strategy === 'hyde' && searchForm.qrw_hyde_prompt
          ? { hyde_prompt: searchForm.qrw_hyde_prompt }
          : {}),
        ...(searchForm.qrw_strategy === 'sub_query'
          ? {
              sub_query_count: searchForm.qrw_sub_query_count,
              sub_query_merge_mode: searchForm.qrw_sub_query_merge_mode,
            }
          : {}),
        ...(searchForm.qrw_llm_model ? { llm_model: searchForm.qrw_llm_model } : {}),
      }
    : undefined

  try {
    let data: SearchResponse
    if (hasImage.value) {
      data = await searchApi.multimodalSearch(spaceId.value, searchForm.kb_id, {
        query: searchForm.query,
        search_mode: 'text_to_image',
        top_k: searchForm.top_k,
        score_threshold: searchForm.score_threshold,
      })
    } else {
      data = await searchApi.search(spaceId.value, searchForm.kb_id, {
        query: searchForm.query,
        search_mode: searchForm.search_mode,
        top_k: searchForm.top_k,
        weights: {
          vector_weight: searchForm.vector_weight,
          bm25_weight: searchForm.bm25_weight,
          content_weight: searchForm.content_weight,
          question_weight: searchForm.question_weight,
          rrf_k: searchForm.rrf_k,
        },
        score_threshold: searchForm.score_threshold,
        rerank: {
          enabled: searchForm.rerank_enabled,
          top_k: searchForm.rerank_top_k,
          model: searchForm.rerank_model || undefined,
        },
        llm: searchForm.llm_enabled
          ? {
              enabled: true,
              ...(searchForm.llm_model ? { model: searchForm.llm_model } : {}),
              temperature: searchForm.llm_temperature,
              top_p: searchForm.llm_top_p,
            }
          : undefined,
        query_rewrite: queryRewrite,
        filters,
        use_cache: searchForm.use_cache,
        fallback_on_unavailable: searchForm.fallback_on_unavailable,
      })
    }
    searchResults.value = data.results || []

    // 图片搜索：根据 document_id 代理获取图片 blob URL
    if (hasImage.value && searchResults.value.length > 0) {
      const uniqueDocIds = [...new Set(searchResults.value.map(r => r.document_id))]
      const urlMap = await Promise.all(
        uniqueDocIds.map(docId =>
          documentApi.getDocumentImage(spaceId.value, searchForm.kb_id, docId)
            .then(url => ({ docId, url }))
            .catch(() => ({ docId, url: '' }))
        )
      )
      const urlLookup = new Map(urlMap.map(item => [item.docId, item.url]))
      searchResults.value = searchResults.value.map(r => ({
        ...r,
        image_url: r.image_url || urlLookup.get(r.document_id) || '',
      }))
    }

    totalResults.value = data.total || 0
    elapsedMs.value = data.elapsed_ms || 0
    cached.value = data.cached || false
    modeFallback.value = data.mode_fallback || false
    rewrittenQueries.value = data.rewritten_queries || null
    llmAnswer.value = data.answer || null
    answerModel.value = data.answer_model || null
    answerElapsedMs.value = data.answer_elapsed_ms || null
    originalMode.value = data.original_mode || null
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '检索失败')
    searchResults.value = []
    llmAnswer.value = null
    answerModel.value = null
    answerElapsedMs.value = null
    originalMode.value = null
  } finally {
    searching.value = false
  }
}

function triggerImageSearch() {
  imageInput.value?.click()
}

async function handleImageFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !searchForm.kb_id) return

  if (queryImagePreview.value) {
    URL.revokeObjectURL(queryImagePreview.value)
  }
  queryImagePreview.value = URL.createObjectURL(file)

  imageSearching.value = true
  hasSearched.value = true

  try {
    const imageBase64 = await fileToBase64(file)

    const data = await searchApi.multimodalSearch(spaceId.value, searchForm.kb_id, {
      image_base64: imageBase64,
      search_mode: 'image_to_image',
      top_k: searchForm.top_k,
      score_threshold: searchForm.score_threshold,
    })
    searchResults.value = data.results || []

    if (searchResults.value.length > 0) {
      const uniqueDocIds = [...new Set(searchResults.value.map(r => r.document_id))]
      const urlMap = await Promise.all(
        uniqueDocIds.map(docId =>
          documentApi.getDocumentImage(spaceId.value, searchForm.kb_id, docId)
            .then(url => ({ docId, url }))
            .catch(() => ({ docId, url: '' }))
        )
      )
      const urlLookup = new Map(urlMap.map(item => [item.docId, item.url]))
      searchResults.value = searchResults.value.map(r => ({
        ...r,
        image_url: r.image_url || urlLookup.get(r.document_id) || '',
      }))
    }

    totalResults.value = data.total || 0
    elapsedMs.value = data.elapsed_ms || 0
    cached.value = data.cached || false
    modeFallback.value = false
    rewrittenQueries.value = null
    llmAnswer.value = null
    answerModel.value = null
    answerElapsedMs.value = null
    originalMode.value = null
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '图片搜索失败')
    searchResults.value = []
  } finally {
    imageSearching.value = false
    input.value = ''
  }
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      const base64 = result.split(',')[1] || result
      resolve(base64)
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

function handleImageDrop(event: DragEvent) {
  isDragging.value = false
  if (!hasImage.value) return
  const file = event.dataTransfer?.files?.[0]
  if (!file || !searchForm.kb_id) return
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请拖入图片文件')
    return
  }
  const dt = new DataTransfer()
  dt.items.add(file)
  if (imageInput.value) {
    imageInput.value.files = dt.files
    imageInput.value.dispatchEvent(new Event('change'))
  }
}

function clearQueryImage() {
  if (queryImagePreview.value) {
    URL.revokeObjectURL(queryImagePreview.value)
  }
  queryImagePreview.value = null
}

onMounted(async () => {
  fetchKnowledgeBases()
  try {
    // 优先从 KB config 读取 space_type，fallback 到 Space config
    const kbId = currentKbId.value
    if (kbId) {
      const kbConfig = await knowledgeBaseApi.getConfig(spaceId.value, Number(kbId))
      if (kbConfig.config?.space_type && Array.isArray(kbConfig.config.space_type) && kbConfig.config.space_type.length > 0) {
        spaceTypes.value = kbConfig.config.space_type
        return
      }
    }
    const space = await spaceApi.getSpace(spaceId.value)
    spaceTypes.value = normalizeSpaceTypes(space.config)
  } catch {
    // 默认 text
  }
})
</script>

<style scoped>
/* ===== Root Layout ===== */
.search-view {
  height: 100%;
}

/* ===== KB Layout: Sidebar + Content ===== */
.kb-layout {
  display: flex;
  height: 100%;
}

/* ===== Right Content ===== */
.kb-content {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ===== Top: Search Query Bar ===== */
.search-query-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-card);
  flex-shrink: 0;
}

.query-input {
  flex: 1;
}

.query-input :deep(.el-textarea__inner) {
  border-radius: var(--radius-lg);
  font-size: var(--text-sm);
  line-height: 1.5;
  padding: 8px 14px;
}

.query-search-btn {
  flex-shrink: 0;
  height: 38px;
  border-radius: var(--radius-lg);
  font-weight: var(--weight-semibold);
  padding: 0 var(--space-5);
}

/* ===== Below: Results + Params ===== */
.search-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ===== Main: Search Results ===== */
.search-main {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5);
  background: var(--color-bg);
}

/* ===== Right: Search Params ===== */
.search-params {
  width: 280px;
  flex-shrink: 0;
  background: var(--color-bg-card);
  border-left: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.param-section {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.param-section-label {
  display: block;
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--color-text-muted);
  text-transform: uppercase;
  margin-bottom: var(--space-2);
}

.param-full-select {
  width: 100%;
}

/* Param rows */
.param-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.param-label {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.param-value {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-weight: var(--weight-medium);
  min-width: 32px;
  text-align: right;
}

/* Image drop zone */
.image-drop-zone {
  border: 2px dashed var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  cursor: pointer;
  transition: all var(--transition-fast);
  min-height: 100px;
  position: relative;
}

.image-drop-zone:hover,
.image-drop-zone.is-dragging {
  border-color: var(--color-primary);
  background: var(--color-primary-subtle);
}

.drop-zone-text {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.drop-zone-preview {
  width: 100%;
  max-height: 120px;
  object-fit: contain;
  border-radius: var(--radius-md);
}

.drop-zone-clear {
  position: absolute;
  top: 4px;
  right: 4px;
}

/* Params collapse (advanced) */
.params-collapse {
  border: none;
  border-bottom: 1px solid var(--color-border);
}

.params-collapse :deep(.el-collapse-item__header) {
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--color-text-muted);
  text-transform: uppercase;
  padding: 0 var(--space-4);
  height: 44px;
  background: transparent;
  border: none;
}

.params-collapse :deep(.el-collapse-item__wrap) {
  background: transparent;
  border: none;
}

.params-collapse :deep(.el-collapse-item__content) {
  padding: 0 var(--space-4) var(--space-4);
}

/* Advanced sections inside collapse */
.advanced-section {
  margin-bottom: var(--space-3);
}

.section-title {
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
  padding-bottom: var(--space-1);
  padding-left: var(--space-2);
  border-bottom: 1px solid var(--color-border);
  border-left: 3px solid var(--color-primary);
}

.adv-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.adv-row .adv-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
  min-width: 60px;
}

.adv-row :deep(.el-slider) {
  flex: 1;
}

/* Results header */
.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
}

.results-header h3 {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  font-family: var(--font-display);
}

.results-meta {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* Rewritten queries */
.rewritten-section {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  padding: var(--space-3);
  background: var(--color-primary-subtle);
  border-radius: var(--radius-md);
}

.rewritten-label {
  font-size: var(--text-sm);
  color: var(--color-primary);
  font-weight: var(--weight-medium);
}

/* LLM Answer */
.llm-answer {
  margin-bottom: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: var(--color-primary-subtle);
  border-radius: var(--radius-lg);
  border-left: 3px solid var(--color-primary);
}

.llm-answer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-3);
  font-weight: var(--weight-semibold);
  font-size: var(--text-sm);
  color: var(--color-primary);
}

.llm-answer-meta {
  display: flex;
  gap: var(--space-3);
}

.llm-answer-model {
  font-weight: var(--weight-normal);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.llm-answer-content {
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--color-text);
}

/* Results list */
.results-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.result-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  transition: border-color var(--transition-fast);
  cursor: default;
}

.result-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-sm);
}

.result-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
}

.result-index {
  width: 20px;
  height: 20px;
  border-radius: var(--radius-full);
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: var(--weight-bold);
  flex-shrink: 0;
}

.result-doc {
  flex: 1;
  font-size: 13px;
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-score {
  font-size: 11px;
  font-weight: var(--weight-bold);
  padding: 1px 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.score-high {
  color: var(--color-success);
  background: var(--color-success-subtle);
}

.score-mid {
  color: var(--color-warning);
  background: var(--color-warning-subtle);
}

.score-low {
  color: var(--color-text-faint);
  background: var(--color-bg-hover);
}

.result-content {
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.result-thumbnail {
  max-width: 200px;
  max-height: 140px;
  border-radius: var(--radius-md);
  object-fit: cover;
  border: 1px solid var(--color-border);
  cursor: pointer;
}

.result-footer {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-1);
  font-size: 11px;
  color: var(--color-text-faint);
}

.result-questions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}

/* ===== Image Grid (multimodal) ===== */
.image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: var(--space-2);
}

.image-card {
  border-radius: var(--radius-lg);
  overflow: hidden;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.image-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.image-card-img {
  position: relative;
  aspect-ratio: 1 / 1;
  overflow: hidden;
  background: var(--color-bg-hover);
}

.image-card-img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.image-card:hover .image-card-img img {
  transform: scale(1.05);
}

.image-card-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.image-card-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: var(--space-3) var(--space-2) var(--space-2);
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  opacity: 0;
  transition: opacity var(--transition-fast);
}

.image-card:hover .image-card-overlay {
  opacity: 1;
}

.image-card-score {
  font-size: var(--text-xs);
  font-weight: var(--weight-bold);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.image-card-score.score-high {
  color: #fff;
  background: rgba(16, 185, 129, 0.85);
}

.image-card-score.score-mid {
  color: #fff;
  background: rgba(245, 158, 11, 0.85);
}

.image-card-score.score-low {
  color: #fff;
  background: rgba(107, 114, 128, 0.7);
}

.image-card-name {
  font-size: var(--text-xs);
  color: #fff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 60%;
}

.image-card-footer {
  padding: var(--space-2) var(--space-3);
}

.image-card-index {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

/* Search empty state (before search) */
.search-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: var(--space-3);
}

.search-empty-title {
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text-muted);
  margin: 0;
}

.search-empty-desc {
  font-size: var(--text-sm);
  color: var(--color-text-faint);
  margin: 0;
}

/* Image preview dialog */
.image-preview-dialog :deep(.el-dialog__body) {
  padding: 0;
}
</style>
