<template>
  <div class="gap-report-page">
    <PageHeader
      title="知识缺口报告"
      :description="`用户问了但知识库答不上的内容清单——内容建设的直接依据（近 7 天）`"
    >
      <template #actions>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <!-- KPI 行：四统计卡，minmax(0,1fr) 防长内容卡轨道 -->
    <div class="kpi-grid">
      <StatCard label="未获理想回答" :value="String(kpi?.failure_total ?? 0)" hint="失败问答总次数（零命中/低分/点踩）" />
      <StatCard label="内容缺口" :value="String(kpi?.gap_query_count ?? 0)" hint="确认为库里没有的提问次数" />
      <StatCard label="缺口问题数" :value="String(kpi?.gap_cluster_count ?? 0)" hint="去重后的不同问题数" />
      <StatCard
        label="待归因"
        :value="String(kpi?.pending_attribution ?? 0)"
        hint="尚未完成归因的失败问答（归因任务每 30 分钟扫批）"
      />
    </div>

    <!-- 归因分布：chip 行，说明每类的含义与责任方 -->
    <div v-if="distribution.length" class="dist-section">
      <div class="section-title">归因分布</div>
      <div class="dist-chips">
        <div v-for="d in distribution" :key="d.key" class="dist-chip" :class="d.key">
          <span class="dist-label">{{ d.label }}</span>
          <span class="dist-value">{{ d.count }}</span>
        </div>
      </div>
      <div class="dist-legend">
        content_gap=库里没有（补内容） · retrieval_failure=有但没召回（调检索） ·
        quality_decay=内容过期（换新版） · permission_boundary=无权限访问（安全策略）
      </div>
    </div>

    <!-- 缺口清单：核心表——「这周答不上来的 top 是什么」 -->
    <div class="list-section">
      <div class="section-title">内容缺口清单（按提问频次降序）</div>
      <el-table
        v-loading="loading"
        :data="gapItems"
        class="gap-table"
        empty-text="近 7 天没有内容缺口——要么覆盖很全，要么还没有人在问"
      >
        <el-table-column label="用户问题" min-width="280">
          <template #default="{ row }">
            <span class="query-text" :title="row.query">{{ row.query }}</span>
          </template>
        </el-table-column>
        <el-table-column label="提问次数" width="100" align="center">
          <template #default="{ row }">
            <el-tag type="danger" effect="plain" size="small">{{ row.hit_count }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近提问" width="170">
          <template #default="{ row }">
            <span class="time-text">{{ formatTime(row.last_seen) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
/** 知识缺口报告页（kb-ops A2）：失败问答归因分布 + 内容缺口清单 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { spaceStatsApi } from '@/api/knowledge'
import type { KbOpsGapReport } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import StatCard from '@/components/common/StatCard.vue'

const route = useRoute()
const spaceId = Number(route.params.id)

const loading = ref(false)
const report = ref<KbOpsGapReport | null>(null)

const kpi = computed(() => report.value?.kpi)
const gapItems = computed(() => report.value?.gap_items ?? [])

const ATTR_LABELS: Record<string, string> = {
  content_gap: '内容缺口',
  retrieval_failure: '检索失败',
  quality_decay: '内容过期',
  permission_boundary: '权限边界',
  pending: '待归因',
}

const distribution = computed(() => {
  const dist = report.value?.attribution_distribution ?? {}
  return Object.entries(dist)
    .map(([key, count]) => ({ key, label: ATTR_LABELS[key] ?? key, count }))
    .sort((a, b) => b.count - a.count)
})

async function load() {
  loading.value = true
  try {
    report.value = await spaceStatsApi.getGapReport(spaceId)
  } catch {
    report.value = null
  } finally {
    loading.value = false
  }
}

function formatTime(iso: string): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

onMounted(load)
</script>

<style scoped>
.gap-report-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 10px;
}

.dist-section,
.list-section {
  min-width: 0;
}

.dist-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.dist-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--color-border-light);
  background: var(--color-bg-card-elevated);
}

.dist-chip.content_gap {
  border-color: rgba(220, 38, 38, 0.35);
}

.dist-label {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.dist-value {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}

.dist-legend {
  margin-top: 8px;
  font-size: 11px;
  color: var(--color-text-muted);
  word-break: break-word;
}

.query-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text);
}

.time-text {
  font-size: 12px;
  color: var(--color-text-muted);
  white-space: nowrap;
}

/* 窄屏降档：KPI 4→2→1 列 */
@media (max-width: 900px) {
  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 520px) {
  .kpi-grid {
    grid-template-columns: 1fr;
  }
}
</style>
