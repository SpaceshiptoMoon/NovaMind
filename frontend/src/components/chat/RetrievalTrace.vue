<template>
  <div v-if="traces?.length" class="retrieval-trace">
    <button class="trace-toggle" @click="expanded = !expanded">
      <span class="trace-label">📎 检索详情</span>
      <span class="trace-summary">{{ summary }}</span>
      <el-icon :size="10" class="toggle-arrow" :class="{ expanded }"><ArrowDown /></el-icon>
    </button>
    <div v-if="expanded" class="trace-detail">
      <div v-for="(t, i) in traces" :key="i" class="trace-step">
        <div v-if="t.type === 'rewrite'" class="trace-item">
          <span class="trace-icon">✏️</span>
          <span class="trace-desc">
            改写：
            <span class="trace-original">"{{ t.original }}"</span>
            → <span class="trace-rewritten">"{{ t.rewritten }}"</span>
            <span class="trace-tag">{{ t.strategy }}</span>
          </span>
        </div>
        <div v-if="t.type === 'search'" class="trace-item">
          <span class="trace-icon">🔍</span>
          <span class="trace-desc">
            检索：<span class="trace-mode">{{ t.mode }}</span>
            <span v-if="t.sources_count"> · {{ t.sources_count }} 条结果</span>
            <span v-if="t.note" class="trace-note">{{ t.note }}</span>
          </span>
        </div>
        <div v-if="t.type === 'grade'" class="trace-item">
          <span class="trace-icon" :class="t.passed ? 'grade-pass' : 'grade-fail'">
            {{ t.passed ? '✅' : '🔄' }}
          </span>
          <span class="trace-desc">
            评分：{{ t.score }}/10
            <span v-if="t.retry"> · 重试 {{ t.retry }}/2</span>
            <span v-if="!t.passed" class="trace-note">未通过，自动重试</span>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'

const props = defineProps<{
  traces?: Record<string, unknown>[]
}>()

const expanded = ref(false)

const summary = computed(() => {
  if (!props.traces?.length) return ''
  const parts: string[] = []
  for (const t of props.traces) {
    if (t.type === 'rewrite') parts.push('改写')
    if (t.type === 'search') parts.push(`检索(${t.sources_count || 0}条)`)
    if (t.type === 'grade') parts.push(t.passed ? '通过' : '重试')
  }
  return parts.join(' → ')
})
</script>

<style scoped>
.retrieval-trace {
  margin: 4px 0;
  font-size: 12px;
}
.trace-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  background: var(--el-fill-color-lighter);
  cursor: pointer;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  transition: all 0.2s;
}
.trace-toggle:hover {
  border-color: var(--el-color-primary-light-5);
  color: var(--el-color-primary);
}
.trace-label { font-weight: 500; }
.trace-summary { color: var(--el-text-color-placeholder); }
.toggle-arrow { transition: transform 0.2s; }
.toggle-arrow.expanded { transform: rotate(180deg); }
.trace-detail {
  margin-top: 4px;
  padding: 6px 10px;
  background: var(--el-fill-color-lighter);
  border-radius: 4px;
}
.trace-step { margin: 3px 0; }
.trace-item { display: flex; align-items: flex-start; gap: 4px; }
.trace-icon { flex-shrink: 0; width: 18px; text-align: center; }
.trace-desc { flex: 1; line-height: 1.5; }
.trace-tag {
  display: inline-block;
  margin-left: 4px;
  padding: 0 4px;
  font-size: 10px;
  background: var(--el-color-primary-light-8);
  border-radius: 2px;
  color: var(--el-color-primary);
}
.trace-mode { font-family: monospace; }
.trace-note { color: var(--el-text-color-placeholder); }
</style>
