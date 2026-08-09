<template>
  <div class="task-node-log">
    <el-table v-if="rows.length" :data="rows" row-key="key" class="node-log-table" size="small">
      <el-table-column label="节点" min-width="120">
        <template #default="{ row }">
          <span class="node-name">{{ row.label }}</span>
        </template>
      </el-table-column>

      <el-table-column label="状态" width="96" align="center">
        <template #default="{ row }">
          <el-tag :type="row.statusType" effect="plain" round size="small">{{ row.statusText }}</el-tag>
        </template>
      </el-table-column>

      <el-table-column label="耗时" width="100" align="center">
        <template #default="{ row }">{{ row.durationText }}</template>
      </el-table-column>

      <el-table-column label="产出" min-width="200">
        <template #default="{ row }">
          <span v-if="row.metricsText" class="node-metrics">{{ row.metricsText }}</span>
          <span v-else class="node-metrics is-empty">-</span>
        </template>
      </el-table-column>

      <el-table-column label="时间" width="200">
        <template #default="{ row }">
          <span class="node-time">{{ row.timeText }}</span>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-else description="暂无节点日志" :image-size="48" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { TaskNodeLog } from '@/api/types'
import { formatDate } from '@/utils/format'

const props = defineProps<{
  stepProgress?: Record<string, TaskNodeLog | string> | null
}>()

// 节点规范顺序 + 中文标签（覆盖文本/音频/视频三套管道的节点键）
const NODE_ORDER: { key: string; label: string }[] = [
  { key: 'parsed', label: '解析' },
  { key: 'transcription_done', label: '转写' },
  { key: 'frames_extracted', label: '抽帧' },
  { key: 'descriptions_generated', label: '画面描述' },
  { key: 'split', label: '切分' },
  { key: 'text_split', label: '切分' },
  { key: 'embedded', label: '向量化' },
  { key: 'question_generation', label: '问题生成' },
  { key: 'indexed', label: '索引' },
]

// metrics 字段的中文标签（未列出的键原样展示）
const METRIC_LABELS: Record<string, string> = {
  char_count: '字符',
  chunk_count: '分块',
  frame_count: '帧',
  description_count: '描述',
  segment_count: '段',
  embedding_count: '向量',
  indexed_count: '已索引',
  total_questions: '问题',
  parse_strategy: '解析策略',
  split_strategy: '切分策略',
  chunk_size: '分块大小',
  dimension: '维度',
  asr_protocol: 'ASR',
  language: '语言',
  file_type: '类型',
  enabled: '启用',
}

interface NodeRow {
  key: string
  label: string
  statusType: 'info' | 'success' | 'warning' | 'danger'
  statusText: string
  durationText: string
  metricsText: string
  timeText: string
}

function normalizeEntry(entry: TaskNodeLog | string | undefined): TaskNodeLog | null {
  if (entry == null) return null
  if (typeof entry === 'string') return { status: entry } // 兼容旧扁平 {step:'done'}
  return entry
}

function statusDisplay(status?: string): { type: NodeRow['statusType']; text: string } {
  switch (status) {
    case 'running':
      return { type: 'warning', text: '处理中' }
    case 'done':
      return { type: 'success', text: '完成' }
    case 'failed':
      return { type: 'danger', text: '失败' }
    case 'skipped':
      return { type: 'info', text: '跳过' }
    default:
      return { type: 'info', text: status || '未知' }
  }
}

function formatDurationMs(ms?: number | null): string {
  if (ms == null) return '-'
  if (ms < 1000) return `${ms} ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 2 : 1)} s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes}m ${rest}s`
}

function formatMetrics(metrics?: Record<string, unknown>): string {
  if (!metrics) return ''
  const entries = Object.entries(metrics).filter(([, v]) => v !== null && v !== undefined && v !== '')
  if (!entries.length) return ''
  return entries
    .map(([k, v]) => {
      const label = METRIC_LABELS[k] ?? k
      const val = typeof v === 'boolean' ? (v ? '是' : '否') : String(v)
      return `${label} ${val}`
    })
    .join(' · ')
}

function formatTimeRange(started?: string | null, finished?: string | null): string {
  if (started && finished) return `${formatDate(started)} → ${formatDate(finished)}`
  if (started) return `${formatDate(started)} →`
  if (finished) return `→ ${formatDate(finished)}`
  return '-'
}

const rows = computed<NodeRow[]>(() => {
  const progress = props.stepProgress
  if (!progress) return []

  // 规范顺序中存在的节点先排，再追加未列出的节点（向前兼容新节点键）
  const ordered: NodeRow[] = []
  const seen = new Set<string>()

  for (const { key, label } of NODE_ORDER) {
    if (!(key in progress)) continue
    seen.add(key)
    const node = normalizeEntry(progress[key])
    if (!node) continue
    const status = statusDisplay(node.status)
    ordered.push({
      key,
      label,
      statusType: status.type,
      statusText: status.text,
      durationText: formatDurationMs(node.duration_ms),
      metricsText: formatMetrics(node.metrics),
      timeText: formatTimeRange(node.started_at, node.finished_at),
    })
  }

  for (const [key, raw] of Object.entries(progress)) {
    if (seen.has(key)) continue
    const node = normalizeEntry(raw)
    if (!node) continue
    const status = statusDisplay(node.status)
    ordered.push({
      key,
      label: key,
      statusType: status.type,
      statusText: status.text,
      durationText: formatDurationMs(node.duration_ms),
      metricsText: formatMetrics(node.metrics),
      timeText: formatTimeRange(node.started_at, node.finished_at),
    })
  }

  return ordered
})
</script>

<style scoped>
.task-node-log {
  width: 100%;
}

.node-log-table {
  border: 1px solid var(--color-border-light);
  border-radius: 12px;
  overflow: hidden;
}

.node-log-table :deep(th.el-table__cell) {
  background: var(--color-bg-card-elevated);
  color: var(--color-text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.node-name {
  color: var(--color-text);
  font-weight: 600;
  font-size: 13px;
}

.node-metrics {
  color: var(--color-text-secondary);
  font-size: 12px;
}

.node-metrics.is-empty {
  color: var(--color-text-muted);
}

.node-time {
  color: var(--color-text-muted);
  font-size: 12px;
}
</style>