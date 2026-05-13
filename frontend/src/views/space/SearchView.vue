<template>
  <div class="search-view">
    <!-- 子导航标签 -->
    <div class="page-nav">
      <div class="nav-tabs">
        <router-link
          :to="`/home/spaces/${spaceId}/knowledge-bases/${currentKbId}/documents`"
          class="nav-tab"
        >
          文档管理
        </router-link>
        <router-link
          :to="`/home/spaces/${spaceId}/search?kbId=${currentKbId}`"
          class="nav-tab active"
        >
          检索
        </router-link>
        <router-link
          :to="`/home/spaces/${spaceId}/knowledge-bases/${currentKbId}/evaluation`"
          class="nav-tab"
        >
          评测
        </router-link>
      </div>
    </div>

    <!-- 搜索区域 -->
    <div class="search-hero">
      <div class="search-row">
        <el-select
          v-model="searchForm.kb_id"
          placeholder="选择知识库"
          class="kb-selector"
          @change="handleKbChange"
        >
          <el-option
            v-for="kb in knowledgeBases"
            :key="kb.id"
            :label="kb.name"
            :value="kb.id"
          />
        </el-select>
        <el-input
          v-model="searchForm.query"
          placeholder="输入查询内容，按 Enter 检索..."
          class="search-input"
          maxlength="2000"
          @keyup.enter="handleSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button
          type="primary"
          :loading="searching"
          :disabled="!searchForm.kb_id || !searchForm.query"
          @click="handleSearch"
          class="search-btn"
        >
          检索
        </el-button>
      </div>
      <div class="search-meta-row">
        <el-select
          v-model="searchForm.search_mode"
          placeholder="检索模式"
          size="small"
          style="width: 160px"
        >
          <el-option
            v-for="mode in searchModes"
            :key="mode.mode"
            :label="mode.label"
            :value="mode.mode"
          />
        </el-select>
        <span class="meta-item">Top {{ searchForm.top_k }}</span>
        <el-switch
          v-model="searchForm.llm_enabled"
          size="small"
          active-text="LLM"
          inactive-text=""
        />
        <button class="advanced-toggle" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? '收起' : '高级设置' }}
          <el-icon :class="{ rotated: showAdvanced }"><ArrowDown /></el-icon>
        </button>
      </div>
    </div>

    <!-- 高级设置（折叠） -->
    <div v-if="showAdvanced" class="advanced-panel">
      <el-form :model="searchForm" label-width="100px" size="small">
        <!-- 基础参数 -->
        <div class="advanced-section">
          <div class="section-title">检索参数</div>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="向量权重">
                <el-slider v-model="searchForm.vector_weight" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="BM25权重">
                <el-slider v-model="searchForm.bm25_weight" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="返回数量">
                <el-input-number v-model="searchForm.top_k" :min="1" :max="100" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="内容权重">
                <el-slider v-model="searchForm.content_weight" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="问题权重">
                <el-slider v-model="searchForm.question_weight" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="分数阈值">
                <el-slider v-model="searchForm.score_threshold" :min="0" :max="1" :step="0.05" show-input :show-input-controls="false" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="RRF 融合参数">
                <el-input-number v-model="searchForm.rrf_k" :min="1" :max="200" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="使用缓存">
                <el-switch v-model="searchForm.use_cache" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="模式降级">
                <el-switch v-model="searchForm.fallback_on_unavailable" active-text="自动" inactive-text="关闭" />
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- Rerank -->
        <div class="advanced-section">
          <div class="section-title">重排序配置</div>
          <el-row :gutter="16">
            <el-col :span="6">
              <el-form-item label="启用 Rerank">
                <el-switch v-model="searchForm.rerank_enabled" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="Rerank 数量">
                <el-input-number v-model="searchForm.rerank_top_k" :min="1" :max="20" :disabled="!searchForm.rerank_enabled" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="Rerank 模型">
                <el-select v-model="searchForm.rerank_model" :disabled="!searchForm.rerank_enabled" placeholder="系统默认" clearable style="width: 100%">
                  <el-option v-for="m in availableRerankModels" :key="m" :label="m" :value="m" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- LLM -->
        <div class="advanced-section">
          <div class="section-title">LLM 配置</div>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="LLM 模型">
                <el-select v-model="searchForm.llm_model" :disabled="!searchForm.llm_enabled" placeholder="系统默认" clearable style="width: 100%">
                  <el-option v-for="m in availableLlmModels" :key="m" :label="m" :value="m" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="生成温度">
                <el-slider v-model="searchForm.llm_temperature" :min="0" :max="2" :step="0.1" :disabled="!searchForm.llm_enabled" show-input :show-input-controls="false" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="Top P">
                <el-slider v-model="searchForm.llm_top_p" :min="0" :max="1" :step="0.1" :disabled="!searchForm.llm_enabled" show-input :show-input-controls="false" />
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- 查询改写 -->
        <div class="advanced-section">
          <div class="section-title">查询改写</div>
          <el-row :gutter="16">
            <el-col :span="6">
              <el-form-item label="改写策略">
                <el-select v-model="searchForm.qrw_strategy" style="width: 100%">
                  <el-option label="不启用" value="" />
                  <el-option label="HyDE 假设性文档" value="hyde" />
                  <el-option label="子问题拆分" value="sub_query" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="改写模型">
                <el-input v-model="searchForm.qrw_llm_model" :disabled="!searchForm.qrw_strategy" placeholder="系统默认" />
              </el-form-item>
            </el-col>
            <template v-if="searchForm.qrw_strategy === 'sub_query'">
              <el-col :span="6">
                <el-form-item label="子问题数量">
                  <el-input-number v-model="searchForm.qrw_sub_query_count" :min="2" :max="5" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="合并方式">
                  <el-select v-model="searchForm.qrw_sub_query_merge_mode" style="width: 100%">
                    <el-option label="加权融合 (RRF)" value="rrf" />
                    <el-option label="分数取最大" value="score" />
                  </el-select>
                </el-form-item>
              </el-col>
            </template>
          </el-row>
          <el-row v-if="searchForm.qrw_strategy === 'hyde'" :gutter="16">
            <el-col :span="12">
              <el-form-item label="HyDE 提示词">
                <el-input v-model="searchForm.qrw_hyde_prompt" type="textarea" :rows="2" maxlength="2000" placeholder="为空使用系统默认提示词" />
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <div class="advanced-footer">
          <el-button size="small" @click="handleReset">重置默认</el-button>
        </div>
      </el-form>
    </div>

    <!-- 检索结果 -->
    <div v-if="searchResults.length > 0" class="results-section">
      <div class="results-header">
        <h3>检索结果</h3>
        <span class="results-meta">
          共 {{ totalResults }} 条结果，耗时 {{ elapsedMs }}ms
          <el-tag v-if="cached" type="success" size="small">缓存</el-tag>
          <el-tag v-if="modeFallback" type="warning" size="small">模式降级: {{ originalMode }}</el-tag>
        </span>
      </div>

      <!-- 查询改写结果 -->
      <div v-if="rewrittenQueries?.length" class="rewritten-section">
        <span class="rewritten-label">查询改写:</span>
        <el-tag v-for="q in rewrittenQueries" :key="q" size="small" type="primary">
          {{ q }}
        </el-tag>
      </div>

      <!-- 大模型回答 -->
      <div v-if="llmAnswer" class="llm-answer">
        <div class="llm-answer-header">
          <span>AI 回答</span>
          <span class="llm-answer-meta">
            <span v-if="answerModel" class="llm-answer-model">{{ answerModel }}</span>
            <span v-if="answerElapsedMs" class="llm-answer-model">{{ answerElapsedMs }}ms</span>
          </span>
        </div>
        <div class="llm-answer-content">{{ llmAnswer }}</div>
      </div>

      <div class="results-list">
        <div
          v-for="(result, index) in searchResults"
          :key="result.chunk_id"
          class="result-card"
        >
          <div class="result-header">
            <span class="result-index">{{ index + 1 }}</span>
            <span class="result-score" :class="getScoreClass(result.score)">
              {{ (result.score * 100).toFixed(1) }}%
            </span>
            <span class="result-doc">{{ (result.file_info as Record<string, string>)?.filename || `文档 #${result.document_id}` }}</span>
          </div>
          <div class="result-content">
            {{ result.content }}
          </div>
          <div class="result-footer">
            <span v-if="(result.metadata as Record<string, unknown>)?.page" class="result-page">
              第 {{ (result.metadata as Record<string, unknown>).page }} 页
            </span>
            <span class="result-chunk">分块 #{{ result.chunk_index + 1 }}</span>
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
    </div>

    <!-- 空状态 -->
    <EmptyState
      v-else-if="hasSearched"
      variant="search"
      title="未找到相关结果"
      description="尝试调整查询内容或检索模式"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, ArrowDown } from '@element-plus/icons-vue'
import { searchApi } from '@/api/search'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import type { KnowledgeBase, SearchMode, SearchResultItem } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'

const route = useRoute()

const spaceId = computed(() => Number(route.params.id))
const currentKbId = computed(() => route.query.kbId || '')

const searching = ref(false)
const hasSearched = ref(false)
const showAdvanced = ref(false)
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
    const data = await searchApi.search(spaceId.value, searchForm.kb_id, {
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
.search-view {
  padding-top: var(--space-2);
}

.page-nav {
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

/* ===== Search Hero ===== */

.search-hero {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  padding: var(--space-5);
  margin-bottom: var(--space-4);
}

.search-row {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.kb-selector {
  width: 180px;
  flex-shrink: 0;
}

.search-input {
  flex: 1;
}

.search-input :deep(.el-input__wrapper) {
  height: 44px;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xs);
}

.search-btn {
  flex-shrink: 0;
  height: 44px;
  padding: 0 var(--space-6);
  border-radius: var(--radius-lg);
  font-weight: var(--weight-medium);
}

.search-meta-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.meta-item {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.advanced-toggle {
  margin-left: auto;
  background: none;
  border: none;
  cursor: pointer;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
}

.advanced-toggle:hover {
  color: var(--color-primary);
  background: var(--color-primary-muted);
}

.advanced-toggle .el-icon {
  transition: transform var(--transition-base);
}

.advanced-toggle .el-icon.rotated {
  transform: rotate(180deg);
}

/* ===== Advanced Panel ===== */

.advanced-panel {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  padding: var(--space-5);
  margin-bottom: var(--space-4);
  animation: slideDown 0.2s ease;
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.advanced-section {
  margin-bottom: var(--space-4);
}

.section-title {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-3);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--color-border-light);
}

.advanced-footer {
  display: flex;
  justify-content: flex-end;
}

/* ===== Results ===== */

.results-section {
  margin-top: var(--space-5);
}

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

.results-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.result-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  transition: all var(--transition-fast);
  cursor: default;
}

.result-card:hover {
  border-color: var(--color-border);
  box-shadow: var(--shadow-xs);
}

.result-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.result-index {
  width: 24px;
  height: 24px;
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

.result-score {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
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
  color: var(--color-danger);
  background: var(--color-danger-subtle);
}

.result-doc {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-left: auto;
}

.result-content {
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text);
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.result-footer {
  display: flex;
  gap: var(--space-4);
  margin-top: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

.result-questions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border-light);
}

/* ===== Rewritten ===== */

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

/* ===== LLM Answer ===== */

.llm-answer {
  margin-bottom: var(--space-4);
  padding: var(--space-4);
  background: linear-gradient(135deg, var(--color-primary-subtle), rgba(37, 99, 235, 0.03));
  border-radius: var(--radius-lg);
  border-left: 4px solid var(--color-primary);
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
  line-height: 1.8;
  color: var(--color-text);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
