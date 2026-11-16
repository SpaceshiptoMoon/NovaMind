<template>
  <div class="ops-inbox">
    <!-- ⓪ 冷启动横幅：stage 未就绪时给检查清单，就绪后消失 -->
    <div v-if="onboarding && onboarding.stage !== 'ready'" class="onboarding-banner" :class="`stage-${onboarding.stage}`">
      <div class="ob-head">
        <span class="ob-title">{{ ONBOARDING_TITLES[onboarding.stage] }}</span>
        <span class="ob-next">{{ onboarding.next_step }}</span>
      </div>
      <div class="ob-checks">
        <div v-for="check in onboarding.checks" :key="check.key" class="ob-check" :class="{ ok: check.ok }">
          <span class="ob-check-dot">{{ check.ok ? '✓' : '○' }}</span>
          <span class="ob-check-label">{{ check.label }}</span>
          <span class="ob-check-detail">{{ check.detail }}</span>
          <span v-if="!check.ok && check.action_hint" class="ob-check-hint">{{ check.action_hint }}</span>
        </div>
      </div>
    </div>

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
      <router-link class="bench-link" :to="`/home/spaces/${spaceId}/ops/workbench`">工作台</router-link>
      <el-button size="small" :icon="Refresh" :loading="loading" class="refresh-btn" @click="loadAll">
        刷新
      </el-button>
    </div>

    <!-- ② 待办流：统一端点一次取全（三源混排+影响度排序后端化） -->
    <div class="inbox">
      <div class="inbox-head">
        <span>待处理 {{ todoCount }}</span>
        <span v-if="todoCount > 0" class="inbox-empty">按影响度排序</span>
      </div>
      <div class="inbox-list">
        <OpsTodoCard
          v-for="todo in uiTodos"
          :key="todo.todo_key"
          :kind="todo.kind"
          :title="todo.title"
          :impact="todo.impact"
          :meta="todo.meta ?? undefined"
          :actions="todo.actions"
          :busy="busyKey === todo.todo_key"
          @action="(key) => handleAction(todo, key)"
        />
      </div>
      <div v-if="todoCount === 0 && !loading" class="inbox-zero">
        知识库当前没有待处理的运营信号
      </div>

      <!-- 忽略区：留痕可撤销（跨会话持久） -->
      <div v-if="ignoredTodos.length" class="ignored-box">
        <div class="ignored-title">已忽略 {{ ignoredTodos.length }}（留痕，可撤销）</div>
        <div v-for="item in ignoredTodos" :key="item.todo_key" class="ignored-row">
          <span class="ignored-kind">{{ KIND_LABELS[item.kind] ?? item.kind }}</span>
          <span class="ignored-key">{{ item.todo_key }}</span>
          <span v-if="item.reason" class="ignored-reason">{{ REASON_LABELS[item.reason] ?? item.reason }}</span>
          <el-button link size="small" class="ignored-undo" @click="handleUnignore(item)">撤销</el-button>
        </div>
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

    <!-- 忽略原因选择：判例是自动分诊的训练燃料 -->
    <el-dialog v-model="ignoreDialogVisible" title="忽略这条待办" width="420px" append-to-body>
      <div class="ignore-dialog-body">
        <p class="ignore-target">{{ ignoreTarget?.title }}</p>
        <p class="ignore-hint">选择忽略原因（留痕可撤销，帮助系统学会自动分诊）：</p>
        <div class="reason-buttons">
          <el-button @click="confirmIgnore('one_shot')">一次性提问</el-button>
          <el-button @click="confirmIgnore('non_kb')">非知识需求</el-button>
          <el-button @click="confirmIgnore('false_positive')">误报</el-button>
        </div>
        <el-button link size="small" class="skip-reason" @click="confirmIgnore(undefined)">
          不选原因，直接忽略
        </el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 运营收件箱（知识运营区默认子页）：冷启动横幅 + 结论行 + 待办流 + 折叠明细。
 *
 * 待办来自统一端点（三源聚合/忽略过滤/影响度排序全部后端化）；忽略需选
 * 原因（状态表持久 + 账本留痕，跨会话/跨用户可见），撤销删行恢复可见。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import OpsTodoCard, { type TodoAction } from '@/components/knowledge/ops/OpsTodoCard.vue'
import OpsTrendChart from '@/components/knowledge/ops/OpsTrendChart.vue'
import { spaceStatsApi, documentApi } from '@/api/knowledge'
import type {
  IgnoredTodoItem,
  KbOpsHealthReport,
  KbOpsOverview,
  KbOpsTrends,
  OpsOnboarding,
  OpsTodoItem,
  OpsTodoList,
} from '@/api/types'

type IgnoreReason = 'one_shot' | 'non_kb' | 'false_positive'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => parseInt(String(route.params.id), 10))

const loading = ref(false)
const health = ref<KbOpsHealthReport | null>(null)
const overview = ref<KbOpsOverview | null>(null)
const trends = ref<KbOpsTrends | null>(null)
const todoList = ref<OpsTodoList | null>(null)
const onboarding = ref<OpsOnboarding | null>(null)
const busyKey = ref<string | null>(null)
const openedPanels = ref<string[]>([])
const ignoreDialogVisible = ref(false)
const ignoreTarget = ref<OpsTodoItem | null>(null)

/** 各类型待办的内联动作（按钮是交互层，数据/排序/过滤归后端） */
const KIND_ACTIONS: Record<OpsTodoItem['kind'], TodoAction[]> = {
  gap: [
    { key: 'drill', label: '去归因', primary: true },
    { key: 'ignore', label: '忽略' },
  ],
  review: [
    { key: 'confirm', label: '确认有效', primary: true },
    { key: 'archive', label: '归档', danger: true },
    { key: 'ignore', label: '忽略' },
  ],
  feedback: [
    { key: 'drill-doc', label: '回看文档', primary: true },
    { key: 'ignore', label: '忽略' },
  ],
}

const uiTodos = computed(() =>
  (todoList.value?.items ?? []).map((t) => ({ ...t, actions: KIND_ACTIONS[t.kind] ?? [] })),
)
const todoCount = computed(() => uiTodos.value.length)
const ignoredTodos = computed<IgnoredTodoItem[]>(() => todoList.value?.ignored ?? [])

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

const ONBOARDING_TITLES: Record<string, string> = {
  empty: '运营未起步',
  collecting: '行为数据采集期',
}

const KIND_LABELS: Record<string, string> = {
  gap: '缺口',
  review: '复审',
  feedback: '反馈',
}

const REASON_LABELS: Record<string, string> = {
  one_shot: '一次性提问',
  non_kb: '非知识需求',
  false_positive: '误报',
}

async function loadAll() {
  loading.value = true
  const sid = spaceId.value
  const [healthR, overviewR, trendsR, todosR, onbR] = await Promise.allSettled([
    spaceStatsApi.getHealthReport(sid),
    spaceStatsApi.getOpsOverview(sid),
    spaceStatsApi.getTrends(sid, { days: 30 }),
    spaceStatsApi.getOpsTodos(sid),
    spaceStatsApi.getOnboarding(sid),
  ])
  if (healthR.status === 'fulfilled') health.value = healthR.value
  if (overviewR.status === 'fulfilled') overview.value = overviewR.value
  if (trendsR.status === 'fulfilled') trends.value = trendsR.value
  if (todosR.status === 'fulfilled') todoList.value = todosR.value
  if (onbR.status === 'fulfilled') onboarding.value = onbR.value
  loading.value = false
}

/** 只重拉待办面（处置动作后的轻刷新） */
async function reloadTodos() {
  const sid = spaceId.value
  const [todosR, onbR] = await Promise.allSettled([
    spaceStatsApi.getOpsTodos(sid),
    spaceStatsApi.getOnboarding(sid),
  ])
  if (todosR.status === 'fulfilled') todoList.value = todosR.value
  if (onbR.status === 'fulfilled') onboarding.value = onbR.value
}

/** 收件箱动作分发 */
async function handleAction(todo: OpsTodoItem, action: string) {
  const sid = spaceId.value
  if (action === 'ignore') {
    ignoreTarget.value = todo
    ignoreDialogVisible.value = true
    return
  }
  if (todo.kind === 'review' && action === 'confirm') {
    const documentId = Number(todo.payload.document_id)
    const kbId = Number(todo.payload.kb_id)
    if (!documentId || !kbId) return
    busyKey.value = todo.todo_key
    try {
      await documentApi.confirmDocumentReview(sid, kbId, documentId)
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
    const documentId = Number(todo.payload.document_id)
    const kbId = Number(todo.payload.kb_id)
    if (!documentId || !kbId) return
    busyKey.value = todo.todo_key
    try {
      await documentApi.transitionDocumentLifecycle(sid, kbId, documentId, 'archive')
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

/** 提交忽略（带原因或跳过），成功后重拉待办面 */
async function confirmIgnore(reason?: IgnoreReason) {
  const todo = ignoreTarget.value
  if (!todo) return
  const sid = spaceId.value
  busyKey.value = todo.todo_key
  try {
    await spaceStatsApi.recordTodoIgnored(sid, {
      kind: todo.kind,
      todo_key: todo.todo_key,
      query: todo.kind === 'gap' ? String(todo.payload.query ?? todo.title) : undefined,
      reason,
    })
    ElMessage.success('已忽略（留痕，不再重复提醒）')
    ignoreDialogVisible.value = false
    ignoreTarget.value = null
    await reloadTodos()
  } catch {
    ElMessage.error('忽略失败')
  } finally {
    busyKey.value = null
  }
}

/** 撤销忽略：删状态行，待办恢复可见 */
async function handleUnignore(item: IgnoredTodoItem) {
  const sid = spaceId.value
  try {
    await spaceStatsApi.unignoreTodo(sid, {
      kind: item.kind as 'gap' | 'review' | 'feedback',
      todo_key: item.todo_key,
    })
    ElMessage.success('已撤销，待办恢复可见')
    await reloadTodos()
  } catch {
    ElMessage.error('撤销失败')
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

/* ⓪ 冷启动横幅 */
.onboarding-banner {
  padding: var(--space-3) var(--space-4);
  background: var(--color-warning-subtle);
  border: 1px solid var(--color-warning);
  border-radius: var(--radius-lg);
}

.onboarding-banner.stage-collecting {
  background: var(--color-info-subtle);
  border-color: var(--color-border);
}

.ob-head {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.ob-title {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-warning);
}

.stage-collecting .ob-title {
  color: var(--color-text-secondary);
}

.ob-next {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.ob-checks {
  margin-top: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.ob-check {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  font-size: var(--text-sm);
  flex-wrap: wrap;
}

.ob-check.ok {
  color: var(--color-text-faint);
}

.ob-check:not(.ok) {
  color: var(--color-text);
}

.ob-check-dot {
  font-size: var(--text-xs);
  color: var(--color-success);
}

.ob-check:not(.ok) .ob-check-dot {
  color: var(--color-text-faint);
}

.ob-check-label {
  font-weight: var(--weight-medium);
  min-width: 4em;
}

.ob-check-detail {
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.ob-check-hint {
  color: var(--color-text-faint);
  font-size: var(--text-xs);
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

.bench-link {
  margin-left: auto;
  font-size: var(--text-sm);
  color: var(--color-primary);
  text-decoration: none;
  flex-shrink: 0;
}

.bench-link:hover {
  text-decoration: underline;
}

.refresh-btn {
  flex-shrink: 0;
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
  color: var(--color-text-faint);
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

/* 忽略区 */
.ignored-box {
  margin-top: var(--space-3);
  padding: var(--space-2) var(--space-4);
  background: var(--color-bg-card);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-lg);
}

.ignored-title {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
  margin-bottom: var(--space-1);
}

.ignored-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-sm);
  padding: var(--space-1) 0;
}

.ignored-kind {
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.ignored-key {
  color: var(--color-text-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ignored-reason {
  color: var(--color-warning);
  font-size: var(--text-xs);
  flex-shrink: 0;
}

.ignored-undo {
  margin-left: auto;
  flex-shrink: 0;
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

/* 忽略原因弹窗 */
.ignore-dialog-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ignore-target {
  font-size: var(--text-sm);
  color: var(--color-text);
  font-weight: var(--weight-medium);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ignore-hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.reason-buttons {
  display: flex;
  gap: var(--space-2);
}

.skip-reason {
  align-self: flex-start;
  color: var(--color-text-faint);
}

@media (max-width: 900px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
