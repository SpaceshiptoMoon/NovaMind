<template>
  <div class="wiki-graph-panel">
    <div class="graph-toolbar">
      <el-select
        v-model="centerSlug"
        size="small"
        filterable
        clearable
        placeholder="搜索页面，仅显示与其相连的节点"
        class="center-select"
        @change="loadGraph"
      >
        <el-option
          v-for="node in allNodes"
          :key="node.slug"
          :label="node.title"
          :value="node.slug"
        />
      </el-select>
      <span v-if="graph?.meta.truncated" class="truncated-hint">
        显示 {{ graph.meta.returned }}/{{ graph.meta.total }} 节点
      </span>
    </div>

    <div ref="canvasRef" class="graph-canvas">
      <div v-if="!graph && !loading" class="graph-empty">
        <el-empty description="暂无图数据" />
      </div>
      <div v-else-if="loading" v-loading="true" class="graph-empty" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { wikiApi } from '@/api/knowledge'
import { useTheme } from '@/composables/useTheme'
import type { WikiGraphResponse } from '@/api/types'

echarts.use([GraphChart, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  spaceId: number
  kbId: number
  initialCenter?: string
}>()

const emit = defineEmits<{ select: [slug: string] }>()

// 模式由 centerSlug 推导：选中即邻域（ego，仅直接相连一层，对齐 WeKnora
// GRAPH_EGO_DEFAULT_DEPTH=1），清空即概览（overview）
const centerSlug = ref(props.initialCenter ?? '')
const graph = ref<WikiGraphResponse | null>(null)
const loading = ref(false)

// 主题切换联动：theme 是模块级共享 ref，AppHeader 切换后 watch 立即触发。
// chart 颜色在 buildOption 时经 cssVar 固化进 canvas，必须重跑 setOption 才能跟随；
// merge 模式下同 id 数据保留 force 布局位置，节点不会重洗
const { theme } = useTheme()

// 全部节点（供 ego 中心下拉；overview 图不完整时回退索引接口）
const allNodes = ref<Array<{ slug: string; title: string }>>([])

const canvasRef = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null
// 容器尚无尺寸时暂存的待渲染数据（ResizeObserver 首次回调消费）
let pendingRender: WikiGraphResponse | null = null

const TYPE_LABELS: Record<string, string> = {
  entity: '实体',
  concept: '概念',
  summary: '摘要',
  synthesis: '综合',
  comparison: '对比',
}

// 类型 → base.css 语义色（与浏览页类型徽章同一色系，light/dark 成对；
// 不用 --el-color-info：EP 默认灰且其 light-9 系暗色未重定义）
const TYPE_COLOR_VARS: Record<string, string> = {
  entity: '--color-primary',
  concept: '--color-success',
  summary: '--color-warning',
  synthesis: '--color-danger',
  comparison: '--color-info',
}

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

// tooltip formatter 拼接 HTML，页面标题用户可控（Markdown 来源），必须转义
function escapeHtml(s: string): string {
  return s.replace(
    /[&<>"']/g,
    (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c,
  )
}

function buildOption(data: WikiGraphResponse): echarts.EChartsCoreOption {
  const categories = [...new Set(data.nodes.map((n) => n.page_type))]
  const textColor = cssVar('--color-text', '#303133')
  // 边线不能用 --color-border-light（#efefef 画在 #ffffff 上对比度 ~1.07，完全隐形）；
  // --color-text-faint 是"离表面一步的灰"，light/dark 成对反转，发丝线仍可辨
  const edgeColor = cssVar('--color-text-faint', '#c9c9c9')

  const slugs = new Set(data.nodes.map((n) => n.slug))
  const nodes = data.nodes.map((node) => {
    const isCenter = node.slug === centerSlug.value
    return {
      id: node.slug,
      name: node.title,
      slug: node.slug,
      category: categories.indexOf(node.page_type),
      symbolSize: isCenter
        ? Math.min(22 + node.link_count * 4, 64) * 1.25
        : Math.min(22 + node.link_count * 4, 64),
      label: isCenter
        ? { show: true, fontSize: 11, color: textColor, fontWeight: 600 }
        : { show: true, fontSize: 11, color: textColor },
      tooltip: {
        title: node.title,
        pageType: TYPE_LABELS[node.page_type] ?? node.page_type,
        linkCount: node.link_count,
      },
    }
  })

  const edges = data.edges
    .filter((e) => slugs.has(e.source) && slugs.has(e.target))
    .map((e) => ({
      source: e.source,
      target: e.target,
      lineStyle: { color: edgeColor, width: 1, opacity: 0.45, curveness: 0.12 },
    }))

  return {
    tooltip: {
      confine: true,
      formatter: (params: {
        dataType: string
        data: { tooltip: { title: string; pageType: string; linkCount: number } }
      }) => {
        if (params.dataType !== 'node') return ''
        const info = params.data.tooltip
        return `<strong>${escapeHtml(info.title)}</strong><br/>类型：${escapeHtml(
          info.pageType,
        )}<br/>链接数：${info.linkCount}`
      },
    },
    legend: [
      {
        top: 8,
        right: 12,
        data: categories.map((type) => ({ name: TYPE_LABELS[type] ?? type })),
        textStyle: { color: textColor, fontSize: 11 },
        itemWidth: 12,
        itemHeight: 12,
      },
    ],
    series: [
      {
        type: 'graph',
        layout: 'force',
        data: nodes,
        links: edges,
        categories: categories.map((type) => ({
          name: TYPE_LABELS[type] ?? type,
          itemStyle: { color: cssVar(TYPE_COLOR_VARS[type] ?? '--color-primary', '#3f3f46') },
        })),
        roam: true,
        draggable: true,
        force: {
          repulsion: 320,
          edgeLength: [70, 170],
          gravity: 0.08,
          layoutAnimation: true,
        },
        label: { position: 'bottom', distance: 6 },
        emphasis: { focus: 'adjacency', lineStyle: { width: 2.5, opacity: 1 } },
        scaleLimit: { min: 0.4, max: 4 },
      },
    ],
  }
}

watch(theme, () => {
  if (!chart || !graph.value) return
  // toggleTheme 先改 <html> data-theme 再触发 watcher，cssVar 读到的已是新值
  chart.setOption(buildOption(graph.value))
})

function renderChart(data: WikiGraphResponse) {
  if (!canvasRef.value) return
  // 0×0 容器（如面板尚不可见）初始化 ECharts 会告警/渲染异常；
  // 跳过本次，等 ResizeObserver 首次回调（拿到真实尺寸）后再渲染
  if (canvasRef.value.clientWidth === 0 || canvasRef.value.clientHeight === 0) {
    pendingRender = data
    return
  }
  if (!chart) {
    chart = echarts.init(canvasRef.value)
    chart.on('click', (params) => {
      const slug = (params.data as { slug?: string } | undefined)?.slug
      if (params.dataType === 'node' && slug) emit('select', slug)
    })
  }
  chart.setOption(buildOption(data), true)
}

async function loadGraph() {
  loading.value = true
  try {
    const params = centerSlug.value
      ? { mode: 'ego', center: centerSlug.value, depth: 1, limit: 80 }
      : { mode: 'overview', limit: 80 }
    const data = await wikiApi.getGraph(props.spaceId, props.kbId, params)
    graph.value = data
    renderChart(data)
  } catch {
    graph.value = null
    chart?.clear()
  } finally {
    loading.value = false
  }
}

watch(
  () => props.initialCenter,
  (slug) => {
    if (slug && slug !== centerSlug.value) {
      centerSlug.value = slug
      void loadGraph()
    }
  },
)

onMounted(async () => {
  resizeObserver = new ResizeObserver(() => {
    // 0 尺寸（pane 隐藏 display:none 或尚未布局）时跳过：
    // chart.resize() 会产生 "Can't get DOM width or height" 告警
    if (!canvasRef.value || canvasRef.value.clientWidth === 0 || canvasRef.value.clientHeight === 0) {
      return
    }
    // 首次拿到非零尺寸时，补渲染此前被暂存的图数据
    if (pendingRender) {
      const data = pendingRender
      pendingRender = null
      renderChart(data)
    }
    chart?.resize()
  })
  if (canvasRef.value) resizeObserver.observe(canvasRef.value)
  await loadGraph()
  // ego 中心下拉数据源：全量页面轻量列表
  try {
    const data = await wikiApi.listPages(props.spaceId, props.kbId, { page_size: 100 })
    allNodes.value = data.pages.map((p) => ({ slug: p.slug, title: p.title }))
  } catch {
    allNodes.value = []
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})

defineExpose({ reload: loadGraph })
</script>

<style scoped>
.wiki-graph-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  flex: 1;
}

.graph-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.center-select {
  width: 260px;
}

.truncated-hint {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.graph-canvas {
  position: relative;
  flex: 1;
  /* pane 已通过高度链拿到确定高度，硬撑只在矮视口造成溢出；
     320px 仅为极端矮视口兜底 */
  min-height: 320px;
  overflow: hidden;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card);
}

.graph-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
