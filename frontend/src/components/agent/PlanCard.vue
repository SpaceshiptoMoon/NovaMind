<template>
  <div class="plan-card">
    <button class="plan-card-row" @click="$emit('toggle')">
      <span class="plan-card-leading" aria-hidden>
        <span class="plan-card-icon">☰</span>
        <span class="plan-card-disclosure" :class="{ expanded }">▾</span>
      </span>
      <span class="plan-card-title">{{ plan.title || '执行计划' }}</span>
      <span class="plan-card-sep" aria-hidden />
      <span class="plan-card-progress">{{ progressLabel }}</span>
      <el-tag :type="statusType" size="small" class="plan-card-tag">{{ statusText }}</el-tag>
    </button>
    <div v-if="expanded" class="plan-card-body">
      <ol class="plan-card-steps">
        <li v-for="(step, i) in plan.steps" :key="i" class="plan-card-step">
          <span class="plan-step-glyph" :class="`glyph--${glyphKind(i)}`">{{ glyph(i) }}</span>
          <span class="plan-step-text">{{ step }}</span>
        </li>
      </ol>
      <!-- 中断说明保留在卡内（用户需要知道计划没走完）；正常完成时不渲染总结——
         最终答案与计划卡是同一段文本，只渲染在下方 final-answer，避免重复 -->
      <div v-if="plan.interrupted" class="plan-card-interrupted">
        计划被中断，最终回复基于已完成部分作答。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Plan-and-Execute 计划卡：标题 + 进度 + 状态 tag 胶囊行，展开看步骤清单。
 * statuses 缺失（历史数据无终态持久化）统一按已完成 [✓] 兜底，与轨迹视图口径一致。
 * 不渲染 summary：最终答案由下方 final-answer 承载，计划卡只负责计划本身。
 */
import { computed } from 'vue'

const props = defineProps<{
  plan: {
    title?: string
    steps: string[]
    statuses?: string[]
    summary?: string
    interrupted?: boolean
  }
  expanded: boolean
}>()

defineEmits<{ toggle: [] }>()

/** 状态判定统一口径（与 TrajectoryList.planStatusGlyph / TrajectoryInspector.planGlyph 互指）：
 * statuses 整体缺失 → 历史数据视为已完成；单步缺失 → 兜底 completed */
function statusAt(i: number): string {
  if (!props.plan.statuses) return 'completed'
  return props.plan.statuses[i] ?? 'completed'
}

function glyph(i: number): string {
  const s = statusAt(i)
  if (s === 'completed') return '[✓]'
  if (s === 'in_progress') return '[→]'
  if (s === 'blocked') return '[!]'
  return '[ ]'
}

function glyphKind(i: number): string {
  return statusAt(i)
}

const completedCount = computed(
  () => props.plan.steps.filter((_, i) => statusAt(i) === 'completed').length,
)

const progressLabel = computed(() =>
  `${completedCount.value}/${props.plan.steps.length} 步`,
)

const statusText = computed(() => {
  if (props.plan.interrupted) return '已中断'
  if (completedCount.value === props.plan.steps.length && props.plan.steps.length > 0)
    return '已完成'
  return '执行中'
})

const statusType = computed(() => {
  if (props.plan.interrupted) return 'warning'
  if (completedCount.value === props.plan.steps.length && props.plan.steps.length > 0)
    return 'success'
  return 'primary'
})
</script>

<style scoped>
.plan-card {
  margin: var(--space-2) 0;
}

.plan-card-row {
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

.plan-card-row:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-text-secondary);
}

.plan-card-leading {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.plan-card-icon {
  color: var(--color-info);
  font-size: 12px;
}

.plan-card-disclosure {
  transition: transform var(--transition-fast);
  font-size: 10px;
}

.plan-card-disclosure.expanded {
  transform: rotate(180deg);
}

.plan-card-title {
  font-weight: var(--weight-medium);
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.plan-card-sep {
  width: 1px;
  height: 12px;
  background: var(--color-border-light);
  flex-shrink: 0;
}

.plan-card-progress {
  white-space: nowrap;
  flex-shrink: 0;
}

.plan-card-tag {
  flex-shrink: 0;
}

.plan-card-body {
  margin-top: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card-elevated);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  max-width: 100%;
  min-width: 0;
}

.plan-card-steps {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.plan-card-step {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
}

.plan-step-glyph {
  flex-shrink: 0;
  font-family: var(--font-mono, monospace);
  font-size: var(--text-xs);
}

.glyph--completed {
  color: var(--color-success, #16a34a);
}

.glyph--in_progress {
  color: var(--color-info);
}

.glyph--blocked {
  color: var(--color-warning, #b45309);
}

.plan-step-text {
  word-break: break-word;
  overflow-wrap: anywhere;
  min-width: 0;
}

.plan-card-interrupted {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--color-border-light);
  font-size: var(--text-xs);
  color: var(--color-warning, #b45309);
}
</style>
