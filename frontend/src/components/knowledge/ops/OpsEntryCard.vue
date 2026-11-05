<template>
  <section class="ops-entry">
    <div class="entry-head">
      <div class="ledger-text">
        <h3 class="entry-title">知识运营</h3>
        <p class="ledger-note" :class="{ 'note-bad': totalTodos > 0 }">{{ summaryText }}</p>
      </div>
      <router-link class="entry-cta" :to="`/home/spaces/${spaceId}/ops/overview`"
        >进入工作台</router-link
      >
    </div>
    <div class="entry-numbers">
      <router-link v-for="tile in tiles" :key="tile.key" class="num-cell" :to="tile.to">
        <b class="num" :class="{ 'num-bad': (tile.count ?? 0) > 0 }">{{ tile.count ?? '—' }}</b>
        <span class="num-label">{{ tile.label }}</span>
      </router-link>
    </div>
  </section>
</template>

<script setup lang="ts">
/**
 * 知识运营大入口卡（空间首页）：标题行 + 待办数字行。
 *
 * 全站 Neutral Minimal 语言：白卡 + --color-border + radius-xl，内部数字列
 * 用发丝线分隔（单卡内部分隔属 shadcn 惯例，不产生异质感）。红只给 >0 的
 * 数字本身。数据轻量三接口，失败静默（计数显 —，卡片仍可进入运营区）。
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
.ops-entry {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  overflow: hidden;
}

.entry-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
}

.ledger-text {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}

.entry-title {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.ledger-note {
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

.entry-numbers {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.num-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-4) var(--space-5);
  text-decoration: none;
  transition: background 0.15s;
}

.num-cell + .num-cell {
  border-left: 1px solid var(--color-border-light);
}

.num-cell:hover {
  background: var(--color-bg-hover);
}

.num {
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  line-height: 1.1;
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.num-bad {
  color: var(--color-danger);
}

.num-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

@media (max-width: 900px) {
  .entry-numbers {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .num-cell:nth-child(3) {
    border-left: none;
  }

  .num-cell:nth-child(n + 3) {
    border-top: 1px solid var(--color-border-light);
  }
}
</style>
