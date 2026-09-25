<template>
  <div class="space-insight">
    <div class="insight-header">
      <div>
        <h2 class="insight-title">空间洞察</h2>
        <p class="insight-subtitle">从问答反馈与检索信号中发现知识缺口</p>
      </div>
      <div class="insight-filters">
        <el-select v-model="kbFilter" placeholder="全部知识库" clearable style="width: 200px">
          <el-option
            v-for="kb in kbOptions"
            :key="kb.id"
            :label="kb.name"
            :value="kb.id"
          />
        </el-select>
        <el-select v-model="rangeDays" style="width: 130px">
          <el-option label="最近 7 天" :value="7" />
          <el-option label="最近 30 天" :value="30" />
          <el-option label="最近 90 天" :value="90" />
        </el-select>
        <el-button :icon="Refresh" :loading="loading" @click="load" />
      </div>
    </div>

    <el-alert
      v-if="legacyNote"
      :title="legacyNote"
      type="info"
      :closable="false"
      show-icon
      class="insight-note"
    />

    <!-- KPI 四卡 -->
    <div class="kpi-grid" v-loading="loading">
      <div class="kpi-card">
        <div class="kpi-label">问答量</div>
        <div class="kpi-value">{{ stats?.kpi.qa_total ?? '—' }}</div>
        <div class="kpi-sub">点赞 {{ stats?.kpi.up_count ?? 0 }}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">点踩率</div>
        <div class="kpi-value" :class="{ 'kpi-bad': rateLevel(stats?.kpi.down_rate) === 'bad' }">
          {{ pct(stats?.kpi.down_rate) }}
        </div>
        <div class="kpi-sub">负反馈占比</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">零命中率</div>
        <div class="kpi-value" :class="{ 'kpi-bad': rateLevel(stats?.kpi.zero_hit_rate) === 'bad' }">
          {{ pct(stats?.kpi.zero_hit_rate) }}
        </div>
        <div class="kpi-sub">含拒答</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">低分率</div>
        <div class="kpi-value" :class="{ 'kpi-bad': rateLevel(stats?.kpi.low_score_rate) === 'bad' }">
          {{ pct(stats?.kpi.low_score_rate) }}
        </div>
        <div class="kpi-sub">阈值 {{ stats?.kpi.low_score_threshold ?? '—' }}</div>
      </div>
    </div>

    <!-- 趋势图 -->
    <div class="insight-card">
      <div class="card-title">问答趋势</div>
      <div ref="trendChartRef" class="trend-chart" />
    </div>

    <div class="two-col">
      <!-- 零命中问题 -->
      <div class="insight-card">
        <div class="card-title-row">
          <span class="card-title">零命中问题 Top {{ stats?.zero_hit_queries.length ?? 0 }}</span>
        </div>
        <el-empty
          v-if="!stats?.zero_hit_queries.length"
          description="暂无零命中记录（或数据早于埋点上线）"
          :image-size="72"
        />
        <div v-else class="zero-hit-list">
          <div v-for="(q, i) in stats.zero_hit_queries" :key="i" class="zero-hit-item">
            <div class="zero-hit-query" :title="q.query">{{ q.query }}</div>
            <div class="zero-hit-meta">
              <span class="hit-badge">×{{ q.hit_count }}</span>
              <span v-if="q.kb_id" class="meta-text">{{ kbName(q.kb_id) }}</span>
              <span class="meta-text">{{ shortDate(q.last_seen) }}</span>
              <el-button size="small" text type="primary" @click="goDocuments">去补充文档</el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 点踩/低分明细 -->
      <div class="insight-card">
        <div class="card-title">点踩 / 低分回答</div>
        <el-empty
          v-if="!stats?.low_score_messages.length"
          description="暂无点踩或低分回答"
          :image-size="72"
        />
        <div v-else class="low-score-list">
          <div
            v-for="m in stats.low_score_messages"
            :key="m.message_id"
            class="low-score-item"
            @click="goSession(m.session_id)"
          >
            <div class="low-score-snippet">{{ m.answer_snippet }}</div>
            <div class="low-score-meta">
              <el-tag v-if="m.rating === 'down'" type="danger" size="small" effect="plain">点踩</el-tag>
              <el-tag v-else type="warning" size="small" effect="plain">
                低分 {{ formatScore(m.max_score) }}
              </el-tag>
              <span class="meta-text">{{ shortDate(m.created_at) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- KB 维度 -->
    <div class="insight-card">
      <div class="card-title">知识库维度</div>
      <el-table :data="stats?.by_kb ?? []" size="small" :show-header="true">
        <el-table-column prop="kb_name" label="知识库" min-width="180" />
        <el-table-column prop="qa_count" label="问答量" width="100" align="right" />
        <el-table-column label="点踩" width="100" align="right">
          <template #default="{ row }">{{ row.down_count }}</template>
        </el-table-column>
        <el-table-column label="零命中" width="100" align="right">
          <template #default="{ row }">{{ row.zero_hit_count }}</template>
        </el-table-column>
        <el-table-column label="点踩率" width="110" align="right">
          <template #default="{ row }">{{ kbRate(row.down_count, row.qa_count) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
/** 空间洞察页（批次 2b）：知识缺口看板。
 * 信息架构：KPI 四卡 → 趋势双线 → 零命中 Top N + 低分明细 → KB 聚合表。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { knowledgeBaseApi, spaceStatsApi } from '@/api/knowledge'
import { useTheme } from '@/composables/useTheme'
import type { KnowledgeGapStatsResponse } from '@/api/types'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const route = useRoute()
const router = useRouter()
const { theme } = useTheme()

const spaceId = computed(() => parseInt(String(route.params.id), 10))

const loading = ref(false)
const stats = ref<KnowledgeGapStatsResponse | null>(null)
const kbFilter = ref<number | undefined>(undefined)
const rangeDays = ref(30)
const kbOptions = ref<Array<{ id: number; name: string }>>([])

// 埋点上线（批次 2b）前的历史数据无 retrieval 键——零命中识别有盲区，提示一次
const legacyNote = computed(() =>
  (stats.value?.trend.length ?? 0) === 0
    ? '当前时间窗内暂无问答数据。历史数据（埋点上线前）的零命中识别可能不完整。'
    : '',
)

function pct(v?: number): string {
  if (v === undefined || v === null) return '—'
  return (v * 100).toFixed(1) + '%'
}

function rateLevel(v?: number): 'ok' | 'warn' | 'bad' {
  const n = v ?? 0
  if (n >= 0.15) return 'bad'
  if (n >= 0.05) return 'warn'
  return 'ok'
}

function formatScore(v?: number | null): string {
  return v === null || v === undefined ? '—' : (v * 100).toFixed(0) + '%'
}

function kbName(kbId?: number | null): string {
  return kbOptions.value.find((k) => k.id === kbId)?.name ?? `知识库 ${kbId}`
}

function shortDate(iso?: string | null): string {
  if (!iso) return ''
  return iso.slice(0, 10)
}

function kbRate(down: number, total: number): string {
  return total ? ((down / total) * 100).toFixed(1) + '%' : '—'
}

function goDocuments() {
  void router.push(`/home/spaces/${spaceId.value}/knowledge-bases`)
}

function goSession(sessionId: string) {
  // 跳回会话：工作台对话页按 session 恢复（query 带 session_id）
  void router.push({ path: '/home/workspace/chat', query: { session_id: sessionId } })
}

async function load() {
  loading.value = true
  try {
    const end = new Date()
    const start = new Date(end.getTime() - rangeDays.value * 24 * 3600 * 1000)
    const data = await spaceStatsApi.getKnowledgeGap({
      spaceId: spaceId.value,
      start: start.toISOString(),
      end: end.toISOString(),
      kb_id: kbFilter.value,
    })
    stats.value = data
    renderTrend()
  } catch (e) {
    console.warn('[SpaceInsight] 看板加载失败', e)
    stats.value = null
  } finally {
    loading.value = false
  }
}

async function loadKbs() {
  try {
    const data = await knowledgeBaseApi.getKnowledgeBases(spaceId.value)
    kbOptions.value = (data.items ?? []).map((k) => ({ id: k.id, name: k.name }))
  } catch {
    kbOptions.value = []
  }
}

// ===== 趋势图（echarts 按需注册 LineChart；颜色从 CSS 变量固化，主题切换重渲染） =====

const trendChartRef = ref<HTMLDivElement>()
let trendChart: echarts.ECharts | null = null

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function renderTrend() {
  const el = trendChartRef.value
  if (!el) return
  const trend = stats.value?.trend ?? []
  if (!trendChart) {
    trendChart = echarts.init(el)
  }
  trendChart.setOption({
    animation: false,
    grid: { left: 40, right: 16, top: 32, bottom: 28 },
    tooltip: { trigger: 'axis' },
    legend: {
      data: ['问答量', '零命中'],
      textStyle: { color: cssVar('--color-text-secondary'), fontSize: 12 },
      top: 0,
    },
    xAxis: {
      type: 'category',
      data: trend.map((t) => t.date),
      axisLabel: { color: cssVar('--color-text-muted'), fontSize: 11 },
      axisLine: { lineStyle: { color: cssVar('--color-border-light') } },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: cssVar('--color-text-muted'), fontSize: 11 },
      splitLine: { lineStyle: { color: cssVar('--color-border-light') } },
    },
    series: [
      {
        name: '问答量',
        type: 'line',
        data: trend.map((t) => t.qa_count),
        smooth: true,
        symbolSize: 5,
        itemStyle: { color: cssVar('--color-primary') },
        areaStyle: { opacity: 0.06 },
      },
      {
        name: '零命中',
        type: 'line',
        data: trend.map((t) => t.zero_hit),
        smooth: true,
        symbolSize: 5,
        itemStyle: { color: cssVar('--color-danger') },
      },
    ],
  })
}

function handleResize() {
  trendChart?.resize()
}

watch([kbFilter, rangeDays], () => void load())
watch(theme, () => renderTrend())

onMounted(async () => {
  window.addEventListener('resize', handleResize)
  await Promise.all([load(), loadKbs()])
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  trendChart?.dispose()
  trendChart = null
})
</script>

<style scoped>
.space-insight {
  max-width: var(--container-width-lg, 1120px);
  margin: 0 auto;
  padding: var(--space-6, 24px);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.insight-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.insight-title {
  margin: 0;
  font-size: 20px;
  color: var(--color-text);
}

.insight-subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--color-text-muted);
}

.insight-filters {
  display: flex;
  gap: 8px;
  align-items: center;
}

.insight-note {
  border-radius: 10px;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

@media (max-width: 768px) {
  .kpi-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .two-col {
    grid-template-columns: 1fr !important;
  }
}

.kpi-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: 12px;
  padding: 16px 18px;
}

.kpi-label {
  font-size: 12px;
  color: var(--color-text-muted);
}

.kpi-value {
  font-size: 26px;
  font-weight: 600;
  color: var(--color-text);
  margin-top: 4px;
  font-variant-numeric: tabular-nums;
}

.kpi-value.kpi-bad {
  color: var(--color-danger);
}

.kpi-sub {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.insight-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: 12px;
  padding: 16px 18px;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 12px;
}

.card-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.trend-chart {
  height: 260px;
  width: 100%;
}

.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.zero-hit-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 320px;
  overflow: auto;
}

.zero-hit-item {
  padding: 8px 10px;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
}

.zero-hit-query {
  font-size: 13px;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.zero-hit-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 6px;
}

.hit-badge {
  font-size: 11px;
  color: var(--color-danger);
  background: var(--color-danger-subtle);
  border-radius: 4px;
  padding: 0 6px;
  font-weight: 600;
}

.meta-text {
  font-size: 11px;
  color: var(--color-text-muted);
}

.low-score-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 320px;
  overflow: auto;
}

.low-score-item {
  padding: 8px 10px;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s;
}

.low-score-item:hover {
  border-color: var(--color-primary);
}

.low-score-snippet {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.low-score-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 6px;
}
</style>
