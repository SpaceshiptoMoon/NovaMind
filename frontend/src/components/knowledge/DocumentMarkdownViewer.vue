<template>
  <div v-if="loading" class="doc-md-viewer loading">
    <el-skeleton :rows="8" animated />
  </div>
  <div v-else-if="error" class="doc-md-viewer error">
    <el-empty :description="error" :image-size="80" />
  </div>
  <div v-else-if="!markdown" class="doc-md-viewer empty">
    <el-empty description="文档尚未解析，暂无内容" :image-size="80" />
  </div>
  <div v-else class="doc-md-viewer" ref="viewerRef">
    <MarkdownRenderer :content="annotatedMarkdown" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import type { Chunk } from '@/api/types'

const props = defineProps<{
  markdown: string
  chunks: Chunk[]
  loading?: boolean
  error?: string
  hoveredChunkIndex?: number | null
}>()

const viewerRef = ref<HTMLElement | null>(null)

/**
 * 在 Markdown 全文中定位每个 chunk 的文本范围。
 * 由于当前 ES chunk 没有填充 char_start/char_end，
 * 使用按顺序的子串搜索来定位 chunk 边界。
 */
interface ChunkRange {
  chunkIndex: number
  start: number
  end: number
}

const chunkRanges = computed<ChunkRange[]>(() => {
  if (!props.markdown || !props.chunks.length) return []

  const ranges: ChunkRange[] = []
  let searchFrom = 0

  for (const chunk of props.chunks) {
    const content = chunk.content || ''
    if (!content) {
      ranges.push({ chunkIndex: chunk.chunk_index, start: -1, end: -1 })
      continue
    }

    // 使用 chunk 内容的前 60 个字符作为搜索锚点，避免过长的子串匹配
    const anchor = content.substring(0, 60)
    const pos = props.markdown.indexOf(anchor, searchFrom)

    if (pos >= 0) {
      // 尝试找到 chunk 完整内容在 markdown 中的结束位置
      const endPos = pos + Math.min(content.length, props.markdown.length - pos)
      ranges.push({ chunkIndex: chunk.chunk_index, start: pos, end: endPos })
      searchFrom = endPos
    } else {
      ranges.push({ chunkIndex: chunk.chunk_index, start: -1, end: -1 })
    }
  }

  return ranges
})

/** 在 Markdown 文本中插入 chunk 边界标记 */
const annotatedMarkdown = computed(() => {
  if (!props.markdown || !chunkRanges.value.length) return props.markdown

  // 按位置逆序排列，从后往前插入标记以避免位置偏移
  const sorted = [...chunkRanges.value]
    .filter(r => r.start >= 0 && r.end > r.start)
    .sort((a, b) => b.start - a.start)

  let text = props.markdown
  for (const range of sorted) {
    const endMarker = `\n<!-- chunk-end:${range.chunkIndex} -->\n`
    const startMarker = `\n<!-- chunk-start:${range.chunkIndex} -->\n`
    text = text.slice(0, range.end) + endMarker + text.slice(range.end)
    text = text.slice(0, range.start) + startMarker + text.slice(range.start)
  }

  return text
})

/** 滚动到指定 chunk 位置 */
function scrollToChunk(chunkIndex: number) {
  if (!viewerRef.value) return
  const startMarker = viewerRef.value.querySelector(`[data-chunk-index="${chunkIndex}"]`)
  if (startMarker) {
    startMarker.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

/** 高亮指定 chunk */
watch(() => props.hoveredChunkIndex, (newIdx) => {
  if (!viewerRef.value) return

  // 清除所有高亮
  viewerRef.value.querySelectorAll('.chunk-highlight').forEach(el => {
    el.classList.remove('chunk-highlight')
  })

  // 设置新高亮
  if (newIdx != null) {
    const chunkEl = viewerRef.value.querySelectorAll(`[data-chunk-index="${newIdx}"]`)
    chunkEl.forEach(el => el.classList.add('chunk-highlight'))
  }
})

defineExpose({ scrollToChunk })
</script>

<style scoped>
.doc-md-viewer {
  padding: var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  min-height: 200px;
}

.doc-md-viewer.loading,
.doc-md-viewer.error,
.doc-md-viewer.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 300px;
}

:deep(.chunk-highlight) {
  background: rgba(99, 102, 241, 0.1);
  border-left: 3px solid var(--color-primary);
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast);
}
</style>