<template>
  <div class="ops-kpi-tile">
    <div class="tile-label">{{ label }}</div>
    <div class="tile-main">
      <span class="tile-value" :class="{ 'tile-bad': valueTone === 'bad' }">{{ value }}</span>
      <span
        v-if="deltaPct !== null && deltaPct !== undefined"
        class="tile-delta"
        :class="
          deltaTone === 'good' ? 'delta-good' : deltaTone === 'bad' ? 'delta-bad' : 'delta-flat'
        "
        :title="`较上一周期 ${deltaPct > 0 ? '+' : ''}${deltaPct.toFixed(1)}%`"
      >
        <span class="delta-arrow" aria-hidden="true">{{ deltaArrow }}</span>
        {{ Math.abs(deltaPct).toFixed(1) }}%
      </span>
    </div>
    <div class="tile-footer">
      <span v-if="sub" class="tile-sub">{{ sub }}</span>
      <svg
        v-if="sparkPath"
        class="tile-spark"
        viewBox="0 0 100 28"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <polyline :points="sparkPath" fill="none" stroke-width="1.5" :class="sparkClass" />
      </svg>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 运营 KPI 磁贴：当前值 + 环比 delta（箭头+红绿冗余编码）+ SVG sparkline。
 *
 * BI 磁贴惯例：数值用 tabular-nums 大号；delta 语义由 invert 决定——
 * 比率类指标「升=坏」（点踩率升红），量类指标「升=好」（问答量升绿）。
 * sparkline 用内联 SVG 折线，不引 echarts（一屏多块磁贴的成本考量）。
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    /** 指标名 */
    label: string
    /** 主值（已格式化的展示串） */
    value: string
    /** 副文案（口径说明/阈值等） */
    sub?: string
    /** 环比变化百分比（+12.5 = 升 12.5%）；null/undefined 不显示 */
    deltaPct?: number | null
    /** 主值语义色：bad 时数值红显 */
    valueTone?: 'neutral' | 'bad'
    /** true = 升是坏事（比率类），false = 升是好事（量类） */
    invert?: boolean
    /** sparkline 数据（按时间序），少于 2 点不画 */
    spark?: number[]
  }>(),
  { sub: '', deltaPct: null, valueTone: 'neutral', invert: false, spark: () => [] },
)

const FLAT_THRESHOLD = 0.1 // 百分比变化小于此值视为持平

const deltaArrow = computed(() => {
  if (deltaDirection.value === 0) return '→'
  return deltaDirection.value > 0 ? '↑' : '↓'
})

const deltaDirection = computed(() => {
  const d = props.deltaPct ?? 0
  if (Math.abs(d) < FLAT_THRESHOLD) return 0
  return d > 0 ? 1 : -1
})

/** delta 语义色：方向 × invert 决定好坏 */
const deltaTone = computed<'good' | 'bad' | 'flat'>(() => {
  const dir = deltaDirection.value
  if (dir === 0) return 'flat'
  const up = dir > 0
  return (props.invert ? !up : up) ? 'good' : 'bad'
})

const sparkPath = computed(() => {
  const data = props.spark
  if (!data || data.length < 2) return ''
  const max = Math.max(...data)
  const min = Math.min(...data)
  const range = max - min || 1
  const width = 100
  const height = 28
  const stepX = width / (data.length - 1)
  return data
    .map((v, i) => {
      const x = (i * stepX).toFixed(1)
      const y = (height - 3 - ((v - min) / range) * (height - 6)).toFixed(1)
      return `${i === 0 ? 'M' : 'L'}${x},${y}`
    })
    .join(' ')
})

const sparkClass = computed(() => (props.valueTone === 'bad' ? 'spark-danger' : 'spark-primary'))
</script>

<style scoped>
/* 「墨水档案」无框磁贴：数字坐在面板上，磁贴之间竖发丝线分隔（容器提供面板
   底与 8px 圆角），废除 12px 同圆角小盒阵列。红只出现在数字本身。 */
.ops-kpi-tile {
  padding: 12px 16px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.ops-kpi-tile + .ops-kpi-tile {
  border-left: 1px solid var(--ops-line);
}

.tile-label {
  font-size: 12px;
  color: var(--color-text-muted);
}

.tile-main {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.tile-value {
  font-size: 28px;
  font-weight: 600;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
}

.tile-value.tile-bad {
  color: var(--color-danger);
}

.tile-delta {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  border-radius: 4px;
  padding: 1px 6px;
}

.delta-arrow {
  font-size: 11px;
}

.delta-good {
  color: var(--color-success);
  background: var(--color-success-subtle);
}

.delta-bad {
  color: var(--color-danger);
  background: var(--color-danger-subtle);
}

.delta-flat {
  color: var(--color-text-muted);
  background: var(--color-bg-hover);
}

.tile-footer {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 8px;
  min-height: 20px;
}

.tile-sub {
  font-size: 11px;
  color: var(--color-text-muted);
}

.tile-spark {
  width: 96px;
  height: 28px;
  flex-shrink: 0;
  opacity: 0.8;
}

.spark-primary {
  stroke: var(--color-primary);
}

.spark-danger {
  stroke: var(--color-danger);
}
</style>
