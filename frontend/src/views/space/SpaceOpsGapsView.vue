<template>
  <div class="ops-gaps" v-loading="loading">
    <!-- KPI 行 -->
    <div class="kpi-grid">
      <OpsKpiTile
        label="未获理想回答"
        :value="String(kpi?.failure_total ?? '—')"
        sub="零命中+低分+点踩"
      />
      <OpsKpiTile
        label="待归因"
        :value="String(kpi?.pending_attribution ?? '—')"
        sub="归因任务自动补齐"
      />
      <OpsKpiTile
        label="缺口问题数"
        :value="String(kpi?.gap_cluster_count ?? '—')"
        sub="内容缺口聚类"
      />
      <OpsKpiTile
        label="缺口提问次数"
        :value="String(kpi?.gap_query_count ?? '—')"
        sub="涉及提问总量"
      />
    </div>

    <!-- 归因分布 -->
    <div class="attr-row">
      <span class="attr-label">归因分布</span>
      <span
        v-for="chip in attributionChips"
        :key="chip.key"
        class="attr-chip"
        :class="{ 'attr-chip--bad': chip.key === 'content_gap' && chip.count > 0 }"
      >
        {{ chip.label }} <b>{{ chip.count }}</b>
      </span>
      <span v-if="!attributionChips.length" class="attr-empty">近 7 天无失败问答</span>
    </div>

    <!-- 缺口清单 -->
    <div class="ops-panel">
      <div class="panel-head">
        <div class="panel-head-text">
          <div class="panel-title">内容缺口清单</div>
          <p class="panel-desc">
            失败问答按问题聚类（频次降序）。补充文档后用「转测试集」生成命中验证用例
          </p>
        </div>
        <div class="panel-actions">
          <el-button size="small" :disabled="!gapItems.length" @click="exportGapsCsv"
            >导出 CSV</el-button
          >
          <el-button
            size="small"
            type="primary"
            plain
            :disabled="!gapItems.length"
            @click="openConvertDialog"
          >
            转测试集
          </el-button>
        </div>
      </div>
      <el-table :data="gapItems" empty-text="近 7 天没有内容缺口">
        <el-table-column label="用户问题" min-width="280">
          <template #default="{ row }">
            <span class="gap-query" :title="row.query">{{ row.query }}</span>
          </template>
        </el-table-column>
        <el-table-column label="提问次数" width="100" align="center">
          <template #default="{ row }">
            <el-tag type="danger" size="small" effect="plain">×{{ row.hit_count }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近提问" width="120">
          <template #default="{ row }">{{ shortDate(row.last_seen) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-tooltip content="去知识库补文档（问题原文已复制）" placement="top">
              <el-button size="small" text type="primary" @click="copyQuery(row.query)">
                补文档
              </el-button>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 零命中 Top + 低分明细 -->
    <div class="two-col">
      <div class="ops-panel">
        <div class="panel-title">零命中问题 Top {{ zeroHitQueries.length }}</div>
        <p class="panel-desc">按原始问题精确聚合计数（未归一化）</p>
        <el-empty v-if="!zeroHitQueries.length" description="暂无零命中记录" :image-size="64" />
        <div v-else class="scroll-list">
          <div v-for="(q, i) in zeroHitQueries" :key="i" class="mini-item">
            <span class="mini-name" :title="q.query">{{ q.query }}</span>
            <span class="mini-meta">
              <em class="hit-badge">×{{ q.hit_count }}</em>
              {{ shortDate(q.last_seen) }}
            </span>
          </div>
        </div>
      </div>
      <div class="ops-panel">
        <div class="panel-title">点踩 / 低分回答</div>
        <el-empty
          v-if="!lowScoreMessages.length"
          description="暂无点踩或低分回答"
          :image-size="64"
        />
        <div v-else class="scroll-list">
          <div
            v-for="m in lowScoreMessages"
            :key="m.message_id"
            class="mini-item mini-item--click"
            title="跳回会话查看"
            @click="goSession(m.session_id)"
          >
            <span class="mini-snippet">{{ m.answer_snippet }}</span>
            <span class="mini-meta">
              <el-tag v-if="m.rating === 'down'" type="danger" size="small" effect="plain"
                >点踩</el-tag
              >
              <el-tag v-else type="warning" size="small" effect="plain">
                低分 {{ formatScore(m.max_score) }}
              </el-tag>
              {{ shortDate(m.created_at) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 检索事件账本 -->
    <div class="ops-panel">
      <div class="panel-head">
        <div class="panel-head-text">
          <div class="panel-title">检索事件账本</div>
          <p class="panel-desc">逐条检索明细（展开看命中片段），归因与复核的原始证据</p>
        </div>
        <div class="panel-actions">
          <el-select
            v-model="eventTypeFilter"
            placeholder="全部类型"
            clearable
            style="width: 140px"
            @change="reloadEvents"
          >
            <el-option
              v-for="(label, key) in EVENT_TYPE_LABELS"
              :key="key"
              :label="label"
              :value="key"
            />
          </el-select>
          <el-button size="small" :disabled="!events.length" @click="exportEventsCsv"
            >导出 CSV</el-button
          >
        </div>
      </div>
      <el-table :data="events" empty-text="时间窗内暂无事件">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div v-if="hitList(row).length" class="hits-panel">
              <div v-for="(hit, i) in hitList(row)" :key="i" class="hit-row">
                <span class="hit-rank">#{{ i + 1 }}</span>
                <span class="hit-doc">{{ hit.document_name ?? docName(hit.document_id) }}</span>
                <el-tag v-if="hit.score !== null" size="small" effect="plain">
                  {{ formatScore(hit.score) }}
                </el-tag>
                <span class="hit-snippet">{{ hit.snippet }}</span>
              </div>
            </div>
            <div v-else class="hits-empty">该事件无命中明细（零命中或非检索类事件）</div>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ shortTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{
              EVENT_TYPE_LABELS[row.event_type] ?? row.event_type
            }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="查询 / 信号" min-width="240">
          <template #default="{ row }">
            <span class="gap-query" :title="row.query_text ?? ''">{{ row.query_text ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="检索结果" min-width="160">
          <template #default="{ row }">
            <span v-if="row.extra?.results_count !== undefined" class="mini-meta">
              命中 {{ row.extra.results_count }} 条
              <template v-if="row.extra.max_score !== null && row.extra.max_score !== undefined">
                · 最高 {{ formatScore(row.extra.max_score) }}
              </template>
            </span>
            <span v-else class="mini-meta">—</span>
          </template>
        </el-table-column>
      </el-table>
      <Pagination
        v-model:page="eventPage"
        :page-size="EVENTS_PAGE_SIZE"
        :total="eventsTotal"
        layout="prev, pager, next, total"
        @change="loadEvents"
      />
    </div>

    <!-- 转测试集弹窗 -->
    <el-dialog v-model="convertVisible" title="缺口转测试用例" width="480">
      <p class="dialog-desc">
        把近 7 天缺口清单（{{ gapItems.length }} 个问题）整体转成检索命中验证型用例：
        补充文档后，这些问题的检索应能命中。用例会追加进所选知识库的测试集，作为回归护栏。
      </p>
      <el-form label-width="90px">
        <el-form-item label="目标知识库" required>
          <el-select
            v-model="convertKbId"
            placeholder="选择知识库"
            style="width: 100%"
            @change="convertTestSetId = undefined"
          >
            <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="测试集">
          <el-select
            v-model="convertTestSetId"
            placeholder="不选则创建新测试集"
            clearable
            style="width: 100%"
            :loading="testSetsLoading"
          >
            <el-option
              v-for="ts in testSetOptions"
              :key="ts.id"
              :label="`${ts.name}（${ts.total_cases} 例）`"
              :value="ts.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="convertVisible = false">取消</el-button>
        <el-button type="primary" :loading="converting" :disabled="!convertKbId" @click="doConvert">
          {{ convertTestSetId ? '追加上去' : '创建测试集' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 缺口与失败页：KPI + 归因分布 → 缺口任务卡（转测试集 flywheel）→
 * 零命中/低分明细 → 检索事件账本（原始证据下钻）。
 *
 * 「补文档」把问题原文写入剪贴板再跳知识库页——动作预填而非裸跳转。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import OpsKpiTile from '@/components/knowledge/ops/OpsKpiTile.vue'
import Pagination from '@/components/common/Pagination.vue'
import { evaluationApi, knowledgeBaseApi, spaceStatsApi } from '@/api/knowledge'
import { useOpsDocNames } from '@/composables/useOpsDocNames'
import { exportCsv } from '@/utils/csv'
import type { KbOpsEvent, KnowledgeGapStatsResponse, TestSet } from '@/api/types'

const EVENTS_PAGE_SIZE = 20

const EVENT_TYPE_LABELS: Record<string, string> = {
  query: '检索',
  query_reformulate: '提问改写',
  citation_click: '引用点击',
  attribution: '归因',
}

const ATTR_LABELS: Record<string, string> = {
  content_gap: '内容缺口',
  retrieval_failure: '检索失败',
  quality_decay: '内容失效',
  permission_boundary: '权限边界',
  pending: '待归因',
}

const route = useRoute()
const router = useRouter()
const spaceId = computed(() => parseInt(String(route.params.id), 10))

const { resolveDocNames, docName } = useOpsDocNames(spaceId)

const loading = ref(false)
const gapReport = ref<Awaited<ReturnType<typeof spaceStatsApi.getGapReport>> | null>(null)
const gapStats = ref<KnowledgeGapStatsResponse | null>(null)
const kpi = computed(() => gapReport.value?.kpi)
const gapItems = computed(() => gapReport.value?.gap_items ?? [])

const attributionChips = computed(() => {
  const dist = gapReport.value?.attribution_distribution ?? {}
  return Object.entries(dist)
    .map(([key, count]) => ({ key, label: ATTR_LABELS[key] ?? key, count }))
    .sort((a, b) => b.count - a.count)
})

const zeroHitQueries = computed(() => gapStats.value?.zero_hit_queries ?? [])
const lowScoreMessages = computed(() => gapStats.value?.low_score_messages ?? [])

// ===== 事件账本 =====

const events = ref<KbOpsEvent[]>([])
const eventsTotal = ref(0)
const eventPage = ref(1)
const eventTypeFilter = ref<string | undefined>(undefined)

async function loadEvents(): Promise<void> {
  try {
    const data = await spaceStatsApi.getEvents(spaceId.value, {
      event_type: eventTypeFilter.value,
      limit: EVENTS_PAGE_SIZE,
      offset: (eventPage.value - 1) * EVENTS_PAGE_SIZE,
    })
    events.value = data.items ?? []
    eventsTotal.value = data.total
  } catch (e) {
    console.warn('[SpaceOpsGaps] 事件加载失败', e)
    events.value = []
    eventsTotal.value = 0
  }
}

function reloadEvents(): void {
  eventPage.value = 1
  void loadEvents()
}

function hitList(row: KbOpsEvent) {
  return row.extra?.hits ?? []
}

// ===== 转测试集 =====

const convertVisible = ref(false)
const convertKbId = ref<number | undefined>(undefined)
const convertTestSetId = ref<number | undefined>(undefined)
const converting = ref(false)
const kbOptions = ref<Array<{ id: number; name: string }>>([])
const testSetOptions = ref<TestSet[]>([])
const testSetsLoading = ref(false)

function openConvertDialog(): void {
  convertVisible.value = true
}

/** 选定目标 KB 后拉该库测试集供「追加」选择。 */
async function loadTestSets(kbId: number): Promise<void> {
  testSetsLoading.value = true
  try {
    const data = await evaluationApi.getTestSets(spaceId.value, kbId, { limit: 50 })
    testSetOptions.value = data.items ?? []
  } catch {
    testSetOptions.value = []
  } finally {
    testSetsLoading.value = false
  }
}

async function doConvert(): Promise<void> {
  if (!convertKbId.value) return
  converting.value = true
  try {
    const result = await spaceStatsApi.convertGapToTestSet(
      spaceId.value,
      convertKbId.value,
      convertTestSetId.value,
    )
    ElMessage.success(
      `${result.message}：${result.added_cases} 例（测试集 #${result.test_set_id}）`,
    )
    convertVisible.value = false
  } catch (e) {
    console.warn('[SpaceOpsGaps] 转测试集失败', e)
    ElMessage.error('转换失败，请稍后重试')
  } finally {
    converting.value = false
  }
}

// ===== 动作 =====

async function copyQuery(query: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(query)
    ElMessage.success('问题原文已复制')
  } catch {
    ElMessage.warning('复制失败，请手动记录')
  }
  void router.push(`/home/spaces/${spaceId.value}/knowledge-bases`)
}

function goSession(sessionId: string | null): void {
  if (!sessionId) return
  void router.push({ path: '/home/workspace/chat', query: { session_id: sessionId } })
}

function exportGapsCsv(): void {
  exportCsv(
    '知识缺口清单',
    [
      { key: 'query', label: '用户问题' },
      { key: 'hit_count', label: '提问次数' },
      { key: 'last_seen', label: '最近提问' },
    ],
    gapItems.value,
  )
}

function exportEventsCsv(): void {
  exportCsv(
    '检索事件',
    [
      { key: 'id', label: '事件ID' },
      { key: 'event_type', label: '类型' },
      { key: 'query_text', label: '查询' },
      { key: 'created_at', label: '时间' },
    ],
    events.value.map((e) => ({
      id: e.id,
      event_type: EVENT_TYPE_LABELS[e.event_type] ?? e.event_type,
      query_text: e.query_text ?? '',
      created_at: e.created_at,
    })),
  )
}

// ===== 工具 =====

function shortDate(iso?: string | null): string {
  return iso ? iso.slice(0, 10) : '—'
}

function shortTime(iso?: string | null): string {
  return iso ? iso.slice(0, 16).replace('T', ' ') : '—'
}

function formatScore(v?: number | null): string {
  return v === null || v === undefined ? '—' : `${(v * 100).toFixed(0)}%`
}

// ===== 加载 =====

onMounted(async () => {
  loading.value = true
  const end = new Date()
  const start = new Date(end.getTime() - 7 * 24 * 3600 * 1000)
  try {
    const [gap, stats] = await Promise.all([
      spaceStatsApi.getGapReport(spaceId.value),
      spaceStatsApi.getKnowledgeGap({
        spaceId: spaceId.value,
        start: start.toISOString(),
        end: end.toISOString(),
      }),
    ])
    gapReport.value = gap
    gapStats.value = stats
  } catch (e) {
    console.warn('[SpaceOpsGaps] 加载失败', e)
  } finally {
    loading.value = false
  }
  void loadEvents()
  void resolveDocNames()
  try {
    const kbs = await knowledgeBaseApi.getKnowledgeBases(spaceId.value)
    kbOptions.value = (kbs.items ?? []).map((k) => ({ id: k.id, name: k.name }))
  } catch {
    kbOptions.value = []
  }
})

watch(convertKbId, (kbId) => {
  testSetOptions.value = []
  if (kbId) void loadTestSets(kbId)
})
</script>

<style scoped>
.ops-gaps {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  background: var(--ops-panel);
  border: 1px solid var(--ops-line);
  border-radius: 8px;
  overflow: hidden;
}

.attr-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.attr-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.attr-chip {
  font-size: 12px;
  color: var(--color-text-secondary);
  background: var(--ops-panel);
  border: 1px solid var(--ops-line);
  border-radius: 999px;
  padding: 3px 10px;
}

.attr-chip b {
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

/* 归因分布里只有 content_gap 计数上红字，芯片边框保持发丝线（红不上结构） */
.attr-chip--bad b {
  color: var(--color-danger);
}

.attr-empty {
  font-size: 12px;
  color: var(--color-text-faint);
}

.ops-panel {
  background: var(--ops-panel);
  border: 1px solid var(--ops-line);
  border-radius: 8px;
  padding: 14px 16px;
  min-width: 0;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.panel-head-text {
  min-width: 0;
}

.panel-title {
  font-family: var(--ops-serif);
  font-size: 15px;
  font-weight: 400;
  letter-spacing: 0.03em;
  color: var(--color-text);
}

.panel-desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--color-text-muted);
}

.panel-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}

.gap-query {
  color: var(--color-text);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
}

.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.scroll-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 300px;
  overflow: auto;
}

.mini-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border: 1px solid var(--ops-line);
  border-radius: 8px;
  min-width: 0;
}

.mini-item--click {
  cursor: pointer;
  transition: border-color 0.15s;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
}

.mini-item--click:hover {
  border-color: var(--color-primary);
}

.mini-name {
  font-size: 13px;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.mini-snippet {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.mini-meta {
  font-size: 11px;
  color: var(--color-text-faint);
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-variant-numeric: tabular-nums;
}

.hit-badge {
  font-style: normal;
  font-size: 11px;
  color: var(--color-danger);
  background: var(--color-danger-subtle);
  border-radius: 4px;
  padding: 0 6px;
  font-weight: 600;
}

.hits-panel {
  padding: 4px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.hit-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
  min-width: 0;
}

.hit-rank {
  color: var(--color-text-faint);
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.hit-doc {
  color: var(--color-text);
  flex-shrink: 0;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hit-snippet {
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.hits-empty {
  font-size: 12px;
  color: var(--color-text-faint);
  padding: 4px 12px;
}

.dialog-desc {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

@media (max-width: 900px) {
  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .kpi-grid :deep(.ops-kpi-tile:nth-child(3)),
  .kpi-grid :deep(.ops-kpi-tile:nth-child(4)) {
    border-left: none;
    border-top: 1px solid var(--ops-line);
  }

  .two-col {
    grid-template-columns: 1fr;
  }
}
</style>
