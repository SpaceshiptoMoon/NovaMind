<template>
  <div class="ops-inbox">
    <!-- ① 结论行：一行健康结论，不是一面墙（score=null 冷启动降级静态提示） -->
    <div class="conclusion-line">
      <template v-if="health && health.score !== null">
        <span class="score-value">{{ Math.round(health.score) }}</span>
        <span
          v-if="health.delta !== null"
          class="score-delta"
          :class="health.delta >= 0 ? 'up' : 'down'"
        >
          {{ health.delta >= 0 ? '↑' : '↓' }}{{ Math.abs(health.delta).toFixed(1) }}
        </span>
        <span class="score-subs">
          <span v-for="(sub, key) in health.subs" :key="key" :title="sub.detail">
            {{ SUB_LABELS[key] ?? key }}
            <b v-if="sub.score !== null" :class="sub.score < 0.6 ? 'sub-low' : 'sub-ok'">
              {{ Math.round(sub.score * 100) }}
            </b>
            <b v-else class="sub-none">待积累</b>
          </span>
        </span>
        <span class="score-weekly">
          本周：缺口转化 {{ health.weekly.gap_converted ?? 0 }} · 复审确认
          {{ health.weekly.review_confirmed ?? 0 }}
          <template v-if="health.weekly.zero_hit_rate !== undefined">
            · 零命中率 {{ (health.weekly.zero_hit_rate * 100).toFixed(1) }}%
          </template>
        </span>
      </template>
      <template v-else>
        <span class="score-value score-value--cold">—</span>
        <span class="score-weekly">
          暂无行为数据：分数将在用户开始检索后积累；静态体检与待办已可用
        </span>
      </template>
      <el-button size="small" :icon="Refresh" :loading="loading" class="refresh-btn" @click="loadAll">
        刷新
      </el-button>
    </div>

    <!-- ② 待办流：混排三源，按影响度排序（清到零即无待办） -->
    <div class="inbox">
      <div class="inbox-head">
        <span>待处理 {{ todoCount }}</span>
        <span v-if="todoCount === 0 && !loading" class="inbox-empty">全部处理完毕</span>
      </div>
      <div class="inbox-list">
        <OpsTodoCard
          v-for="todo in sortedTodos"
          :key="todo.key"
          :kind="todo.kind"
          :title="todo.title"
          :impact="todo.impact"
          :meta="todo.meta"
          :actions="todo.actions"
          :loop="ignoredKeys.has(todo.key) ? { state: 'ignored' } : undefined"
          :busy="busyKey === todo.key"
          @action="(key) => handleAction(todo, key)"
        />
      </div>
      <div v-if="todoCount === 0 && !loading" class="inbox-zero">
        知识库当前没有待处理的运营信号
      </div>
    </div>

    <!-- ③ 分析与明细：折叠区（默认收起——不打扰清待办的人） -->
    <el-collapse v-model="openedPanels" class="detail-collapse">
      <el-collapse-item name="detail" title="查看分析与明细">
        <div class="detail-grid">
          <div class="detail-block">
            <div class="detail-label">检索趋势（近 30 天）</div>
            <OpsTrendChart
              v-if="trendLabels.length"
              title=""
              :labels="trendLabels"
              :series="trendSeries"
              :height="180"
            />
            <div v-else class="detail-empty">暂无检索数据</div>
          </div>
          <div class="detail-block">
            <div class="detail-label">资产账本</div>
            <div v-if="overview" class="ledger">
              <span>生效 {{ overview.documents.active ?? 0 }}</span>
              <span>草稿 {{ overview.documents.draft ?? 0 }}</span>
              <span>被替代 {{ overview.documents.superseded ?? 0 }}</span>
              <span>归档 {{ overview.documents.archived ?? 0 }}</span>
              <span>解析失败 {{ overview.failed_documents.count }}</span>
            </div>
          </div>
          <div class="detail-block">
            <div class="detail-label">下钻</div>
            <div class="drill-links">
              <router-link :to="`/home/spaces/${spaceId}/ops/gaps`">搜索洞察与归因</router-link>
              <router-link :to="`/home/spaces/${spaceId}/ops/queue`">建议队列</router-link>
              <router-link :to="`/home/spaces/${spaceId}/ops/health`">资产健康</router-link>
            </div>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup lang="ts">
/**
 * 运营收件箱（知识运营区默认子页）：结论行 + 待办流 + 折叠明细。
 *
 * 三源待办混排（零命中缺口/复审到期/低分反馈）按影响度排序；内联动作：
 * 复审确认（顺延到期日）/ 归档 / 忽略留痕（事件账本，计入本周战果）/
 * 去归因下钻。健康分来自 health-report 端点（透明四维）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import OpsTodoCard, { type TodoAction } from '@/components/knowledge/ops/OpsTodoCard.vue'
import OpsTrendChart from '@/components/knowledge/ops/OpsTrendChart.vue'
import { spaceStatsApi, documentApi } from '@/api/knowledge'
import type {
  KbOpsDueReview,
  KbOpsGapItem,
  KbOpsHealthReport,
  KbOpsOverview,
  KbOpsTrends,
  LowScoreMessageItem,
} from '@/api/types'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => parseInt(String(route.params.id), 10))

const loading = ref(false)
const health = ref<KbOpsHealthReport | null>(null)
const overview = ref<KbOpsOverview | null>(null)
const trends = ref<KbOpsTrends | null>(null)
const gapItems = ref<KbOpsGapItem[]>([])
const lowScore = ref<LowScoreMessageItem[]>([])
const ignoredKeys = ref(new Set<string>())
const busyKey = ref<string | null>(null)
const openedPanels = ref<string[]>([])

/** 待办统一形状（三源归一） */
interface Todo {
  key: string
  kind: 'gap' | 'review' | 'feedback'
  title: string
  impact: { count: number | string; unit: string; tone: 'danger' | 'warning' | 'neutral' }
  meta?: string
  weight: number
  actions: TodoAction[]
}

const todos = computed<Todo[]>(() => {
  const list: Todo[] = []
  for (const g of gapItems.value) {
    list.push({
      key: `gap:${g.normalized}`,
      kind: 'gap',
      title: g.query,
      impact: { count: g.hit_count, unit: '次搜索', tone: 'danger' },
      meta: '内容缺口：用户在搜而知识库没有',
      weight: g.hit_count * 10,
      actions: [
        { key: 'drill', label: '去归因', primary: true },
        { key: 'ignore', label: '忽略' },
      ],
    })
  }
  for (const r of overview.value?.due_reviews.items ?? []) {
    list.push({
      key: `review:${r.document_id}`,
      kind: 'review',
      title: r.filename,
      impact: {
        count: r.overdue ? '已过期' : '临期',
        unit: r.next_review_at.slice(0, 10),
        tone: 'warning',
      },
      meta: `复审到期 · 知识库 #${r.kb_id}`,
      weight: r.overdue ? 8 : 5,
      actions: [
        { key: 'confirm', label: '确认有效', primary: true },
        { key: 'archive', label: '归档', danger: true },
        { key: 'ignore', label: '忽略' },
      ],
    })
  }
  for (const m of lowScore.value.slice(0, 5)) {
    list.push({
      key: `feedback:${m.message_id}`,
      kind: 'feedback',
      title: m.answer_snippet.slice(0, 40),
      impact: {
        count: m.rating === 'down' ? '点踩' : '低分',
        unit: m.max_score != null ? m.max_score.toFixed(2) : '—',
        tone: 'danger',
      },
      meta: `检索得分低${m.created_at ? ` · ${m.created_at.slice(0, 10)}` : ''}`,
      weight: 3,
      actions: [
        { key: 'drill-doc', label: '回看文档', primary: true },
        { key: 'ignore', label: '忽略' },
      ],
    })
  }
  return list
})

/** 影响度排序（gap 的搜索影响 ×10 权重天然居前） */
const sortedTodos = computed(() => {
  const visible = todos.value.filter((t) => !ignoredKeys.value.has(t.key))
  return [...visible].sort((a, b) => b.weight - a.weight)
})
const todoCount = computed(() => sortedTodos.value.length)

const trendLabels = computed(() => (trends.value?.series ?? []).map((s) => s.date.slice(5)))
const trendSeries = computed(() => [
  { name: '检索量', data: (trends.value?.series ?? []).map((s) => s.query_total), area: true },
  {
    name: '零命中',
    data: (trends.value?.series ?? []).map((s) => s.zero_hit),
    tone: 'danger' as const,
  },
])

const SUB_LABELS: Record<string, string> = {
  retrieval: '检索',
  freshness: '新鲜',
  feedback: '反馈',
  order: '秩序',
}

async function loadAll() {
  loading.value = true
  const sid = spaceId.value
  const [healthR, overviewR, trendsR, gapR, kgR] = await Promise.allSettled([
    spaceStatsApi.getHealthReport(sid),
    spaceStatsApi.getOpsOverview(sid),
    spaceStatsApi.getTrends(sid, { days: 30 }),
    spaceStatsApi.getGapReport(sid),
    spaceStatsApi.getKnowledgeGap({ spaceId: sid }),
  ])
  if (healthR.status === 'fulfilled') health.value = healthR.value
  if (overviewR.status === 'fulfilled') overview.value = overviewR.value
  if (trendsR.status === 'fulfilled') trends.value = trendsR.value
  if (gapR.status === 'fulfilled') gapItems.value = (gapR.value.gap_items ?? []).slice(0, 10)
  if (kgR.status === 'fulfilled') lowScore.value = kgR.value.low_score_messages ?? []
  loading.value = false
}

/** 收件箱动作分发 */
async function handleAction(todo: Todo, action: string) {
  const sid = spaceId.value
  if (action === 'ignore') {
    busyKey.value = todo.key
    try {
      await spaceStatsApi.recordTodoIgnored(sid, {
        kind: todo.kind,
        todo_key: todo.key,
        query: todo.kind === 'gap' ? todo.title : undefined,
      })
      ignoredKeys.value = new Set([...ignoredKeys.value, todo.key])
      ElMessage.success('已忽略（留痕，不再重复提醒）')
    } catch {
      ElMessage.error('忽略失败')
    } finally {
      busyKey.value = null
    }
    return
  }
  if (action === 'undo-ignore') {
    ignoredKeys.value = new Set([...ignoredKeys.value].filter((k) => k !== todo.key))
    return
  }
  if (todo.kind === 'review' && action === 'confirm') {
    const doc = (overview.value?.due_reviews.items ?? []).find(
      (d: KbOpsDueReview) => `review:${d.document_id}` === todo.key,
    )
    if (!doc) return
    busyKey.value = todo.key
    try {
      await documentApi.confirmDocumentReview(sid, doc.kb_id, doc.document_id)
      ElMessage.success('已确认复审，到期日已顺延')
      await loadAll()
    } catch {
      ElMessage.error('确认失败')
    } finally {
      busyKey.value = null
    }
    return
  }
  if (todo.kind === 'review' && action === 'archive') {
    const doc = (overview.value?.due_reviews.items ?? []).find(
      (d: KbOpsDueReview) => `review:${d.document_id}` === todo.key,
    )
    if (!doc) return
    busyKey.value = todo.key
    try {
      await documentApi.transitionDocumentLifecycle(sid, doc.kb_id, doc.document_id, 'archive')
      ElMessage.success('已归档（退出检索召回）')
      await loadAll()
    } catch {
      ElMessage.error('归档失败')
    } finally {
      busyKey.value = null
    }
    return
  }
  if (action === 'drill') {
    void router.push(`/home/spaces/${sid}/ops/gaps`)
    return
  }
  if (action === 'drill-doc') {
    void router.push(`/home/spaces/${sid}/knowledge-bases`)
  }
}

onMounted(() => {
  void loadAll()
})
</script>

<style scoped>
.ops-inbox {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ① 结论行：一行，非卡片墙 */
.conclusion-line {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.refresh-btn {
  margin-left: auto;
}

.score-value {
  font-family: var(--font-display);
  font-size: 32px;
  font-weight: var(--weight-bold);
  font-variant-numeric: tabular-nums;
  color: var(--color-text);
  line-height: 1;
}

.score-value--cold {
  color: var(--color-text-faint);
}

.score-delta {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  font-variant-numeric: tabular-nums;
}

.score-delta.up {
  color: var(--color-success);
}

.score-delta.down {
  color: var(--color-danger);
}

.score-subs {
  display: inline-flex;
  gap: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.score-subs b {
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-semibold);
}

.sub-ok {
  color: var(--color-text);
}

.sub-low {
  color: var(--color-warning);
}

.sub-none {
  color: var(--color-text-faint);
  font-weight: var(--weight-normal);
}

.score-weekly {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

/* ② 待办流 */
.inbox-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.inbox-empty {
  font-size: var(--text-sm);
  font-weight: var(--weight-normal);
  color: var(--color-success);
}

.inbox-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.inbox-zero {
  padding: var(--space-8);
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-faint);
  background: var(--color-bg-card);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-lg);
}

/* ③ 折叠明细 */
.detail-collapse {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
}

.detail-collapse :deep(.el-collapse-item__header) {
  padding: 0 var(--space-4);
  background: transparent;
  border: none;
}

.detail-collapse :deep(.el-collapse-item__wrap) {
  background: transparent;
  border: none;
}

.detail-collapse :deep(.el-collapse-item__content) {
  padding: var(--space-2) var(--space-4) var(--space-4);
}

.detail-grid {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  gap: var(--space-4);
}

.detail-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-bottom: var(--space-2);
}

.detail-empty {
  font-size: var(--text-sm);
  color: var(--color-text-faint);
  padding: var(--space-4) 0;
}

.ledger {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
}

.drill-links {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.drill-links a {
  font-size: var(--text-sm);
  color: var(--color-primary);
  text-decoration: none;
}

.drill-links a:hover {
  text-decoration: underline;
}

@media (max-width: 900px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
