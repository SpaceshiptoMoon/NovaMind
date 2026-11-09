<template>
  <div class="research-card">
    <button class="research-card-row" @click="$emit('toggle')">
      <span class="research-card-leading" aria-hidden>
        <span class="research-card-spinner" :class="{ done: isDone, failed: isFailed }" />
        <el-icon :size="10" class="research-card-disclosure" :class="{ expanded }">
          <ArrowDown />
        </el-icon>
      </span>
      <span class="research-card-title">{{ title }}</span>
      <span class="research-card-sep" aria-hidden />
      <span class="research-card-progress">{{ progressLabel }}</span>
    </button>
    <div v-if="expanded" class="research-card-body">
      <div class="research-card-bar">
        <div class="research-card-bar-fill" :style="{ width: `${percent}%` }" />
      </div>
      <div v-if="plan?.steps?.length" class="research-card-plan">
        <div class="research-card-plan-title">{{ plan.title || '研究计划' }}</div>
        <ol class="research-card-plan-steps">
          <li v-for="(s, i) in plan.steps" :key="s.step_id || i" class="research-card-plan-step">
            <span class="research-card-plan-glyph" aria-hidden>{{ i + 1 }}.</span>
            <span class="research-card-plan-text">{{ s.title || s.description }}</span>
          </li>
        </ol>
      </div>
      <div v-if="isFailed" class="research-card-failed">研究执行失败，详见错误信息。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 深度研究进度卡：spinner + 标题 + 进度百分比的折叠胶囊行，展开看进度条与计划步骤。
 * 数据源为 role='research' 消息的 extra.research（research_progress 事件原地更新）。
 * 进度是瞬态增强：role='research' 消息不落库，会话刷新/切换后卡片消失
 * （研究报告正文经 tool 消息留档，进度/计划不可回看——批4 再议持久化）。
 */
import { computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import type { ResearchProgressData } from '@/api/types'

const props = defineProps<{
  data: ResearchProgressData
  expanded: boolean
}>()

defineEmits<{ toggle: [] }>()

const STATUS_LABELS: Record<string, string> = {
  analyzing: '分析查询',
  planning: '制定计划',
  plan: '计划就绪',
  searching: '检索中',
  synthesizing: '生成报告',
  completed: '研究完成',
  failed: '研究失败',
}

// completed 是工具层（research.py）在 done 后补发的终态事件；synthesizing 只是
// 引擎综合阶段（85%），此后主模型还要消化报告作答，不算完成
const isDone = computed(() => props.data.status === 'completed')
const isFailed = computed(() => props.data.status === 'failed')

const title = computed(() => props.data.current_step || STATUS_LABELS[props.data.status] || '深度研究')

const percent = computed(() => Math.round(props.data.progress_percent ?? 0))

const plan = computed(() => props.data.plan)

const progressLabel = computed(() => {
  if (isFailed.value) return '失败'
  const total = props.data.total_tasks ?? 0
  if (total > 0) return `${percent.value}% · ${props.data.completed_tasks ?? 0}/${total}`
  return `${percent.value}%`
})
</script>

<style scoped>
.research-card {
  margin: 6px 0;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  overflow: hidden;
  max-width: 640px;
}

.research-card-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  min-width: 0;
}

.research-card-row:hover {
  background: var(--color-bg-hover);
}

.research-card-leading {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.research-card-spinner {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid var(--color-border);
  border-top-color: var(--color-text-secondary);
  animation: research-spin 0.9s linear infinite;
}

.research-card-spinner.done {
  animation: none;
  border: 2px solid var(--color-success);
  background: var(--color-success);
}

.research-card-spinner.failed {
  animation: none;
  border: 2px solid var(--color-danger);
  background: var(--color-danger);
}

@keyframes research-spin {
  to {
    transform: rotate(360deg);
  }
}

.research-card-disclosure {
  color: var(--color-text-faint, var(--color-text-muted));
  transition: transform 0.15s;
}

.research-card-disclosure.expanded {
  transform: rotate(180deg);
}

.research-card-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--color-text);
}

.research-card-sep {
  flex: 1;
  flex-shrink: 1;
  min-width: 12px;
  height: 1px;
  background: var(--color-border-light);
}

.research-card-progress {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--color-text-faint, var(--color-text-muted));
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.research-card-body {
  padding: 8px 12px 12px;
  border-top: 1px solid var(--color-border-light);
}

.research-card-bar {
  height: 3px;
  border-radius: 2px;
  background: var(--color-border-light);
  overflow: hidden;
  margin-bottom: 8px;
}

.research-card-bar-fill {
  height: 100%;
  border-radius: 2px;
  background: var(--color-text-secondary);
  transition: width 0.4s ease;
}

.research-card-plan-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
}

.research-card-plan-steps {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.research-card-plan-step {
  font-size: 12px;
  color: var(--color-text-muted);
  overflow-wrap: anywhere;
}

.research-card-plan-glyph {
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.research-card-failed {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-danger);
}

@media (prefers-reduced-motion: reduce) {
  .research-card-spinner {
    animation: none;
  }
}
</style>
