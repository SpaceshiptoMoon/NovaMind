<template>
  <div class="todo-card" :class="{ 'is-ignored': loop.state === 'ignored' }">
    <div class="todo-title-row">
      <span class="todo-kind" :class="`kind-${kind}`">{{ kindLabel }}</span>
      <span class="todo-title" :title="title">{{ title }}</span>
      <span class="todo-impact" :class="`tone-${impact.tone}`">
        {{ impact.count }} {{ impact.unit }}
      </span>
    </div>
    <div v-if="meta" class="todo-meta">{{ meta }}</div>

    <div class="todo-actions">
      <button
        v-for="action in visibleActions"
        :key="action.key"
        type="button"
        class="todo-action"
        :class="{ 'is-primary': action.primary, 'is-danger': action.danger }"
        :disabled="busy"
        @click="emit('action', action.key)"
      >
        {{ action.label }}
      </button>
      <span v-if="busy" class="todo-busy">处理中…</span>
    </div>

    <div v-if="loop.state !== 'none'" class="todo-loop" :class="`loop-${loop.state}`">
      <template v-if="loop.state === 'ignored'">
        已忽略<span v-if="loop.at">（{{ loop.at }}）</span>
        <button type="button" class="todo-undo" @click="emit('action', 'undo-ignore')">撤销</button>
      </template>
      <template v-else>
        {{ loop.text }}<span v-if="loop.at"> · {{ loop.at }}</span>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 运营收件箱待办卡：聚合后的信号 + 内联动作 + 闭环脚注。
 *
 * 三种 kind（gap/review/feedback）共享一套版式；忽略留痕不消失（置灰 +
 * 撤销入口）——飞轮「有借有还」：忽略也是一种处置。
 */
import { computed } from 'vue'

export interface TodoImpact {
  count: number | string
  unit: string
  tone: 'danger' | 'warning' | 'neutral'
}

export interface TodoAction {
  key: string
  label: string
  primary?: boolean
  danger?: boolean
}

export interface TodoLoop {
  state: 'none' | 'converted' | 'passed' | 'failed' | 'ignored' | 'reviewed'
  text?: string
  at?: string
}

const props = defineProps<{
  kind: 'gap' | 'review' | 'feedback' | 'evaluation'
  title: string
  impact: TodoImpact
  meta?: string
  actions: TodoAction[]
  loop?: TodoLoop
  busy?: boolean
}>()

const emit = defineEmits<{ (e: 'action', key: string): void }>()

const kindLabel = computed(
  () =>
    ({ gap: '零命中', review: '复审到期', feedback: '反馈异常', evaluation: '评测归因' })[
      props.kind
    ],
)

const visibleActions = computed(() =>
  props.loop?.state === 'ignored' ? [] : props.actions,
)

const loop = computed(() => props.loop ?? { state: 'none' as const })
</script>

<style scoped>
.todo-card {
  position: relative;
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  transition: border-color var(--transition-fast);
}

.todo-card:hover {
  border-color: var(--color-primary);
}

/* 忽略留痕：置灰不消失 */
.todo-card.is-ignored {
  opacity: 0.55;
}

/* 登记簿墨水左标（与侧栏同语法）：处置中的卡 */
.todo-card:hover::before,
.todo-card.is-busy::before {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--color-primary);
}

.todo-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.todo-kind {
  flex-shrink: 0;
  font-size: var(--text-xs);
  padding: 1px 8px;
  border-radius: var(--radius-full);
  background: var(--color-info-subtle, var(--color-bg-hover));
  color: var(--color-text-secondary);
}

.kind-gap {
  background: var(--color-warning-subtle);
  color: var(--color-warning);
}

.kind-review {
  background: var(--color-warning-subtle);
  color: var(--color-warning);
}

.kind-feedback {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

.kind-evaluation {
  background: var(--color-primary-subtle);
  color: var(--color-primary);
}

.todo-title {
  flex: 1;
  min-width: 0;
  font-size: var(--text-base);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.todo-impact {
  flex-shrink: 0;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-semibold);
}

.tone-danger {
  color: var(--color-danger);
}

.tone-warning {
  color: var(--color-warning);
}

.tone-neutral {
  color: var(--color-text-secondary);
}

.todo-meta {
  margin-top: 2px;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.todo-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-2);
}

.todo-action {
  border: none;
  background: none;
  padding: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: color var(--transition-fast);
}

.todo-action:hover:not(:disabled) {
  color: var(--color-primary);
}

.todo-action.is-primary {
  color: var(--color-primary);
  font-weight: var(--weight-semibold);
}

.todo-action.is-danger {
  color: var(--color-danger);
}

.todo-action:disabled {
  opacity: 0.5;
  cursor: default;
}

.todo-busy {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

.todo-loop {
  margin-top: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--color-border-light);
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

.loop-passed {
  color: var(--color-success);
}

.loop-failed {
  color: var(--color-danger);
}

.todo-undo {
  border: none;
  background: none;
  padding: 0 0 0 var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-primary);
  cursor: pointer;
}
</style>
