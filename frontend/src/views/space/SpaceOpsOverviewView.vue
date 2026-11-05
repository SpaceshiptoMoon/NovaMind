<template>
  <div class="ops-overview" v-loading="loading">
    <!-- 异常区（置顶）：解析失败 / 待复审 / 建议队列 / 内容缺口。全零时折叠为一条正常态 -->
    <div v-if="hasAlerts" class="alert-grid">
      <div class="alert-card" :class="{ 'alert-card--hot': overview?.failed_documents.count }">
        <div class="alert-head">
          <span class="alert-title">解析失败文档</span>
          <span class="alert-count" :class="{ 'count-bad': overview?.failed_documents.count }">
            {{ overview?.failed_documents.count ?? '—' }}
          </span>
        </div>
        <ul v-if="overview?.failed_documents.items.length" class="alert-list">
          <li v-for="doc in overview.failed_documents.items.slice(0, 3)" :key="doc.document_id">
            <span class="item-name" :title="doc.filename">{{ doc.filename }}</span>
            <span class="item-meta">{{ shortTime(doc.completed_at) }}</span>
          </li>
        </ul>
        <p v-else class="alert-empty">暂无明细</p>
        <router-link class="alert-link" :to="`/home/spaces/${spaceId}/knowledge-bases`">
          去查看文档
        </router-link>
      </div>

      <div class="alert-card" :class="{ 'alert-card--hot': overview?.due_reviews.count }">
        <div class="alert-head">
          <span class="alert-title">待复审文档</span>
          <span class="alert-count" :class="{ 'count-bad': overview?.due_reviews.count }">
            {{ overview?.due_reviews.count ?? '—' }}
          </span>
        </div>
        <ul v-if="overview?.due_reviews.items.length" class="alert-list">
          <li v-for="doc in overview.due_reviews.items.slice(0, 3)" :key="doc.document_id">
            <span class="item-name" :title="doc.filename">
              {{ doc.filename }}
              <em v-if="doc.overdue" class="overdue-flag">已过期</em>
            </span>
            <span class="item-meta">{{ shortDate(doc.next_review_at) }}</span>
          </li>
        </ul>
        <p v-else class="alert-empty">暂无明细</p>
        <router-link class="alert-link" :to="`/home/spaces/${spaceId}/ops/queue`">
          去处理复审
        </router-link>
      </div>

      <div class="alert-card" :class="{ 'alert-card--hot': suggestionCount }">
        <div class="alert-head">
          <span class="alert-title">待处置建议</span>
          <span class="alert-count" :class="{ 'count-bad': suggestionCount }">
            {{ suggestionCount ?? '—' }}
          </span>
        </div>
        <p v-if="suggestionCount" class="alert-desc">{{ suggestionSummary }}</p>
        <p v-else class="alert-empty">队列为空</p>
        <router-link class="alert-link" :to="`/home/spaces/${spaceId}/ops/queue`">
          进入待办队列
        </router-link>
      </div>

      <div class="alert-card" :class="{ 'alert-card--hot': gapCount }">
        <div class="alert-head">
          <span class="alert-title">内容缺口</span>
          <span class="alert-count" :class="{ 'count-bad': gapCount }">{{ gapCount ?? '—' }}</span>
        </div>
        <p v-if="topGap" class="alert-desc">
          「{{ topGap.query }}」被问了 {{ topGap.hit_count }} 次，还没有对应内容
        </p>
        <p v-else class="alert-empty">近 7 天无缺口</p>
        <router-link class="alert-link" :to="`/home/spaces/${spaceId}/ops/gaps`">
          查看缺口清单
        </router-link>
      </div>
    </div>
    <div v-else-if="!loading" class="all-clear">近 7 天无待办异常，知识库运行正常</div>

    <!-- KPI 快照：近 7 天单粒度 + 环比 + sparkline（比率类指标升=坏） -->
    <div class="kpi-grid">
      <OpsKpiTile
        label="问答量"
        :value="String(kpi?.qa_total ?? '—')"
        :sub="`点赞 ${kpi?.up_count ?? 0}`"
        :delta-pct="deltaQa"
        :spark="trendQa"
      />
      <OpsKpiTile
        label="点踩率"
        :value="pct(kpi?.down_rate)"
        sub="负反馈占比"
        :value-tone="rateLevel(kpi?.down_rate)"
        :delta-pct="deltaDown"
        invert
      />
      <OpsKpiTile
        label="零命中率"
        :value="pct(kpi?.zero_hit_rate)"
        sub="含拒答"
        :value-tone="rateLevel(kpi?.zero_hit_rate)"
        :delta-pct="deltaZero"
        :spark="trendZero"
        invert
      />
      <OpsKpiTile
        label="低分率"
        :value="pct(kpi?.low_score_rate)"
        :sub="`阈值 ${kpi?.low_score_threshold ?? '—'}`"
        :value-tone="rateLevel(kpi?.low_score_rate)"
        :delta-pct="deltaLow"
        invert
      />
    </div>

    <!-- 洞察条：现象 → 归因 → 链接 -->
    <OpsInsightBar :items="insights" />

    <!-- 趋势 -->
    <OpsTrendChart
      title="问答趋势"
      subtitle="近 7 天按日"
      :labels="trendLabels"
      :series="trendSeries"
    />

    <!-- 内容双榜 -->
    <div class="two-col">
      <div class="ops-panel">
        <div class="panel-title">最常支撑回答</div>
        <el-empty v-if="!supportTop.length" description="暂无引用数据" :image-size="64" />
        <ol v-else class="rank-list">
          <li v-for="row in supportTop" :key="row.document_id" class="rank-item">
            <span class="rank-name" :title="docName(row.document_id)">
              {{ docName(row.document_id) }}
            </span>
            <span class="rank-num">{{ row.support_count }} 次</span>
          </li>
        </ol>
      </div>
      <div class="ops-panel">
        <div class="panel-title">被点击核验最多</div>
        <el-empty v-if="!clickTop.length" description="暂无点击数据" :image-size="64" />
        <ol v-else class="rank-list">
          <li v-for="row in clickTop" :key="row.document_id" class="rank-item">
            <span class="rank-name" :title="docName(row.document_id)">
              {{ docName(row.document_id) }}
            </span>
            <span class="rank-num">{{ row.click_count }} 次</span>
          </li>
        </ol>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 运营工作台首页：异常区置顶 → KPI 快照（环比+sparkline）→ 洞察条 → 趋势 → 双榜。
 *
 * 只回答「哪里需要处理」，不回答「为什么」（归因在缺口页）。
 * KPI 环比：knowledge-gap 端点单窗口，前端调本期+上期两个窗口算 delta；
 * 点踩/低分率无逐日序列，不画 sparkline（量类才有）。
 */
import { computed, onMounted, inject, ref } from 'vue'
import { useRoute } from 'vue-router'
import OpsKpiTile from '@/components/knowledge/ops/OpsKpiTile.vue'
import OpsTrendChart from '@/components/knowledge/ops/OpsTrendChart.vue'
import OpsInsightBar from '@/components/knowledge/ops/OpsInsightBar.vue'
import { spaceStatsApi } from '@/api/knowledge'
import { useOpsDocNames } from '@/composables/useOpsDocNames'
import type { KbOpsOverview, KnowledgeGapStatsResponse, KbOpsSuggestion } from '@/api/types'

const OVERVIEW_WINDOW_DAYS = 7

const route = useRoute()
const spaceId = computed(() => parseInt(String(route.params.id), 10))

const opsRefreshBadges = inject<(() => void) | undefined>('opsRefreshBadges', undefined)

const loading = ref(false)
const overview = ref<KbOpsOverview | null>(null)
const currentStats = ref<KnowledgeGapStatsResponse | null>(null)
const prevStats = ref<KnowledgeGapStatsResponse | null>(null)
const suggestions = ref<KbOpsSuggestion[]>([])
const { resolveDocNames, docName } = useOpsDocNames(spaceId)

const kpi = computed(() => currentStats.value?.kpi)
const trendLabels = computed(() => (currentStats.value?.trend ?? []).map((t) => t.date))
const trendQa = computed(() => (currentStats.value?.trend ?? []).map((t) => t.qa_count))
const trendZero = computed(() => (currentStats.value?.trend ?? []).map((t) => t.zero_hit))
const trendSeries = computed(() => [
  { name: '问答量', data: trendQa.value, tone: 'primary' as const, area: true },
  { name: '零命中', data: trendZero.value, tone: 'danger' as const },
])

const suggestionCount = computed(() => suggestions.value.length)
const gapReport = ref<Awaited<ReturnType<typeof spaceStatsApi.getGapReport>> | null>(null)
const gapKpi = computed(() => gapReport.value?.kpi)
const gapCount = computed(() => gapKpi.value?.gap_cluster_count ?? 0)

const hasAlerts = computed(
  () =>
    (overview.value?.failed_documents.count ?? 0) > 0 ||
    (overview.value?.due_reviews.count ?? 0) > 0 ||
    suggestionCount.value > 0 ||
    gapCount.value > 0,
)

const topGap = computed(() => gapReport.value?.gap_items?.[0] ?? null)

const suggestionSummary = computed(() => {
  const first = suggestions.value[0]
  if (!first) return ''
  const typeText = first.suggestion_type === 'new_version' ? '疑似新旧版本' : '内容矛盾'
  // score 存相似度×1e4（0~10000），展示按旧页口径换算百分比
  const scoreText = first.score === null ? '—' : `${(first.score / 100).toFixed(0)}%`
  return `最新一条：${typeText}建议（相似度 ${scoreText}），待人工裁决`
})

// ===== 洞察条（现象 → 归因 → 链接） =====

const ATTR_LABELS: Record<string, string> = {
  content_gap: '内容缺口',
  retrieval_failure: '检索失败',
  quality_decay: '内容失效',
  permission_boundary: '权限边界',
}

const insights = computed<
  Array<{ text: string; to?: string; linkLabel?: string; tone?: 'bad' | 'flat' }>
>(() => {
  const out: Array<{ text: string; to?: string; linkLabel?: string; tone?: 'bad' | 'flat' }> = []
  const k = gapKpi.value
  const dist = gapReport.value?.attribution_distribution ?? {}
  if (k && k.failure_total > 0) {
    const ranked = Object.entries(dist)
      .filter(([key]) => key !== 'pending')
      .sort((a, b) => b[1] - a[1])
    const [topKey, topCount] = ranked[0] ?? ['', 0]
    const reason =
      topCount > 0 ? `，主要归因是${ATTR_LABELS[topKey] ?? topKey}（${topCount} 个）` : ''
    out.push({
      text: `近 7 天 ${k.failure_total} 个问题未获理想回答${reason}`,
      to: `/home/spaces/${spaceId.value}/ops/gaps`,
      linkLabel: '看归因明细',
      tone: 'bad',
    })
  }
  if (topGap.value) {
    out.push({
      text: `「${topGap.value.query}」被问了 ${topGap.value.hit_count} 次，还没有对应内容`,
      to: `/home/spaces/${spaceId.value}/ops/gaps`,
      linkLabel: '去补内容',
      tone: 'bad',
    })
  }
  if (k && k.pending_attribution > 0) {
    out.push({
      text: `${k.pending_attribution} 个失败问答待归因，归因任务下一轮自动补齐`,
      to: `/home/spaces/${spaceId.value}/ops/gaps`,
      linkLabel: '查看',
      tone: 'flat',
    })
  }
  if (!out.length && (kpi.value?.qa_total ?? 0) > 0) {
    out.push({ text: '近 7 天没有未获理想回答的问题', tone: 'flat' })
  }
  return out
})

// ===== 双榜 =====

const supportTop = computed(() => (citationStats.value?.support_stats ?? []).slice(0, 5))
const clickTop = computed(() => (citationStats.value?.items ?? []).slice(0, 5))
const citationStats = ref<Awaited<ReturnType<typeof spaceStatsApi.getCitationStats>> | null>(null)

// ===== 工具 =====

function pct(v?: number): string {
  if (v === undefined || v === null) return '—'
  return (v * 100).toFixed(1) + '%'
}

function rateLevel(v?: number): 'neutral' | 'bad' {
  return (v ?? 0) >= 0.15 ? 'bad' : 'neutral'
}

/** 环比百分比：上期为 0 或缺失时返回 null（不显示 delta，0 基数下百分比无意义） */
function pctDelta(cur: number | undefined, prev: number | undefined): number | null {
  if (cur === undefined || prev === undefined || prev === 0) return null
  return ((cur - prev) / prev) * 100
}

const deltaQa = computed(() => pctDelta(kpi.value?.qa_total, prevStats.value?.kpi.qa_total))
const deltaDown = computed(() => pctDelta(kpi.value?.down_rate, prevStats.value?.kpi.down_rate))
const deltaZero = computed(() =>
  pctDelta(kpi.value?.zero_hit_rate, prevStats.value?.kpi.zero_hit_rate),
)
const deltaLow = computed(() =>
  pctDelta(kpi.value?.low_score_rate, prevStats.value?.kpi.low_score_rate),
)

function shortDate(iso?: string | null): string {
  return iso ? iso.slice(0, 10) : '—'
}

function shortTime(iso?: string | null): string {
  return iso ? iso.slice(0, 16).replace('T', ' ') : '—'
}

// ===== 加载 =====

onMounted(async () => {
  loading.value = true
  const now = new Date()
  const curStart = new Date(now.getTime() - OVERVIEW_WINDOW_DAYS * 24 * 3600 * 1000)
  const prevStart = new Date(curStart.getTime() - OVERVIEW_WINDOW_DAYS * 24 * 3600 * 1000)
  try {
    const [ov, cur, prev, gap, sug, cit] = await Promise.all([
      spaceStatsApi.getOpsOverview(spaceId.value),
      spaceStatsApi.getKnowledgeGap({
        spaceId: spaceId.value,
        start: curStart.toISOString(),
        end: now.toISOString(),
      }),
      spaceStatsApi.getKnowledgeGap({
        spaceId: spaceId.value,
        start: prevStart.toISOString(),
        end: curStart.toISOString(),
      }),
      spaceStatsApi.getGapReport(spaceId.value),
      spaceStatsApi.getReviewSuggestions(spaceId.value),
      spaceStatsApi.getCitationStats(spaceId.value, { limit: 5 }),
    ])
    overview.value = ov
    currentStats.value = cur
    prevStats.value = prev
    gapReport.value = gap
    suggestions.value = sug.items ?? []
    citationStats.value = cit
    opsRefreshBadges?.()
  } catch (e) {
    console.warn('[SpaceOpsOverview] 概览加载失败', e)
  } finally {
    loading.value = false
  }
  void resolveDocNames()
})
</script>

<style scoped>
.ops-overview {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.all-clear {
  background: var(--ops-panel);
  border: 1px solid var(--ops-line);
  border-left: 3px solid var(--ops-ink-bar);
  border-radius: 8px;
  padding: 12px 16px;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.alert-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.alert-card {
  background: var(--ops-panel);
  border: 1px solid var(--ops-line);
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

/* 异常信号 = 数字红（count-bad）+ 左缘墨条锚点；边框恒发丝线，红不上结构 */
.alert-card--hot {
  border-left: 3px solid var(--ops-ink-bar);
  padding-left: 14px;
}

.alert-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
}

.alert-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.alert-count {
  font-size: 22px;
  font-weight: 600;
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.alert-count.count-bad {
  color: var(--color-danger);
}

.alert-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.alert-list li {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  min-width: 0;
}

.item-name {
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.overdue-flag {
  font-style: normal;
  color: var(--color-danger);
  font-size: 11px;
  margin-left: 4px;
}

.item-meta {
  color: var(--color-text-faint);
  font-size: 11px;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.alert-desc {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.alert-empty {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-faint);
}

.alert-link {
  font-size: 12px;
  color: var(--color-primary);
  text-decoration: none;
  margin-top: auto;
}

.alert-link:hover {
  text-decoration: underline;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  background: var(--ops-panel);
  border: 1px solid var(--ops-line);
  border-radius: 8px;
  overflow: hidden;
}

.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.ops-panel {
  background: var(--ops-panel);
  border: 1px solid var(--ops-line);
  border-radius: 8px;
  padding: 14px 16px;
  min-width: 0;
}

.panel-title {
  font-family: var(--ops-serif);
  font-size: 15px;
  font-weight: 400;
  letter-spacing: 0.03em;
  color: var(--color-text);
  margin-bottom: 10px;
}

.rank-list {
  list-style: none;
  margin: 0;
  padding: 0;
  counter-reset: rank;
  display: flex;
  flex-direction: column;
}

.rank-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
  border-bottom: 1px solid var(--ops-line);
  font-size: 13px;
}

.rank-item:last-child {
  border-bottom: none;
}

.rank-item::before {
  counter-increment: rank;
  content: counter(rank);
  font-size: 11px;
  color: var(--color-text-faint);
  width: 16px;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.rank-name {
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.rank-num {
  color: var(--color-text-secondary);
  font-size: 12px;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 900px) {
  .alert-grid,
  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  /* 两列布局下磁贴自带左线会贴容器左缘：第二行行首去掉左线、补上横线 */
  .kpi-grid :deep(.ops-kpi-tile:nth-child(3)),
  .kpi-grid :deep(.ops-kpi-tile:nth-child(4)) {
    border-left: none;
    border-top: 1px solid var(--ops-line);
  }

  .two-col {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 520px) {
  .alert-grid,
  .kpi-grid {
    grid-template-columns: 1fr;
  }

  .kpi-grid :deep(.ops-kpi-tile) {
    border-left: none;
  }

  .kpi-grid :deep(.ops-kpi-tile + .ops-kpi-tile) {
    border-top: 1px solid var(--ops-line);
  }
}
</style>
