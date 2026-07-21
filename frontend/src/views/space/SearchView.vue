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
            :loading="searching"
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

              <!-- 结果卡片列表 -->
              <div class="results-list">
                <div
                  v-for="(result, index) in searchResults"
                  :key="result.chunk_id"
                  class="result-card"
                >
                  <div class="result-header">
                    <span class="result-index">{{ index + 1 }}</span>
                    <el-tag
                      v-if="result.chunk_type && result.chunk_type !== 'text'"
                      :type="result.chunk_type === 'video' ? 'primary' : result.chunk_type === 'audio' ? 'danger' : 'warning'"
                      size="small"
                      effect="plain"
                    >{{ chunkTypeLabels[result.chunk_type] || result.chunk_type }}</el-tag>
                    <span class="result-doc">{{ (result.file_info as Record<string, string>)?.filename || `文档 #${result.document_id}` }}</span>
                    <span class="result-score" :class="getScoreClass(result.score)">
                      {{ (result.score * 100).toFixed(1) }}%
                    </span>
                  </div>
                  <div class="result-content">
                    {{ result.content }}
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
              <el-button @click="handleReset">重置检索</el-button>
            </EmptyState>

            <!-- 未检索时的引导 -->
            <div v-else class="search-empty">
              <el-icon :size="48" color="var(--color-text-faint)"><Search /></el-icon>
              <p class="search-empty-title">输入查询内容开始检索</p>
              <p class="search-empty-desc">在上方输入查询内容并选择知识库，按 Enter 或点击检索按钮开始搜索。</p>
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

            <!-- 检索模式 -->
            <div class="param-section">
              <label class="param-section-label">检索模式</label>
              <el-select v-model="searchForm.search_mode" size="small" class="param-full-select">
                <el-option
                  v-for="mode in searchModes"
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

            <!-- LLM 开关 + 模型选择 -->
            <div class="param-section">
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

            <!-- 高级设置折叠 -->
            <el-collapse v-model="advancedCollapsed" class="params-collapse">
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
                    <el-select v-model="searchForm.qrw_llm_model" placeholder="默认" clearable size="small" style="flex:1">
                      <el-option v-for="m in availableLlmModels" :key="m" :label="m" :value="m" />
                    </el-select>
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
                  <!-- HyDE 策略提示词暂不支持自定义 -->
                </div>

                <el-button size="small" @click="handleReset" style="width:100%">重置默认</el-button>
              </el-collapse-item>
            </el-collapse>
          </aside>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, Document, DataAnalysis } from '@element-plus/icons-vue'
import { knowledgeBaseApi, searchApi } from '@/api/knowledge'
import { KbSidebar, buildKbNavItems } from '@/components/knowledge'
import type { KnowledgeBase, SearchMode, SearchResultItem, SearchResponse } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import { chunkTypeLabels } from '@/components/knowledge'
import { formatDuration } from '@/utils/format'

const route = useRoute()

const spaceId = computed(() => Number(route.params.id))
const currentKbId = computed(() => {
  const raw = route.query.kbId
  return Array.isArray(raw) ? (raw[0] || '') : (raw || '')
})

const kbNavItems = computed(() =>
  buildKbNavItems({
    spaceId: spaceId.value,
    kbId: currentKbId.value,
    currentRouteName: route.name,
    icons: {
      document: Document,
      list: DataAnalysis,
      search: Search,
      evaluation: DataAnalysis,
    },
  })
)

const searching = ref(false)
const hasSearched = ref(false)
const advancedCollapsed = ref<string[]>([])
const knowledgeBases = ref<KnowledgeBase[]>([])
const searchModes = ref<SearchMode[]>([])
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
  qrw_sub_query_count: 3,
  qrw_sub_query_merge_mode: 'rrf' as 'rrf' | 'score',
  qrw_llm_model: '',
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
  } catch (e) {
    console.error('获取检索模式失败:', e)
    ElMessage.error('获取检索模式失败，请检查知识库状态')
  }

  try {
    const config = await searchApi.getModelConfig(spaceId.value, searchForm.kb_id)
    availableLlmModels.value = config.available_llm_models || []
    availableRerankModels.value = config.available_rerank_models || []
    defaultLlmModel.value = config.default_llm_model || ''
    defaultRerankModel.value = config.default_rerank_model || ''
  } catch (e) {
    console.error('获取模型配置失败:', e)
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

  const queryRewrite = searchForm.qrw_strategy
    ? {
        strategy: searchForm.qrw_strategy as 'hyde' | 'sub_query',
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
    const data: SearchResponse = await searchApi.search(spaceId.value, searchForm.kb_id, {
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
      use_cache: searchForm.use_cache,
      fallback_on_unavailable: searchForm.fallback_on_unavailable,
    })

    searchResults.value = data.results || []
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

onMounted(() => {
  fetchKnowledgeBases()
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
</style>