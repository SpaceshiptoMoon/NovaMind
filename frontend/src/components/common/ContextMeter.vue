<template>
  <span class="ctx-meter" ref="rootRef">
    <button
      type="button"
      class="ctx-trigger"
      :class="levelClass"
      :title="`上下文已用 ${percent}%（近似）`"
      @click="toggle"
    >
      <svg viewBox="0 0 14 14" width="14" height="14" aria-hidden>
        <circle class="ctx-track" cx="7" cy="7" r="5.5" />
        <circle
          class="ctx-fill"
          cx="7"
          cy="7"
          r="5.5"
          :stroke-dasharray="`${(circ * percent) / 100} ${circ}`"
          transform="rotate(-90 7 7)"
        />
      </svg>
      <span class="ctx-pct">{{ percent }}%</span>
    </button>
    <div v-if="open" class="ctx-panel" role="dialog">
      <div class="ctx-head">
        上下文已用 {{ percent }}% · ~{{ fmt(used) }} / {{ fmt(window) }}
      </div>
      <div class="ctx-bar">
        <span class="ctx-seg seg-system" :style="{ width: segWidth('system') }" />
        <span class="ctx-seg seg-tools" :style="{ width: segWidth('tools') }" />
        <span class="ctx-seg seg-messages" :style="{ width: segWidth('messages') }" />
      </div>
      <div class="ctx-rows">
        <div class="ctx-row">
          <span class="ctx-swatch sw-system" aria-hidden />system
          <b>~{{ fmt(breakdown?.system_tokens) }}</b>
        </div>
        <div class="ctx-row">
          <span class="ctx-swatch sw-tools" aria-hidden />tools
          <b>~{{ fmt(breakdown?.tools_tokens) }}</b>
        </div>
        <div class="ctx-row">
          <span class="ctx-swatch sw-messages" aria-hidden />messages
          <b>~{{ fmt(breakdown?.messages_tokens) }}</b>
        </div>
      </div>
      <div class="ctx-hint">tiktoken 近似估算</div>
    </div>
  </span>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { AgentContextUsageData } from '@/api/types'

const props = defineProps<{
  used: number
  window: number
  breakdown?: AgentContextUsageData | null
}>()

const RADIUS = 5.5
const circ = 2 * Math.PI * RADIUS

const open = ref(false)
const rootRef = ref<HTMLElement>()

const percent = computed(() => {
  if (!props.window || props.window <= 0) return 0
  const p = Math.round((props.used / props.window) * 100)
  return p > 100 ? 100 : p
})

const levelClass = computed(() => {
  const p = percent.value
  if (p >= 85) return 'lvl-danger'
  if (p >= 60) return 'lvl-warning'
  return 'lvl-ok'
})

function segWidth(key: 'system' | 'tools' | 'messages'): string {
  const b = props.breakdown
  if (!b) return '0%'
  const total = (b.system_tokens || 0) + (b.tools_tokens || 0) + (b.messages_tokens || 0)
  if (total <= 0) return '0%'
  const val = b[`${key}_tokens`] || 0
  return `${(percent.value * val) / total}%`
}

function fmt(n: number | null | undefined): string {
  if (n == null) return '0'
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

function toggle() {
  open.value = !open.value
}

// outside click / escape 关闭
function onPointerDown(e: PointerEvent) {
  if (rootRef.value?.contains(e.target as Node)) return
  open.value = false
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') open.value = false
}
watch(open, (o) => {
  if (o) {
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKey)
  } else {
    document.removeEventListener('pointerdown', onPointerDown)
    document.removeEventListener('keydown', onKey)
  }
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerDown)
  document.removeEventListener('keydown', onKey)
})
</script>

<style scoped>
.ctx-meter {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.ctx-trigger {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px 3px 5px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.ctx-trigger:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
}

.ctx-track {
  fill: none;
  stroke: var(--color-border-light);
  stroke-width: 2;
}

.ctx-fill {
  fill: none;
  stroke: var(--color-text-muted);
  stroke-width: 2;
  transition: stroke 0.2s;
}

.ctx-trigger.lvl-ok .ctx-fill {
  stroke: var(--color-success);
}
.ctx-trigger.lvl-warning .ctx-fill {
  stroke: var(--color-warning);
}
.ctx-trigger.lvl-danger .ctx-fill {
  stroke: var(--color-danger);
}

.ctx-pct {
  font-variant-numeric: tabular-nums;
}

.ctx-panel {
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  z-index: 10;
  min-width: 220px;
  padding: var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-md);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.ctx-head {
  margin-bottom: var(--space-2);
  color: var(--color-text);
  font-weight: var(--weight-medium);
}

.ctx-bar {
  display: flex;
  height: 6px;
  border-radius: 3px;
  overflow: hidden;
  background: var(--color-bg-hover);
  margin-bottom: var(--space-2);
}

.ctx-seg {
  display: block;
  min-width: 0;
  height: 100%;
}

.seg-system {
  background: #6366f1;
}
.seg-tools {
  background: #14b8a6;
}
.seg-messages {
  background: #f59e0b;
}

.ctx-rows {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ctx-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ctx-row b {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  color: var(--color-text);
}

.ctx-swatch {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
}

.sw-system {
  background: #6366f1;
}
.sw-tools {
  background: #14b8a6;
}
.sw-messages {
  background: #f59e0b;
}

.ctx-hint {
  margin-top: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--color-border-light);
  color: var(--color-text-faint);
  font-size: 10px;
}
</style>