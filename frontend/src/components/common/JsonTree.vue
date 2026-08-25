<template>
  <!-- 自递归可折叠 JSON 树节点。对象/数组可折叠，基本类型按类型着色。 -->
  <div class="json-tree-node">
    <!-- 基本类型 / null / undefined -->
    <span v-if="!isObject" class="jt-leaf">
      <span class="jt-value" :class="leafType">{{ formatLeaf(data) }}</span>
    </span>

    <!-- 对象 / 数组 -->
    <template v-else>
      <button class="jt-toggle" @click="toggle">
        <span class="jt-chevron" :class="{ expanded }">▶</span>
        <span class="jt-bracket">{{ opener }}</span>
        <span v-if="!expanded" class="jt-summary">{{ collapsedSummary }}</span>
        <span v-if="!expanded" class="jt-bracket">{{ closer }}</span>
      </button>
      <div v-show="expanded" class="jt-children">
        <div v-for="([k, v], i) in entries" :key="k + '-' + i" class="jt-child">
          <span class="jt-key">{{ Array.isArray(data) ? k : `"${k}"` }}</span>
          <span class="jt-colon">:</span>
          <JsonTree :data="v" :depth="depth + 1" :default-expanded="defaultExpanded" />
        </div>
        <span class="jt-bracket">{{ closer }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

// 自递归组件名（Vue 3 SFC 自引用需要显式 name）
defineOptions({ name: 'JsonTree' })

const props = withDefaults(
  defineProps<{
    data: unknown
    depth?: number
    defaultExpanded?: number
  }>(),
  { depth: 0, defaultExpanded: 1 },
)

// depth < defaultExpanded 时默认展开
const expanded = ref(props.depth < props.defaultExpanded)
function toggle() {
  expanded.value = !expanded.value
}

const isObject = computed(() => props.data !== null && typeof props.data === 'object')

const entries = computed<[string, unknown][]>(() => {
  if (Array.isArray(props.data)) {
    return props.data.map((v, i) => [String(i), v] as [string, unknown])
  }
  if (props.data && typeof props.data === 'object') {
    return Object.entries(props.data as Record<string, unknown>)
  }
  return []
})

const opener = computed(() => (Array.isArray(props.data) ? '[' : '{'))
const closer = computed(() => (Array.isArray(props.data) ? ']' : '}'))

// 折叠态摘要：{a: 1, b: 2} → "…"，数组 → "[3]"
const collapsedSummary = computed(() => {
  const n = entries.value.length
  if (n === 0) return ''
  return Array.isArray(props.data) ? `${n}` : `…${n}`
})

const leafType = computed(() => {
  if (props.data === null) return 'jt-null'
  if (props.data === undefined) return 'jt-null'
  const t = typeof props.data
  if (t === 'string') return 'jt-string'
  if (t === 'number') return 'jt-number'
  if (t === 'boolean') return 'jt-boolean'
  return 'jt-other'
})

function formatLeaf(v: unknown): string {
  if (v === null) return 'null'
  if (v === undefined) return 'undefined'
  if (typeof v === 'string') return JSON.stringify(v)
  return String(v)
}
</script>

<style scoped>
.json-tree-node {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-secondary);
}

.jt-leaf {
  display: inline;
}

.jt-value {
  white-space: pre-wrap;
  word-break: break-word;
}
.jt-value.jt-string {
  color: #16a34a;
}
.jt-value.jt-number {
  color: #2563eb;
}
.jt-value.jt-boolean {
  color: #9333ea;
}
.jt-value.jt-null {
  color: var(--color-text-muted);
  font-style: italic;
}
.jt-value.jt-other {
  color: var(--color-text);
}

.jt-toggle {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  border: none;
  background: transparent;
  padding: 0;
  cursor: pointer;
  color: inherit;
  font: inherit;
}

.jt-chevron {
  display: inline-block;
  font-size: 9px;
  color: var(--color-text-muted);
  transition: transform var(--transition-fast);
  transform: rotate(0deg);
}
.jt-chevron.expanded {
  transform: rotate(90deg);
}

.jt-bracket {
  color: var(--color-text-muted);
}

.jt-summary {
  color: var(--color-text-faint, var(--color-text-muted));
  font-style: italic;
  margin: 0 2px;
}

.jt-children {
  padding-left: 16px;
  border-left: 1px solid var(--color-border-light);
  margin-left: 4px;
}

.jt-child {
  display: flex;
  align-items: baseline;
  gap: 4px;
  flex-wrap: wrap;
}

.jt-key {
  color: #b45309;
  flex-shrink: 0;
}

.jt-colon {
  color: var(--color-text-muted);
  flex-shrink: 0;
}
</style>