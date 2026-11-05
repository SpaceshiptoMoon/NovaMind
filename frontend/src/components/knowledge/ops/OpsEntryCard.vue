<template>
  <section class="ops-entry">
    <div class="entry-head">
      <div class="entry-head-text">
        <h3 class="entry-title">知识运营</h3>
        <p class="entry-note" :class="{ 'note-bad': totalTodos > 0 }">{{ summaryText }}</p>
      </div>
      <router-link class="entry-cta" :to="`/home/spaces/${spaceId}/ops/overview`"
        >进入工作台</router-link
      >
    </div>
    <div class="entry-grid">
      <router-link v-for="tile in tiles" :key="tile.key" class="stat-card" :to="tile.to">
        <span class="stat-value" :class="{ 'stat-bad': (tile.count ?? 0) > 0 }">
          {{ tile.count ?? '—' }}
        </span>
        <span class="stat-label">{{ tile.label }}</span>
      </router-link>
    </div>
  </section>
</template>

<script setup lang="ts">
/**
 * 知识运营大入口卡（空间首页）：标题行 + 四张 stat-card。
 *
 * 数字卡完全复用站点 stat-card 语言（KnowledgeBaseView 统计卡条同款：白卡
 * + --color-border + radius-lg + hover 焦点边），与本页下方统计卡条同屏
 * 一致。红只给 >0 的数字本身。数据轻量三接口，失败静默（计数显 —，
 * 卡片仍可进入运营区）。
 */
import { computed, onMounted, ref } from 'vue'
import { spaceStatsApi } from '@/api/knowledge'
import type { KbOpsOverview } from '@/api/types'

const props = defineProps<{ spaceId: number }>()

const loading = ref(false)
const overview = ref<KbOpsOverview | null>(null)
const suggestionCount = ref<number | null>(null)
const gapCount = ref<number | null>(null)

const tiles = computed(() => [
  {
    key: 'failed',
    count: overview.value?.failed_documents.count ?? null,
    label: '解析失败',
    to: `/home/spaces/${props.spaceId}/ops/overview`,
  },
  {
    key: 'due',
    count: overview.value?.due_reviews.count ?? null,
    label: '待复审',
    to: `/home/spaces/${props.spaceId}/ops/queue`,
  },
  {
    key: 'suggestions',
    count: suggestionCount.value,
    label: '待处置建议',
    to: `/home/spaces/${props.spaceId}/ops/queue`,
  },
  {
    key: 'gaps',
    count: gapCount.value,
    label: '内容缺口',
    to: `/home/spaces/${props.spaceId}/ops/gaps`,
  },
])

const totalTodos = computed(() => tiles.value.reduce((sum, t) => sum + (t.count ?? 0), 0))

const summaryText = computed(() => {
  if (totalTodos.value > 0) {
    return `${totalTodos.value} 项待办需要处理`
  }
  if (loading.value) return '加载中…'
  return '近 7 天无待办异常'
})

onMounted(async () => {
  loading.value = true
  try {
    const [ov, sug, gap] = await Promise.all([
      spaceStatsApi.getOpsOverview(props.spaceId),
      spaceStatsApi.getReviewSuggestions(props.spaceId),
      spaceStatsApi.getGapReport(props.spaceId),
    ])
    overview.value = ov
    suggestionCount.value = sug.total ?? 0
    gapCount.value = gap.kpi?.gap_cluster_count ?? 0
  } catch (e) {
    console.warn('[OpsEntryCard] 概览加载失败', e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
/* 头部行不带盒子：与 KnowledgeBaseView「页头 → 统计卡条」同一解剖结构 */
.ops-entry {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.entry-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.entry-head-text {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  flex-wrap: wrap;
  min-width: 0;
}

.entry-title {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.entry-note {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.note-bad {
  color: var(--color-danger);
  font-weight: var(--weight-semibold);
}

.entry-cta {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-btn-primary-text);
  background: var(--color-btn-primary);
  border-radius: var(--radius-md);
  padding: 7px 16px;
  text-decoration: none;
  transition: background 0.15s;
  flex-shrink: 0;
}

.entry-cta:hover {
  background: var(--color-btn-primary-hover);
}

.entry-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-3);
}

/* 数字卡：与 KnowledgeBaseView .stat-card 同款（白卡 + --color-border +
   radius-lg + hover 焦点边），保证与本页下方统计卡条同屏一致 */
.stat-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-1);
  padding: var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  text-decoration: none;
  transition:
    border-color 0.15s,
    background 0.15s;
}

.stat-card:hover {
  border-color: var(--color-border-focus);
  background: var(--color-bg-hover);
}

.stat-value {
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}

/* 待办语义：>0 红数（与站内 danger 数字口径一致），0 保持中性 */
.stat-value.stat-bad {
  color: var(--color-danger);
}

.stat-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

@media (max-width: 900px) {
  .entry-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
