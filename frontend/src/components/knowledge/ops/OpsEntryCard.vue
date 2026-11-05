<template>
  <div class="ops-entry" v-loading="loading">
    <div class="entry-head">
      <div class="entry-title">
        <span class="entry-name">知识运营</span>
        <span class="entry-summary" :class="{ 'summary-bad': totalTodos > 0 }">{{
          summaryText
        }}</span>
      </div>
      <router-link class="entry-cta" :to="`/home/spaces/${spaceId}/ops/overview`">
        进入工作台
        <span class="cta-arrow" aria-hidden="true">→</span>
      </router-link>
    </div>
    <div class="entry-tiles">
      <router-link
        v-for="tile in tiles"
        :key="tile.key"
        class="entry-tile"
        :class="{ 'tile-bad': (tile.count ?? 0) > 0 }"
        :to="tile.to"
      >
        <span class="tile-num">{{ tile.count ?? '—' }}</span>
        <span class="tile-label">{{ tile.label }}</span>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 知识运营大入口卡（空间首页）：健康摘要 + 四待办维度真实计数直链。
 *
 * 入口即状态：替代原 header 小按钮，进空间首页 5 秒内可见运营待办全景；
 * 任一维度 >0 红显并计入摘要文案。数据轻量三接口，失败静默（计数显 —，
 * 卡片仍可点击进入运营区）。
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
  border: 1px solid var(--color-border-light);
  border-left: 3px solid var(--color-accent);
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.entry-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.entry-title {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
  min-width: 0;
}

.entry-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text);
}

.entry-summary {
  font-size: 12px;
  color: var(--color-text-muted);
}

.summary-bad {
  color: var(--color-danger);
  font-weight: 600;
}

.entry-cta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-btn-primary-text);
  background: var(--color-btn-primary);
  border-radius: 8px;
  padding: 7px 14px;
  text-decoration: none;
  transition: background 0.15s;
  flex-shrink: 0;
}

.entry-cta:hover {
  background: var(--color-btn-primary-hover);
}

.cta-arrow {
  font-size: 12px;
}

.entry-tiles {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.entry-tile {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid var(--color-border-light);
  border-radius: 10px;
  padding: 10px 14px;
  text-decoration: none;
  transition:
    border-color 0.15s,
    background 0.15s;
}

.entry-tile:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
}

.entry-tile.tile-bad {
  border-color: var(--color-danger);
}

.tile-num {
  font-size: 22px;
  font-weight: 600;
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.tile-bad .tile-num {
  color: var(--color-danger);
}

.tile-label {
  font-size: 12px;
  color: var(--color-text-secondary);
}

@media (max-width: 900px) {
  .entry-tiles {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
