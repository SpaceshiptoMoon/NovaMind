<template>
  <div
    class="result-card"
    :class="{ 'is-wiki': isWikiResult(result) }"
    :role="isWikiResult(result) ? 'button' : undefined"
    @click="isWikiResult(result) && emit('open-wiki', result)"
  >
    <div class="result-header">
      <span class="result-index">{{ index + 1 }}</span>
      <el-tag
        v-if="result.chunk_type && result.chunk_type !== 'text'"
        :type="
          result.chunk_type === 'video'
            ? 'primary'
            : result.chunk_type === 'audio'
              ? 'danger'
              : 'warning'
        "
        size="small"
        effect="plain"
        >{{ chunkTypeLabels[result.chunk_type] || result.chunk_type }}</el-tag
      >
      <el-tag v-if="result.content_type === 'table'" type="warning" size="small" effect="plain"
        >表格</el-tag
      >
      <el-tag v-else-if="result.content_type === 'code'" type="info" size="small" effect="plain"
        >代码</el-tag
      >
      <span v-if="isWikiResult(result)" class="wiki-hit-title">
        {{ strMetaOf(result, 'wiki_title') || 'Wiki 条目' }}
      </span>
      <template v-else>
        <span class="result-doc">{{
          fileInfoOf(result).filename || `文档 #${result.document_id}`
        }}</span>
        <span class="result-chunk-pos">分块{{ result.chunk_index + 1 }}</span>
      </template>
      <span class="result-score" :class="getScoreClass(result.score)">
        {{ (result.score * 100).toFixed(1) }}%
      </span>
    </div>
    <!-- 来源行：全局检索展示 空间 / 知识库（空间内检索不重复展示） -->
    <div v-if="showSource && (result.space_name || result.kb_name)" class="result-source">
      <span v-if="result.space_name">{{ result.space_name }}</span>
      <span v-if="result.space_name && result.kb_name" class="result-source-sep">/</span>
      <span v-if="result.kb_name">{{ result.kb_name }}</span>
    </div>
    <div
      ref="contentEl"
      class="result-content"
      :class="{ 'is-expanded': expanded }"
      :data-chunk-id="result.chunk_id"
    >
      <template v-if="segments.length > 1 || segments[0]?.hit">
        <template v-for="(seg, i) in segments" :key="i">
          <mark v-if="seg.hit" class="result-hl">{{ seg.text }}</mark>
          <template v-else>{{ seg.text }}</template>
        </template>
      </template>
      <template v-else>{{ result.content }}</template>
    </div>
    <button
      v-if="truncated"
      type="button"
      class="result-expand-toggle"
      :class="{ 'is-expanded': expanded }"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      {{ expanded ? '收起' : '展开全文' }}
      <el-icon><ArrowDown /></el-icon>
    </button>
    <!-- 视频帧图缩略图：与正文里的 VLM 描述一一对应，点击放大看原图 -->
    <div v-if="frameThumbsOf(result).length" class="result-frames">
      <el-image
        v-for="(url, fi) in frameThumbsOf(result)"
        :key="fi"
        :src="url"
        :preview-src-list="frameThumbsOf(result)"
        :initial-index="fi"
        fit="cover"
        loading="lazy"
        hide-on-click-modal
        class="result-frame-thumb"
      />
    </div>
    <div class="result-footer">
      <!-- wiki 命中：来源是 LLM 综合条目（带加权说明），非原文档分块 -->
      <template v-if="isWikiResult(result)">
        <span class="wiki-hit-badge">Wiki 综合条目 · 检索加权中</span>
        <span class="wiki-hit-open">打开页面</span>
      </template>
      <template v-else>
        <span v-if="numMetaOf(result, 'page') != null">第 {{ numMetaOf(result, 'page') }} 页</span>
        <span v-if="clipRangeText(result)">{{ clipRangeText(result) }}</span>
        <span
          v-if="
            (result.chunk_type === 'audio' || result.chunk_type === 'video') &&
            numMetaOf(result, 'start_time') != null
          "
          class="clip-play-link"
          role="button"
          @click.stop="emit('play', result)"
        >
          ▶ 播放片段
        </span>
        <span v-if="strMetaOf(result, 'speaker_id')" class="speaker-tag"
          >说话人 {{ strMetaOf(result, 'speaker_id') }}</span
        >
      </template>
    </div>
    <!-- 视频：流式 + #t= 媒体片段（有画面）；音频：服务端切片 blob -->
    <video
      v-if="activeClipKey === clipKeyOf(result) && activeClipIsVideo"
      :src="activeClipUrl ?? undefined"
      controls
      autoplay
      class="clip-audio clip-video"
      @error="emit('stop-clip')"
      @ended="emit('stop-clip')"
    ></video>
    <audio
      v-else-if="activeClipKey === clipKeyOf(result)"
      :src="activeClipUrl ?? undefined"
      controls
      autoplay
      class="clip-audio"
      @ended="emit('stop-clip')"
    ></audio>
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
</template>

<script setup lang="ts">
/**
 * 检索结果卡片：空间内检索页与全局检索页共用的单条命中展示。
 *
 * 自含 2 行截断实测（mount / result 变更时量自身 content 节点，真截断才出
 * 展开按钮）与关键词高亮（分段 <mark> 渲染，不走 v-html）。片段播放是父级
 * 单实例状态：本组件只发 play / stop-clip 事件并按 activeClipKey 渲染媒体
 * 元素，避免两张卡同时出声。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { chunkTypeLabels } from '../document'
import type { GlobalSearchResultItem } from '@/api/types'
import { formatDuration } from '@/utils/format'
import { highlightSegments, queryToTerms } from '@/utils/highlight'

/** 卡片入参类型：全局结果（含来源扩展字段）为超集，单库结果结构可赋值 */
type AnyResultItem = GlobalSearchResultItem

const props = withDefaults(
  defineProps<{
    result: AnyResultItem
    /** 序号（1 起展示用，传入 0 起下标） */
    index: number
    /** 查询文本（非空时正文做关键词高亮） */
    query?: string
    /** 显示空间/知识库来源行（全局检索用） */
    showSource?: boolean
    /** 父级单实例播放状态：当前播放片段的 key */
    activeClipKey?: string | null
    /** 父级单实例播放状态：媒体 URL */
    activeClipUrl?: string | null
    /** 父级单实例播放状态：是否视频 */
    activeClipIsVideo?: boolean
  }>(),
  { query: '', showSource: false, activeClipKey: null, activeClipUrl: null, activeClipIsVideo: false },
)

const emit = defineEmits<{
  (e: 'play', result: AnyResultItem): void
  (e: 'stop-clip'): void
  (e: 'open-wiki', result: AnyResultItem): void
}>()

// wiki 命中判断：chunk_type="wiki_page" 由后端 wiki ES 同步写入，
// slug 存在 metadata.wiki_slug（wiki_es_sync.py）；命中卡片可点击直达 wiki 页
function isWikiResult(result: AnyResultItem): boolean {
  return result.chunk_type === 'wiki_page'
}

// ===== chunk 元数据读取 helper：模板侧收敛 as 泛型断言 =====
// prettier 3.8.1 的 Vue 解析器无法处理 mustache 文本里的 `as Record<...>`
// （属性表达式不受影响），断言一律收进 script helper，模板只调函数
function metaOf(result: AnyResultItem): Record<string, unknown> {
  return (result.metadata as Record<string, unknown> | null) ?? {}
}

function fileInfoOf(result: AnyResultItem): Record<string, string> {
  return (result.file_info as Record<string, string> | null) ?? {}
}

function numMetaOf(result: AnyResultItem, key: string): number | null {
  const v = metaOf(result)[key]
  return typeof v === 'number' ? v : null
}

function strMetaOf(result: AnyResultItem, key: string): string {
  const v = metaOf(result)[key]
  return typeof v === 'string' ? v : ''
}

/** 音/视频命中的「起 - 止」展示文本；无起始时间返回 null（footer 不渲染） */
function clipRangeText(result: AnyResultItem): string | null {
  if (result.chunk_type !== 'audio' && result.chunk_type !== 'video') return null
  const start = numMetaOf(result, 'start_time')
  if (start == null) return null
  const end = numMetaOf(result, 'end_time') ?? start + 30
  return `${formatDuration(start)} - ${formatDuration(end)}`
}

// ===== 视频帧图缩略图：后端把 metadata.frame_paths（MinIO 路径）预签名成
// frame_urls（响应层派生字段）；无帧图的 hit 返回空数组不渲染 =====
function frameThumbsOf(result: AnyResultItem): string[] {
  const raw = metaOf(result).frame_urls
  return Array.isArray(raw) ? raw.filter((u): u is string => typeof u === 'string') : []
}

function clipKeyOf(result: AnyResultItem): string {
  return `${result.document_id}:${numMetaOf(result, 'start_time')}`
}

function getScoreClass(score: number): string {
  if (score >= 0.8) return 'score-high'
  if (score >= 0.5) return 'score-mid'
  return 'score-low'
}

// ===== 关键词高亮：查询非空时正文切分段渲染 =====
const segments = computed(() => {
  if (!props.query) return []
  return highlightSegments(props.result.content, queryToTerms(props.query))
})

// ===== 截断实测：量自身 content 节点（scrollHeight > clientHeight 即真截断） =====
const contentEl = ref<HTMLElement | null>(null)
const truncated = ref(false)
const expanded = ref(false)

async function measureTruncation() {
  expanded.value = false
  await nextTick()
  const el = contentEl.value
  truncated.value = !!el && el.scrollHeight > el.clientHeight + 1
}

onMounted(measureTruncation)
watch(() => props.result, measureTruncation)
</script>

<style scoped>
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

/* wiki 命中卡片：主题色左边条 + 主题底色（区别于普通文档分块），可点击 */
.result-card.is-wiki {
  border-left: 3px solid var(--color-primary);
  cursor: pointer;
}

.result-card.is-wiki:hover {
  background: var(--color-primary-muted);
}

.wiki-hit-title {
  flex: 1;
  overflow: hidden;
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wiki-hit-badge {
  padding: 1px 8px;
  border-radius: var(--radius-full);
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  font-size: 11px;
}

.wiki-hit-open {
  margin-left: auto;
  color: var(--color-primary);
  font-size: 11px;
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

/* 来源行：全局检索的 空间/库 归属，弱化为单行小字 */
.result-source {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: var(--space-1);
  font-size: 11px;
  /* muted 档而非 faint：11px 小字须过 4.5:1 对比度 */
  color: var(--color-text-muted);
}

.result-source-sep {
  color: var(--color-text-faint);
}

.result-content {
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text-secondary);
  overflow-wrap: anywhere;
}

/* 默认 2 行截断，展开态不限高 */
.result-content:not(.is-expanded) {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 命中高亮：warning 系底色，与卡片/wiki 的 primary 系拉开 */
.result-hl {
  background: var(--color-warning-subtle);
  color: inherit;
  padding: 0 1px;
  border-radius: 2px;
}

/* 展开/收起按钮：与查询改写面板同族（muted 小字 + 主题色文本 + 120ms 箭头旋转） */
.result-expand-toggle {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  border: none;
  background: none;
  padding: 2px 4px;
  margin-top: 2px;
  font-size: var(--text-xs);
  color: var(--color-primary);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast);
}

.result-expand-toggle:hover {
  background: var(--color-bg-hover);
}

.result-expand-toggle .el-icon {
  font-size: 12px;
  transition: transform var(--transition-fast);
}

.result-expand-toggle.is-expanded .el-icon {
  transform: rotate(180deg);
}

/* 分块位置：header 行内文件名后的中性小标签 */
.result-chunk-pos {
  flex-shrink: 0;
  font-size: 11px;
  /* muted 档而非 faint：11px 小字须过 4.5:1 */
  color: var(--color-text-muted);
  white-space: nowrap;
}

.result-footer {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-1);
  font-size: 11px;
  color: var(--color-text-faint);
}

/* 视频帧图缩略图：16:9 小图横排可换行，点击 el-image 放大看原图 */
.result-frames {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.result-frame-thumb {
  width: 120px;
  height: 68px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
  cursor: zoom-in;
}

.clip-play-link {
  color: var(--color-primary);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}

.clip-play-link:hover {
  text-decoration: underline;
}

.speaker-tag {
  padding: 0 6px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  white-space: nowrap;
}

.clip-audio {
  width: 100%;
  margin-top: var(--space-2);
  height: 36px;
}

/* 视频片段播放器：覆盖 audio 的固定行高，16:9 保持画面比例 */
.clip-video {
  height: auto;
  aspect-ratio: 16 / 9;
  background: var(--color-bg-card-elevated);
  border-radius: var(--radius-md);
}

.result-questions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}
</style>
