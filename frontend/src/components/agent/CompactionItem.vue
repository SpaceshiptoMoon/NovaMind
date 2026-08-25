<template>
  <div class="compaction-item">
    <button class="compaction-row" @click="$emit('toggle')">
      <span class="compaction-leading" aria-hidden>
        <span class="compaction-context-icon">⇲</span>
        <span class="compaction-disclosure" :class="{ expanded }">▾</span>
      </span>
      <span class="compaction-title">上下文已压缩</span>
      <span class="compaction-sep" aria-hidden />
      <span class="compaction-summary">
        已压缩 {{ data?.summarized_count ?? 0 }} 条消息<template v-if="ratioPercent != null">
          · 节省 {{ ratioPercent }}%</template>
      </span>
    </button>
    <div v-if="expanded && data?.summary" class="compaction-body">
      <MarkdownRenderer :content="data.summary" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentCompactionData } from '@/api/types'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'

const props = defineProps<{
  data?: AgentCompactionData | null
  expanded: boolean
}>()
defineEmits<{ toggle: [] }>()

// compression_ratio = 压缩后/压缩前，节省比例 = 1 - ratio
const ratioPercent = computed(() => {
  const r = props.data?.compression_ratio
  if (r == null) return null
  const saved = Math.round((1 - r) * 100)
  return saved > 0 ? saved : 0
})
</script>

<style scoped>
.compaction-item {
  margin: var(--space-2) 0;
}

.compaction-row {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  width: fit-content;
  max-width: 100%;
  padding: 4px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: var(--color-bg-card-elevated);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.compaction-row:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-text-secondary);
}

.compaction-leading {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.compaction-context-icon {
  color: var(--color-info);
  font-size: 12px;
}

.compaction-disclosure {
  transition: transform var(--transition-fast);
  font-size: 10px;
}

.compaction-disclosure.expanded {
  transform: rotate(180deg);
}

.compaction-title {
  font-weight: var(--weight-medium);
  color: var(--color-text-secondary);
}

.compaction-sep {
  width: 1px;
  height: 12px;
  background: var(--color-border-light);
}

.compaction-summary {
  color: var(--color-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.compaction-body {
  margin-top: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card-elevated);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  max-height: 320px;
  overflow-y: auto;
}

.compaction-body :deep(p:last-child) {
  margin-bottom: 0;
}
</style>