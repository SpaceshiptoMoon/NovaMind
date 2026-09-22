<template>
  <div class="wiki-graph-panel">
    <div class="graph-toolbar">
      <el-select
        v-model="centerSlug"
        size="small"
        filterable
        clearable
        :placeholder="allNodes.length ? '搜索页面，仅显示与其相连的节点' : '暂无页面可作中心'"
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
      <span class="graph-count">
        {{ graphCountText }}
      </span>
      <span class="toolbar-space" />
      <el-tooltip content="重置布局" placement="top">
        <el-button
          text
          size="small"
          :icon="Refresh"
          :disabled="!graph"
          @click="resetLayout"
        />
      </el-tooltip>
      <span class="graph-hint">拖拽平移 · 滚轮缩放 · 单击节点打开页面</span>
    </div>

    <div ref="canvasRef" class="graph-canvas" :class="{ 'is-loading': loading }">
      <div v-if="!graph && !loading" class="graph-empty">
        <el-empty description="暂无图数据" />
      </div>
      <div v-else-if="loading" class="graph-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Loading, Refresh } from '@element-plus/icons-vue'
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

// 工具栏统计 chip：概览「N 节点 · M 链接」，ego「N 个相关页面」；
// 截断时并入提示（替代原独立 truncated hint）
const graphCountText = computed(() => {
  if (!graph.value) return ''
  const { meta } = graph.value
  const base = meta.truncated ? `已显示 ${meta.returned}/${meta.total} 节点` : `${meta.returned} 节点`
  return centerSlug.value ? base : `${base} · ${graph.value.edges.length} 链接`
})

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
  const secondaryColor = cssVar('--color-text-secondary', '#616161')
  // 边线不能用 --color-border-light（#efefef 画在 #ffffff 上对比度 ~1.07，完全隐形）；
  // --color-text-faint 是"离表面一步的灰"，light/dark 成对反转，发丝线仍可辨
  const edgeColor = cssVar('--color-text-faint', '#c9c9c9')
  const surfaceColor = cssVar('--color-bg-card', '#ffffff')

  // 标签分级（Obsidian 式）：只给 hub 节点 + ego 中心直标，其余 hover 浮现；
  // 阈值随规模缩放，小图全标、大图只标头部 15%
  const slugs = new Set(data.nodes.map((n) => n.slug))
  const labelQuota = Math.max(6, Math.ceil(data.nodes.length * 0.15))
  const labelSlugs = new Set(
    [...data.nodes].sort((a, b) => b.link_count - a.link_count).slice(0, labelQuota).map((n) => n.slug),
  )

  const nodes = data.nodes.map((node) => {
    const isCenter = node.slug === centerSlug.value
    const typeColor = cssVar(TYPE_COLOR_VARS[node.page_type] ?? '--color-primary', '#3f3f46')
    // sqrt 压缩：link_count 悬殊时 hub 不再吞掉邻域（线性公式 22+4n 会到 64px）
    const size = Math.max(10, Math.min(30, 10 + Math.sqrt(node.link_count) * 4))
    if (isCenter) {
      // 选中节点强化区分：typeColor 描边 + 同色半透明 halo 外圈 + 加粗下划线标签
      return {
        id: node.slug,
        name: node.title,
        slug: node.slug,
        category: categories.indexOf(node.page_type),
        symbolSize: size * 1.4,
        itemStyle: {
          borderColor: typeColor,
          borderWidth: 3,
          shadowBlur: 12,
          shadowColor: typeColor,
        },
        label: {
          show: true,
          position: 'bottom',
          distance: 8,
          fontSize: 12,
          color: textColor,
          fontWeight: 700,
          backgroundColor: surfaceColor,
          padding: [3, 8],
          borderRadius: 4,
          borderColor: typeColor,
          borderWidth: 1,
        },
        tooltip: {
          title: node.title,
          pageType: TYPE_LABELS[node.page_type] ?? node.page_type,
          linkCount: node.link_count,
        },
      }
    }
    return {
      id: node.slug,
      name: node.title,
      slug: node.slug,
      category: categories.indexOf(node.page_type),
      symbolSize: size,
      // 底色表面环：节点重叠处保持可辨，随主题反转
      itemStyle: { borderColor: surfaceColor, borderWidth: 2 },
      label: {
        show: labelSlugs.has(node.slug),
        fontSize: 11,
        color: secondaryColor,
        // 底色晕圈：标签压在边线/节点上仍可读
        textBorderColor: surfaceColor,
        textBorderWidth: 2,
      },
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
      backgroundColor: cssVar('--color-bg-card-elevated', '#fafafa'),
      borderColor: cssVar('--color-border', '#e5e5e5'),
      textStyle: { color: textColor, fontSize: 12 },
      extraCssText: 'border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,0.07);',
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
        // 左上角：力导向易聚簇的是右上（中心下拉区），左上通常空
        top: 10,
        left: 12,
        data: categories.map((type) => ({ name: TYPE_LABELS[type] ?? type })),
        icon: 'circle',
        textStyle: { color: secondaryColor, fontSize: 12 },
        itemWidth: 10,
        itemHeight: 10,
        itemGap: 14,
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
          repulsion: 800,
          edgeLength: [50, 130],
          gravity: 0.06,
          friction: 0.2,
          layoutAnimation: true,
        },
        label: { position: 'bottom', distance: 6 },
        // 剩余重叠兜底：直标集合之外的标签互相压盖时自动隐藏
        labelLayout: { hideOverlap: true },
        emphasis: {
          focus: 'adjacency',
          label: { show: true },
          lineStyle: { width: 2.5, opacity: 1 },
        },
        scaleLimit: { min: 0.3, max: 3 },
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

// 重置布局：全量重跑力导向（notMerge），节点回到初始排布
function resetLayout() {
  if (graph.value) renderChart(graph.value)
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
  flex-shrink: 0;
}

.center-select {
  width: 280px;
}

.graph-count {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  white-space: nowrap;
}

/* 弹性占位：把重置按钮与手势提示推到右端 */
.toolbar-space {
  flex: 1;
}

.graph-hint {
  color: var(--color-text-faint);
  font-size: var(--text-xs);
  white-space: nowrap;
}

@media (max-width: 900px) {
  .graph-hint {
    display: none;
  }
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
  transition: opacity var(--transition-base);
}

/* 加载态：EP v-loading 遮罩白底在 dark 下闪白，改降透明 + 居中旋转图标 */
.graph-canvas.is-loading {
  opacity: 0.55;
  pointer-events: none;
}

.graph-loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
  font-size: 24px;
}

.graph-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
