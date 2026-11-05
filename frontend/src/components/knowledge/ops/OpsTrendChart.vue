<template>
  <div class="ops-trend-chart">
    <div class="chart-title-row">
      <span class="chart-title">{{ title }}</span>
      <span v-if="subtitle" class="chart-subtitle">{{ subtitle }}</span>
    </div>
    <div ref="chartRef" class="chart-body" :style="{ height: `${height}px` }" />
    <div v-if="empty" class="chart-empty">当前时间窗内暂无问答数据</div>
  </div>
</template>

<script setup lang="ts">
/**
 * 运营趋势折线图（echarts 封装）：多序列 line + 主题色从 CSS 变量固化。
 *
 * 生命周期与坑位（承 WikiGraphPanel/SpaceInsightView 既有经验）：
 * - ResizeObserver 处理容器尺寸变化，0 尺寸（display:none）跳过渲染；
 * - 颜色在渲染时从 CSS 变量读取固化进 canvas，主题切换（watch theme）全量重渲染；
 * - 卸载 disconnect + dispose。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useTheme } from '@/composables/useTheme'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

interface TrendSeries {
  /** 序列名（图例与 tooltip） */
  name: string
  /** 与 labels 等长的数值序列 */
  data: number[]
  /** 语义色 token 名：primary=墨水蓝 / danger=红（默认 primary） */
  tone?: 'primary' | 'danger'
  /** 面积填充（主序列用） */
  area?: boolean
}

const props = withDefaults(
  defineProps<{
    title: string
    subtitle?: string
    /** x 轴标签（日期串） */
    labels: string[]
    series: TrendSeries[]
    height?: number
  }>(),
  { subtitle: '', height: 240 },
)

const { theme } = useTheme()
const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

const empty = computed(() => props.labels.length === 0)

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function colorToken(token: string, fallback: string): string {
  const v = cssVar(token)
  return v || fallback
}

function render(): void {
  const el = chartRef.value
  if (!el || empty.value) return
  if (el.clientWidth === 0 || el.clientHeight === 0) return
  if (!chart) {
    chart = echarts.init(el)
  }
  chart.setOption({
    animation: false,
    grid: { left: 40, right: 16, top: 32, bottom: 28 },
    tooltip: { trigger: 'axis' },
    legend: {
      data: props.series.map((s) => s.name),
      textStyle: { color: colorToken('--color-text-secondary', '#525252'), fontSize: 12 },
      top: 0,
    },
    xAxis: {
      type: 'category',
      data: props.labels,
      axisLabel: { color: colorToken('--color-text-muted', '#5f5f5f'), fontSize: 11 },
      axisLine: { lineStyle: { color: colorToken('--color-border-light', '#e7e7e3') } },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: colorToken('--color-text-muted', '#5f5f5f'), fontSize: 11 },
      splitLine: { lineStyle: { color: colorToken('--color-border-light', '#e7e7e3') } },
    },
    series: props.series.map((s) => ({
      name: s.name,
      type: 'line',
      data: s.data,
      smooth: true,
      symbolSize: 5,
      itemStyle: {
        color:
          s.tone === 'danger'
            ? colorToken('--color-danger', '#9f2f2d')
            : colorToken('--color-primary', '#20618f'),
      },
      areaStyle: s.area ? { opacity: 0.06 } : undefined,
    })),
  })
}

watch(
  () => [props.labels, props.series],
  () => render(),
  { deep: true },
)
watch(theme, () => render())

onMounted(() => {
  observer = new ResizeObserver(() => render())
  if (chartRef.value) observer.observe(chartRef.value)
  render()
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.ops-trend-chart {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  padding: 14px 16px;
  position: relative;
}

.chart-title-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.chart-title {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.chart-subtitle {
  font-size: 11px;
  color: var(--color-text-muted);
}

.chart-body {
  width: 100%;
}

.chart-empty {
  position: absolute;
  inset: 48px 0 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--color-text-muted);
}
</style>
