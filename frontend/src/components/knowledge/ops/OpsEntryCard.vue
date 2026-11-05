<template>
  <section class="ops-entry">
    <div class="entry-title">
      <h3>知识运营</h3>
      <p :class="{ 'note-bad': totalTodos > 0 }">{{ summaryText }}</p>
    </div>
    <div class="entry-metrics">
      <router-link v-for="tile in tiles" :key="tile.key" class="metric" :to="tile.to">
        <b class="metric-num" :class="{ 'num-bad': (tile.count ?? 0) > 0 }">
          {{ tile.count ?? '—' }}
        </b>
        <span class="metric-label">{{ tile.label }}</span>
      </router-link>
    </div>
    <router-link class="entry-cta" :to="`/home/spaces/${spaceId}/ops/overview`">进入工作台</router-link>
  </section>
</template>

<script setup lang="ts">
/**
 * 知识运营入口条（空间首页）：单卡横向状态条。
 *
 * 与下方知识库统计卡行在结构上拉开层次——这是一条「状态条」（标题+摘要 |
 * 内联数字×4 | CTA），不是又一行数字卡，避免同屏八张同款卡的模板感。
 * 数字可点直达对应运营页（>0 红数），数据轻量三接口，失败静默。
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
    return `${totalTodos.value} 项待办`
  }
  if (loading.value) return '加载中…'
  return '无待办异常'
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
/* 单卡横向状态条：与下方 stat-card 行（盒阵列）结构互异，native token */
.ops-entry {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-5);
  padding: var(--space-3) var(--space-5);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.entry-title {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  flex-shrink: 0;
}

.entry-title h3 {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.entry-title p {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.note-bad {
  color: var(--color-danger);
  font-weight: var(--weight-semibold);
}

.entry-metrics {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
  row-gap: var(--space-1);
}

/* 内联数字对：竖发丝线分隔，是「摘要里的计数」不是磁贴 */
.metric {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  padding: 4px 20px;
  text-decoration: none;
  border-left: 1px solid var(--color-border-light);
}

.metric:first-child {
  border-left: none;
  padding-left: 0;
}

.metric-num {
  font-size: var(--text-lg);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.metric-num.num-bad {
  color: var(--color-danger);
}

.metric-label {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  transition: color 0.15s;
}

.metric:hover .metric-label {
  color: var(--color-text);
}

.entry-cta {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-btn-primary-text);
  background: var(--color-btn-primary);
  border-radius: var(--radius-md);
  padding: 6px 16px;
  text-decoration: none;
  transition: background 0.15s;
  flex-shrink: 0;
  margin-left: auto;
}

@media (max-width: 900px) {
  .entry-cta {
    margin-left: 0;
  }
}
</style>
