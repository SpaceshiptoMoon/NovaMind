<template>
  <div class="ops-workbench">
    <!-- 页头：工作台定位 + 刷新 -->
    <div class="wb-head">
      <div>
        <div class="wb-title">运营工作台</div>
        <div class="wb-sub">运营平台五模块枢纽：看板 · 质检 · 处置 · 验证 · 账本</div>
      </div>
      <el-button size="small" :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
    </div>

    <!-- 冷启动提示（stage≠ready 一行带出，清单在收件箱横幅） -->
    <div v-if="onboarding && onboarding.stage !== 'ready'" class="wb-coldstart">
      <span class="wb-coldstart-tag">{{ stageLabel }}</span>
      <span class="wb-coldstart-text">{{ onboarding.next_step }}</span>
      <router-link class="wb-coldstart-link" :to="`/home/spaces/${spaceId}/ops`">
        查看引导清单
      </router-link>
    </div>

    <!-- 五模块登记行：一行一模块（定位+摘要+下钻），不是卡片墙 -->
    <div class="wb-modules">
      <div
        v-for="mod in modules"
        :key="mod.key"
        class="wb-row"
        :class="{ 'is-drillable': mod.to }"
        @click="mod.to && router.push(String(mod.to))"
      >
        <div class="wb-row-id">
          <span class="wb-row-dot" :style="{ background: mod.color }"></span>
          <div>
            <div class="wb-row-name">{{ mod.name }}</div>
            <div class="wb-row-role">{{ mod.role }}</div>
          </div>
        </div>
        <div class="wb-row-summary">
          <template v-if="mod.summary">
            <span
              v-for="(part, i) in mod.summary"
              :key="i"
              class="wb-sum-part"
              :class="{ 'sum-bad': part.bad }"
            >
              {{ part.text }}<b v-if="part.num !== undefined" class="sum-num">{{ part.num }}</b>{{ part.unit }}
            </span>
          </template>
          <span v-else class="wb-sum-loading">{{ loading ? '加载中…' : '暂无数据' }}</span>
        </div>
        <div class="wb-row-drill">
          <span v-if="mod.to" class="drill-label">{{ mod.drillLabel }}</span>
          <span v-else-if="mod.hint" class="drill-hint">{{ mod.hint }}</span>
        </div>
      </div>
    </div>

    <!-- 脚注：模块数据口径 -->
    <div class="wb-footnote">
      各模块计数与事件账本同源（口径唯一）；处置动作的验证状态（干预回看）随下批次接入，
      当前以本周战果计数呈现。
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 运营工作台：运营平台五模块的枢纽页（用户定稿的模块划分即信息架构）。
 *
 * 一行一模块（看板=统计监控/质检=内容诊断/处置=待办行动/验证=效果闭环/
 * 账本=事件底座），每行给结论摘要与下钻；数据全部来自现有 kb-ops 端点，
 * 失败静默降级为「暂无数据」。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { spaceStatsApi } from '@/api/knowledge'
import type { KbOpsBadgeCounts, KbOpsHealthReport, OpsOnboarding, OpsTodoList } from '@/api/types'

interface SumPart {
  text?: string
  num?: number | string
  unit?: string
  bad?: boolean
}

interface WorkbenchModule {
  key: string
  name: string
  role: string
  color: string
  summary: SumPart[] | null
  to?: string
  drillLabel?: string
  hint?: string
}

const route = useRoute()
const router = useRouter()
const spaceId = computed(() => parseInt(String(route.params.id), 10))

const loading = ref(false)
const health = ref<KbOpsHealthReport | null>(null)
const badges = ref<KbOpsBadgeCounts | null>(null)
const todos = ref<OpsTodoList | null>(null)
const eventTotal = ref<number | null>(null)
const eventsThisWeek = ref<number | null>(null)
const onboarding = ref<OpsOnboarding | null>(null)

const stageLabel = computed(
  () => (onboarding.value?.stage === 'empty' ? '运营未起步' : '行为数据采集期'),
)

/** 五模块行（顺序即 PDCA 流转：看→诊→处→验，账本垫底） */
const modules = computed<WorkbenchModule[]>(() => {
  const sid = spaceId.value
  const base = `/home/spaces/${sid}/ops`

  const h = health.value
  const boardSummary: SumPart[] | null = h
    ? [
        { text: '健康分' },
        h.score !== null
          ? { num: Math.round(h.score), bad: h.score < 60 }
          : { text: '冷启动待积累' },
        ...(h.delta !== null
          ? [{ text: h.delta >= 0 ? `↑${h.delta.toFixed(1)}` : `↓${Math.abs(h.delta).toFixed(1)}` }]
          : []),
        ...(h.weekly.zero_hit_rate !== undefined
          ? [{ text: '· 零命中率', num: `${(h.weekly.zero_hit_rate * 100).toFixed(1)}%` }]
          : []),
      ]
    : null

  const b = badges.value
  const qcTotal = b ? b.due_reviews + b.open_suggestions + b.failed_documents : null
  const qcSummary: SumPart[] | null = b
    ? [
        { text: '信号' },
        { num: qcTotal ?? 0, bad: (qcTotal ?? 0) > 0, unit: ' 项' },
        { text: '：内容缺口' },
        { num: b.gap_clusters },
        { text: '复审到期' },
        { num: b.due_reviews },
        { text: '待处置建议' },
        { num: b.open_suggestions },
        { text: '解析失败' },
        { num: b.failed_documents },
      ]
    : null

  const t = todos.value
  const highImpact = t ? t.items.filter((i) => i.weight >= 8).length : 0
  const doSummary: SumPart[] | null = t
    ? [
        { text: '待办' },
        { num: t.total, bad: t.total > 0, unit: ' 条' },
        ...(t.total > 0 ? [{ text: `（高影响 ${highImpact}）` }] : []),
        ...(t.ignored.length ? [{ text: '· 已忽略', num: t.ignored.length }] : []),
      ]
    : null

  const verifySummary: SumPart[] | null = h
    ? [
        { text: '本周战果：缺口转化' },
        { num: h.weekly.gap_converted ?? 0 },
        { text: '复审确认' },
        { num: h.weekly.review_confirmed ?? 0 },
        { text: '忽略留痕' },
        { num: h.weekly.todo_ignored ?? 0 },
      ]
    : null

  const ledgerSummary: SumPart[] | null =
    eventTotal.value !== null
      ? [
          { text: '累计事件' },
          { num: eventTotal.value.toLocaleString(), unit: ' 条' },
          ...(eventsThisWeek.value !== null
            ? [{ text: '· 本周新增', num: eventsThisWeek.value }]
            : []),
        ]
      : null

  return [
    {
      key: 'board',
      name: '看板',
      role: '统计监控',
      color: 'var(--color-primary)',
      summary: boardSummary,
      to: `${base}/health`,
      drillLabel: '资产健康',
    },
    {
      key: 'qc',
      name: '质检',
      role: '内容诊断',
      color: 'var(--color-warning)',
      summary: qcSummary,
      to: `${base}/queue`,
      drillLabel: '质检中心',
    },
    {
      key: 'dispose',
      name: '处置',
      role: '待办行动',
      color: 'var(--color-danger)',
      summary: doSummary,
      to: `${base}`,
      drillLabel: '进收件箱',
    },
    {
      key: 'verify',
      name: '验证',
      role: '效果闭环',
      color: 'var(--color-success)',
      summary: verifySummary,
      hint: '干预回看随下批次接入',
    },
    {
      key: 'ledger',
      name: '账本',
      role: '事件底座',
      color: 'var(--color-text-faint)',
      summary: ledgerSummary,
      hint: '单一事实来源',
    },
  ]
})

async function loadAll() {
  loading.value = true
  const sid = spaceId.value
  const weekAgo = new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString()
  const [healthR, badgeR, todosR, eventsR, weekR, onbR] = await Promise.allSettled([
    spaceStatsApi.getHealthReport(sid),
    spaceStatsApi.getBadgeCounts(sid),
    spaceStatsApi.getOpsTodos(sid),
    spaceStatsApi.getEvents(sid, { limit: 1 }),
    spaceStatsApi.getEvents(sid, { start: weekAgo, limit: 1 }),
    spaceStatsApi.getOnboarding(sid),
  ])
  if (healthR.status === 'fulfilled') health.value = healthR.value
  if (badgeR.status === 'fulfilled') badges.value = badgeR.value
  if (todosR.status === 'fulfilled') todos.value = todosR.value
  if (eventsR.status === 'fulfilled') eventTotal.value = eventsR.value.total ?? null
  if (weekR.status === 'fulfilled') eventsThisWeek.value = weekR.value.total ?? null
  if (onbR.status === 'fulfilled') onboarding.value = onbR.value
  loading.value = false
}

onMounted(() => {
  void loadAll()
})
</script>

<style scoped>
.ops-workbench {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* 页头 */
.wb-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.wb-title {
  font-size: var(--text-xl);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.wb-sub {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-top: var(--space-1);
}

/* 冷启动提示行 */
.wb-coldstart {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding: var(--space-2) var(--space-4);
  background: var(--color-info-subtle);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  font-size: var(--text-sm);
}

.wb-coldstart-tag {
  color: var(--color-text-secondary);
  font-weight: var(--weight-semibold);
}

.wb-coldstart-text {
  color: var(--color-text-muted);
}

.wb-coldstart-link {
  margin-left: auto;
  color: var(--color-primary);
  text-decoration: none;
  flex-shrink: 0;
}

.wb-coldstart-link:hover {
  text-decoration: underline;
}

/* 模块登记行 */
.wb-modules {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.wb-row {
  display: flex;
  align-items: center;
  gap: var(--space-5);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
  transition: background 0.15s, border-color 0.15s;
  cursor: default;
}

.wb-row:last-child {
  border-bottom: none;
}

.wb-row.is-drillable {
  cursor: pointer;
}

.wb-row.is-drillable:hover {
  background: var(--color-bg-hover);
  box-shadow: inset 2px 0 0 var(--color-primary);
}

/* 模块标识区 */
.wb-row-id {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 148px;
  flex-shrink: 0;
}

.wb-row-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.wb-row-name {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  line-height: 1.3;
}

.wb-row-role {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

/* 摘要区 */
.wb-row-summary {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.sum-num {
  color: var(--color-text);
  font-weight: var(--weight-semibold);
  margin: 0 2px;
}

.sum-bad {
  color: var(--color-danger);
}

.sum-bad .sum-num {
  color: var(--color-danger);
}

.wb-sum-loading {
  color: var(--color-text-faint);
}

/* 下钻区 */
.wb-row-drill {
  flex-shrink: 0;
  min-width: 96px;
  text-align: right;
}

.drill-label {
  color: var(--color-primary);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
}

.wb-row.is-drillable:hover .drill-label {
  text-decoration: underline;
}

.drill-hint {
  color: var(--color-text-faint);
  font-size: var(--text-xs);
}

.wb-footnote {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
  padding: 0 var(--space-1);
}

@media (max-width: 760px) {
  .wb-row {
    flex-wrap: wrap;
  }

  .wb-row-summary {
    order: 3;
    width: 100%;
  }
}
</style>
