<template>
  <div class="global-search-view">
    <div class="gs-inner">
      <!-- 搜索头：大输入框 + 三档预设 + 返回数量 -->
      <section class="gs-head">
        <h1 class="gs-title">知识检索</h1>
        <p class="gs-subtitle">跨空间搜索你有权限的全部知识：语义 / 混合 / AI 问答</p>
        <div class="gs-search-bar">
          <el-input
            ref="inputRef"
            v-model="query"
            size="large"
            placeholder="输入问题，搜索全部知识空间…"
            maxlength="2000"
            clearable
            class="gs-input"
            @keydown.enter.exact.prevent="handleSearch"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button
            type="primary"
            size="large"
            class="gs-search-btn"
            :loading="searching"
            :disabled="!query.trim()"
            @click="handleSearch"
          >
            {{ searching ? '检索中…' : '搜索' }}
          </el-button>
        </div>
        <div class="gs-controls">
          <el-radio-group v-model="presetKey" size="default" @change="handlePresetChange">
            <el-radio-button v-for="p in SEARCH_PRESETS" :key="p.key" :value="p.key">
              {{ p.label }}
            </el-radio-button>
          </el-radio-group>
          <el-select v-model="topK" size="default" class="gs-topk">
            <el-option :value="10" label="10 条" />
            <el-option :value="20" label="20 条" />
            <el-option :value="30" label="30 条" />
          </el-select>
        </div>
      </section>

      <!-- 结果区 -->
      <section class="gs-body">
        <template v-if="searchResults.length > 0">
          <div class="gs-results-header">
            <span class="gs-results-meta">
              共 {{ total }} 条 · {{ elapsedMs }}ms · 覆盖 {{ searchedKbs }} 个知识库
              <el-tooltip
                v-if="skippedKbs.length"
                :content="skippedTooltip"
                placement="bottom"
              >
                <el-tag type="info" size="small" effect="plain">
                  {{ skippedKbs.length }} 个库未参与
                </el-tag>
              </el-tooltip>
            </span>
          </div>

          <!-- AI 回答（生成失败时降级提示，不挡检索结果） -->
          <SearchAnswerPanel
            v-if="llmAnswer"
            :answer="llmAnswer"
            :model="answerModel"
            :elapsed-ms="answerElapsedMs"
          />
          <el-alert
            v-else-if="answerError"
            type="warning"
            :closable="false"
            show-icon
            class="gs-answer-error"
            :title="`AI 回答生成失败：${answerError}`"
          />

          <div class="gs-results-list">
            <SearchResultCard
              v-for="(result, index) in searchResults"
              :key="`${result.kb_id}-${result.chunk_id}`"
              :result="result"
              :index="index"
              :query="lastQuery"
              show-source
              :active-clip-key="playingClipKey"
              :active-clip-url="playingClipUrl"
              :active-clip-is-video="playingIsVideo"
              @play="playClip"
              @stop-clip="stopClip"
              @open-wiki="openWikiResult"
            />
          </div>
        </template>

        <EmptyState
          v-else-if="hasSearched && !searching"
          variant="search"
          title="未找到相关结果"
          description="换个说法，或切换语义 / 混合 / AI 问答再试"
        />

        <div v-else-if="!hasSearched" class="gs-empty">
          <el-icon :size="44" color="var(--color-text-faint)"><Search /></el-icon>
          <p class="gs-empty-title">搜索你有权限的全部空间</p>
          <p class="gs-empty-desc">
            输入问题按 Enter 开始；AI 问答档会基于检索结果生成带来源的回答。
          </p>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 跨空间全局检索页（/home/search）：消费侧一步直达的知识检索入口。
 *
 * 门户 Hero 搜索框与顶栏搜索位的落地页；三档预设（语义/混合/AI 问答）
 * 映射 9 种后端模式（AI 问答 = 混合 + LLM 回答，模型缺省走用户默认），
 * 结果经共享 SearchResultCard 展示（关键词高亮 + 空间/库来源行）。
 * 支持 ?q= 深链自动执行。
 */
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { searchApi } from '@/api/knowledge'
import { SearchAnswerPanel, SearchResultCard } from '@/components/knowledge'
import EmptyState from '@/components/common/EmptyState.vue'
import type {
  GlobalSearchResponse,
  GlobalSearchResultItem,
  GlobalSearchSkippedKb,
} from '@/api/types'
import { SEARCH_PRESETS, getPreset, type SearchPresetKey } from '@/utils/searchModes'
import { documentApi } from '@/api/knowledge'

const route = useRoute()
const router = useRouter()

const query = ref('')
const lastQuery = ref('')
const presetKey = ref<SearchPresetKey>('hybrid')
const topK = ref(10)
const searching = ref(false)
const hasSearched = ref(false)

const searchResults = ref<GlobalSearchResultItem[]>([])
const total = ref(0)
const elapsedMs = ref(0)
const searchedKbs = ref(0)
const skippedKbs = ref<GlobalSearchSkippedKb[]>([])
const llmAnswer = ref<string | null>(null)
const answerModel = ref<string | null>(null)
const answerElapsedMs = ref<number | null>(null)
const answerError = ref<string | null>(null)

const inputRef = ref<{ focus: () => void } | null>(null)

const skippedTooltip = ref('')
function buildSkippedTooltip(items: GlobalSearchSkippedKb[]) {
  const label = (r: string) => (r === 'fan_out_limit' ? '超参与上限' : '检索失败')
  skippedTooltip.value = items
    .slice(0, 6)
    .map((s) => `${s.kb_name}：${label(s.reason)}`)
    .join('；')
}

/** 三档切换：已有结果时立即按新档重跑（AI 档开启 LLM，模型缺省走用户默认配置） */
async function handlePresetChange() {
  await reSearch()
}

async function handleSearch() {
  const q = query.value.trim()
  if (!q) return
  if (searching.value) return

  searching.value = true
  hasSearched.value = true
  const preset = getPreset(presetKey.value)
  stopClip()

  try {
    const data: GlobalSearchResponse = await searchApi.globalSearch({
      query: q,
      search_mode: preset.mode,
      top_k: topK.value,
      llm: preset.llmEnabled ? { enabled: true } : undefined,
    })
    searchResults.value = data.results || []
    total.value = data.total || 0
    elapsedMs.value = data.elapsed_ms || 0
    searchedKbs.value = data.searched_kbs || 0
    skippedKbs.value = data.skipped_kbs || []
    buildSkippedTooltip(skippedKbs.value)
    llmAnswer.value = data.answer || null
    answerModel.value = data.answer_model || null
    answerElapsedMs.value = data.answer_elapsed_ms || null
    answerError.value = data.answer_error || null
    lastQuery.value = q
  } catch (error: unknown) {
    const err = error as { response?: { data?: { error?: { message?: string } } } }
    ElMessage.error(err.response?.data?.error?.message || '检索失败')
    searchResults.value = []
    llmAnswer.value = null
    answerError.value = null
  } finally {
    searching.value = false
  }
}

/** 预设切换后带当前查询立即重跑（尚未检索过则只影响下一次） */
async function reSearch() {
  if (hasSearched.value && query.value.trim()) await handleSearch()
}

// ===== 片段回跳播放（父级单实例；URL 生命周期与空间内检索页同构） =====
const playingClipKey = ref<string | null>(null)
const playingClipUrl = ref<string | null>(null)
const playingIsVideo = ref(false)

function clipKeyOf(result: GlobalSearchResultItem): string {
  const start = (result.metadata as Record<string, unknown> | null)?.start_time
  return `${result.document_id}:${start ?? ''}`
}

async function playClip(result: GlobalSearchResultItem) {
  const meta = (result.metadata as Record<string, unknown> | null) ?? {}
  if (meta.start_time == null) return
  const key = clipKeyOf(result)
  if (playingClipKey.value === key) {
    stopClip()
    return
  }
  const spaceId = result.space_id
  if (!spaceId) return
  const start = Number(meta.start_time)
  const end = Number(meta.end_time ?? start + 30)
  if (result.chunk_type === 'video') {
    if (playingClipUrl.value) window.URL.revokeObjectURL(playingClipUrl.value)
    const base = documentApi.getVideoStreamUrl(spaceId, result.kb_id, result.document_id)
    playingClipUrl.value = `${base}#t=${start},${end}`
    playingIsVideo.value = true
    playingClipKey.value = key
    return
  }
  try {
    const url = await documentApi.getAudioClipBlobUrl(
      spaceId,
      result.kb_id,
      result.document_id,
      start,
      end,
    )
    if (playingClipUrl.value) window.URL.revokeObjectURL(playingClipUrl.value)
    playingClipUrl.value = url
    playingIsVideo.value = false
    playingClipKey.value = key
  } catch {
    ElMessage.error('音频片段获取失败')
  }
}

function stopClip() {
  if (playingClipUrl.value) window.URL.revokeObjectURL(playingClipUrl.value)
  playingClipUrl.value = null
  playingClipKey.value = null
}

/** wiki 命中直达对应空间的 Wiki 页（slug 在 metadata.wiki_slug） */
function openWikiResult(result: GlobalSearchResultItem) {
  const slug = (result.metadata as Record<string, unknown> | null)?.wiki_slug
  if (!slug || !result.space_id) return
  void router.push({
    path: `/home/spaces/${result.space_id}/knowledge-bases/${result.kb_id}/wiki`,
    query: { page: String(slug) },
  })
}

// ===== 深链 ?q= 与同页二次推入（门户/顶栏在已在检索页时改 q） =====
function applyRouteQuery() {
  const raw = route.query.q
  const q = Array.isArray(raw) ? raw[0] : raw
  if (q && q.trim() && q.trim() !== lastQuery.value) {
    query.value = q.trim()
    void handleSearch()
  } else {
    void nextTick(() => inputRef.value?.focus())
  }
}

watch(
  () => route.query.q,
  () => {
    if (route.name === 'GlobalSearch') applyRouteQuery()
  },
)

onMounted(applyRouteQuery)
</script>

<style scoped>
.global-search-view {
  min-height: 100%;
  padding: var(--space-8) var(--space-6) var(--space-10);
  display: flex;
  justify-content: center;
}

.gs-inner {
  width: 100%;
  max-width: 860px;
  display: flex;
  flex-direction: column;
}

/* ===== 搜索头 ===== */
.gs-head {
  margin-bottom: var(--space-6);
}

.gs-title {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin: 0 0 var(--space-1);
}

.gs-subtitle {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin: 0 0 var(--space-5);
}

.gs-search-bar {
  display: flex;
  gap: var(--space-2);
}

.gs-input {
  flex: 1;
}

.gs-search-btn {
  flex-shrink: 0;
  min-width: 96px;
}

.gs-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-top: var(--space-3);
}

.gs-topk {
  width: 96px;
  flex-shrink: 0;
}

/* ===== 结果区 ===== */
.gs-results-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: var(--space-3);
}

.gs-results-meta {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.gs-answer-error {
  margin-bottom: var(--space-4);
}

.gs-results-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

/* 未检索引导 */
.gs-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-16) 0;
  gap: var(--space-3);
}

.gs-empty-title {
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text-muted);
  margin: 0;
}

.gs-empty-desc {
  font-size: var(--text-sm);
  color: var(--color-text-faint);
  margin: 0;
}

@media (max-width: 640px) {
  .global-search-view {
    padding: var(--space-5) var(--space-4);
  }

  .gs-search-bar {
    flex-direction: column;
  }

  .gs-controls {
    flex-wrap: wrap;
  }
}
</style>
