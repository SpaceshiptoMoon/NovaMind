<template>
  <div class="wiki-graph-panel">
    <div class="graph-toolbar">
      <el-radio-group v-model="mode" size="small" @change="loadGraph">
        <el-radio-button value="overview">概览</el-radio-button>
        <el-radio-button value="ego">邻域</el-radio-button>
      </el-radio-group>
      <el-select
        v-if="mode === 'ego'"
        v-model="centerSlug"
        size="small"
        filterable
        placeholder="选择中心页面"
        class="center-select"
        @change="loadGraph"
      >
        <el-option v-for="node in allNodes" :key="node.slug" :label="node.title" :value="node.slug" />
      </el-select>
      <span v-if="graph?.meta.truncated" class="truncated-hint">
        显示 {{ graph.meta.returned }}/{{ graph.meta.total }} 节点
      </span>
    </div>

    <div v-if="!graph" v-loading="loading" class="graph-canvas is-empty">
      <el-empty v-if="!loading" description="暂无图数据" />
    </div>
    <svg v-else class="graph-canvas" :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="xMidYMid meet">
      <!-- 边 -->
      <line
        v-for="(edge, index) in visibleEdges"
        :key="`e${index}`"
        :x1="nodePos(edge.source)?.x"
        :y1="nodePos(edge.source)?.y"
        :x2="nodePos(edge.target)?.x"
        :y2="nodePos(edge.target)?.y"
        class="graph-edge"
      />
      <!-- 节点 -->
      <g
        v-for="node in graph.nodes"
        :key="node.slug"
        class="graph-node"
        :class="[`is-${node.page_type}`, { 'is-center': node.slug === centerSlug }]"
        :transform="`translate(${nodePos(node.slug)?.x ?? 0},${nodePos(node.slug)?.y ?? 0})`"
        @click="$emit('select', node.slug)"
      >
        <circle :r="nodeRadius(node)" />
        <text :y="nodeRadius(node) + 12" text-anchor="middle">{{ node.title.slice(0, 8) }}</text>
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { wikiApi } from '@/api/knowledge'
import type { WikiGraphResponse } from '@/api/types'

const props = defineProps<{
  spaceId: number
  kbId: number
  initialCenter?: string
}>()

defineEmits<{ select: [slug: string] }>()

const width = 800
const height = 520

const mode = ref<'overview' | 'ego'>(props.initialCenter ? 'ego' : 'overview')
const centerSlug = ref(props.initialCenter ?? '')
const graph = ref<WikiGraphResponse | null>(null)
const loading = ref(false)

// 全部节点（供 ego 中心下拉；overview 图不完整时回退索引接口）
const allNodes = ref<Array<{ slug: string; title: string }>>([])

/** 圆形布局：按 page_type 分三环，slug 哈希决定起始角，避免每次刷新跳动 */
const layout = computed(() => {
  const positions = new Map<string, { x: number; y: number }>()
  if (!graph.value) return positions
  const groups: Record<string, string[]> = {}
  for (const node of graph.value.nodes) {
    ;(groups[node.page_type] ??= []).push(node.slug)
  }
  const radii: Record<string, number> = {
    summary: 120, concept: 190, entity: 230, synthesis: 160, comparison: 160,
  }
  for (const [type, slugs] of Object.entries(groups)) {
    const radius = radii[type] ?? 180
    slugs.forEach((slug, index) => {
      const angle = (2 * Math.PI * index) / Math.max(slugs.length, 1) + type.length
      positions.set(slug, {
        x: width / 2 + radius * Math.cos(angle),
        y: height / 2 + radius * Math.sin(angle),
      })
    })
  }
  return positions
})

function nodePos(slug: string) {
  return layout.value.get(slug)
}

function nodeRadius(node: { link_count: number }) {
  return Math.min(6 + node.link_count * 1.5, 18)
}

const visibleEdges = computed(() => {
  if (!graph.value) return []
  return graph.value.edges.filter(
    (e: { source: string; target: string }) =>
      layout.value.has(e.source) && layout.value.has(e.target)
  )
})

async function loadGraph() {
  loading.value = true
  try {
    const params =
      mode.value === 'ego' && centerSlug.value
        ? { mode: 'ego', center: centerSlug.value, depth: 2, limit: 80 }
        : { mode: 'overview', limit: 80 }
    graph.value = await wikiApi.getGraph(props.spaceId, props.kbId, params)
  } catch {
    graph.value = null
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadGraph()
  // ego 中心下拉数据源：全量页面轻量列表
  try {
    const data = await wikiApi.listPages(props.spaceId, props.kbId, { page_size: 100 })
    allNodes.value = data.pages.map((p) => ({ slug: p.slug, title: p.title }))
  } catch {
    allNodes.value = []
  }
})

defineExpose({ reload: loadGraph })
</script>

<style scoped>
.wiki-graph-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
}

.graph-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.center-select {
  width: 220px;
}

.truncated-hint {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.graph-canvas {
  flex: 1;
  min-height: 380px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card);
}

.graph-canvas.is-empty {
  display: flex;
  align-items: center;
  justify-content: center;
}

.graph-edge {
  stroke: var(--color-border-light, #ddd);
  stroke-width: 1;
}

.graph-node {
  cursor: pointer;
}

.graph-node circle {
  fill: var(--el-color-primary-light-7);
  stroke: var(--el-color-primary);
  stroke-width: 1.5;
}

.graph-node.is-concept circle {
  fill: var(--el-color-success-light-7);
  stroke: var(--el-color-success);
}

.graph-node.is-summary circle {
  fill: var(--el-color-warning-light-7);
  stroke: var(--el-color-warning);
}

.graph-node.is-center circle {
  stroke-width: 3;
}

.graph-node text {
  fill: var(--color-text, #333);
  font-size: 11px;
  pointer-events: none;
}

.graph-node:hover circle {
  stroke-width: 3;
}
</style>
