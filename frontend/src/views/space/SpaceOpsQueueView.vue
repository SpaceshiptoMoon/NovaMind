<template>
  <div class="ops-queue" v-loading="loading">
    <!-- 待办队列 -->
    <div class="ops-panel">
      <div class="panel-head">
        <div class="panel-head-text">
          <div class="panel-title">复审建议</div>
          <p class="panel-desc">
            平台生成的待人工处置建议。采纳新版会下线旧文档，平台永不自动改写内容
          </p>
        </div>
        <div class="panel-actions">
          <el-select
            v-model="kbFilter"
            placeholder="矛盾检测知识库"
            style="width: 180px"
            size="small"
          >
            <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
          <el-button size="small" :disabled="!kbFilter" :loading="scanning" @click="runScan">
            矛盾检测
          </el-button>
        </div>
      </div>

      <div class="filter-row">
        <button
          v-for="f in TYPE_FILTERS"
          :key="f.key"
          type="button"
          class="filter-chip"
          :class="{ 'filter-chip--active': typeFilter === f.key }"
          @click="typeFilter = f.key"
        >
          {{ f.label }} <b v-if="typeCount(f.key) > 0">{{ typeCount(f.key) }}</b>
        </button>
        <span v-if="selectedIds.length" class="batch-bar">
          已选 {{ selectedIds.length }} 项
          <el-button size="small" text type="danger" @click="batchDismiss">忽略所选</el-button>
        </span>
      </div>

      <el-empty
        v-if="!filteredSuggestions.length"
        description="队列为空——所有建议已处置完毕"
        :image-size="72"
      />
      <div v-else class="queue-list">
        <div v-for="item in filteredSuggestions" :key="item.id" class="queue-card">
          <div class="queue-main">
            <el-checkbox
              :model-value="selectedIds.includes(item.id)"
              @change="toggleSelect(item.id)"
            />
            <el-tag
              :type="item.suggestion_type === 'new_version' ? 'warning' : 'danger'"
              size="small"
              effect="plain"
            >
              {{ item.suggestion_type === 'new_version' ? '疑似新旧版本' : '内容矛盾' }}
            </el-tag>
            <span class="queue-docs">
              <template v-if="item.suggestion_type === 'new_version'">
                {{ docName(item.old_doc_id) }} → {{ docName(item.new_doc_id) }}
              </template>
              <template v-else
                >{{ docName(item.old_doc_id) }} ↔ {{ docName(item.new_doc_id) }}</template
              >
            </span>
            <span v-if="item.score !== null" class="queue-score">{{
              formatScore(item.score)
            }}</span>
            <span class="queue-time">{{ shortTime(item.created_at) }}</span>
          </div>
          <p v-if="item.reason" class="queue-reason">{{ item.reason }}</p>
          <div class="queue-actions">
            <el-button size="small" type="primary" plain @click="accept(item)">
              {{ item.suggestion_type === 'new_version' ? '采纳并替换' : '确认矛盾' }}
            </el-button>
            <el-button size="small" @click="dismiss(item)">忽略</el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 复审到期 -->
    <div class="ops-panel">
      <div class="panel-head">
        <div class="panel-head-text">
          <div class="panel-title">复审到期文档</div>
          <p class="panel-desc">owner 应在文档详情页确认内容仍然有效（确认后顺延复审周期）</p>
        </div>
        <el-tag v-if="dueCount" type="warning" size="small" effect="plain"
          >窗口内 {{ dueCount }} 篇</el-tag
        >
      </div>
      <el-empty v-if="!dueReviews.length" description="没有临期复审文档" :image-size="64" />
      <div v-else class="due-list">
        <div
          v-for="doc in dueReviews"
          :key="doc.document_id"
          class="due-item"
          @click="goDocument(doc)"
        >
          <span class="due-name" :title="doc.filename">
            {{ doc.filename }}
            <em v-if="doc.overdue" class="overdue-flag">已过期</em>
          </span>
          <span class="due-meta">复审期 {{ shortDate(doc.next_review_at) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 待办队列页：复审建议 triage（证据卡+三态处置+后果前置）+ 复审到期清单。
 *
 * 后果前置：accept 前的确认框写明动作后果（旧文档下线退出召回 / 通知
 * 双方 owner）；批量忽略逐条调 resolve（无批量端点，客户端循环）。
 * 处置成功后拉一次父壳徽标刷新（inject opsRefreshBadges）。
 */
import { computed, inject, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { knowledgeBaseApi, spaceStatsApi } from '@/api/knowledge'
import { useOpsDocNames } from '@/composables/useOpsDocNames'
import type { KbOpsDueReview, KbOpsOverview, KbOpsSuggestion } from '@/api/types'

const TYPE_FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'new_version', label: '新旧版本' },
  { key: 'contradiction', label: '矛盾' },
] as const

const route = useRoute()
const router = useRouter()
const spaceId = computed(() => parseInt(String(route.params.id), 10))

const opsRefreshBadges = inject<(() => void) | undefined>('opsRefreshBadges', undefined)
const { resolveDocNames, docName } = useOpsDocNames(spaceId)

const loading = ref(false)
const suggestions = ref<KbOpsSuggestion[]>([])
const overview = ref<KbOpsOverview | null>(null)
const typeFilter = ref<string>('all')
const selectedIds = ref<number[]>([])
const kbFilter = ref<number | undefined>(undefined)
const kbOptions = ref<Array<{ id: number; name: string }>>([])
const scanning = ref(false)

const filteredSuggestions = computed(() =>
  typeFilter.value === 'all'
    ? suggestions.value
    : suggestions.value.filter((s) => s.suggestion_type === typeFilter.value),
)

const dueReviews = computed(() => overview.value?.due_reviews.items ?? [])
const dueCount = computed(() => overview.value?.due_reviews.count ?? 0)

function typeCount(key: string): number {
  if (key === 'all') return suggestions.value.length
  return suggestions.value.filter((s) => s.suggestion_type === key).length
}

function toggleSelect(id: number): void {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((v) => v !== id)
    : [...selectedIds.value, id]
}

// ===== 处置 =====

async function accept(item: KbOpsSuggestion): Promise<void> {
  const oldName = docName(item.old_doc_id)
  const newName = docName(item.new_doc_id)
  const confirmText =
    item.suggestion_type === 'new_version'
      ? `采纳后将下线旧文档「${oldName}」（退出检索召回），由「${newName}」替代。误替换可在文档生命周期中恢复。`
      : `确认矛盾后将通知两位文档 owner 人工对齐内容，平台不会自动改写。`
  try {
    await ElMessageBox.confirm(confirmText, '确认处置', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await resolve(item, 'accepted')
}

async function dismiss(item: KbOpsSuggestion): Promise<void> {
  await resolve(item, 'dismissed')
}

async function resolve(item: KbOpsSuggestion, action: 'accepted' | 'dismissed'): Promise<void> {
  try {
    const result = await spaceStatsApi.resolveSuggestion(spaceId.value, item.id, action)
    if (result.superseded_doc_id) {
      ElMessage.success(`已采纳：旧文档 #${result.superseded_doc_id} 已下线`)
    } else {
      ElMessage.success(action === 'accepted' ? '已确认矛盾并通知 owner' : '已忽略')
    }
  } catch (e) {
    console.warn('[SpaceOpsQueue] 处置失败', e)
    ElMessage.error('处置失败，请稍后重试')
    return
  }
  suggestions.value = suggestions.value.filter((s) => s.id !== item.id)
  selectedIds.value = selectedIds.value.filter((v) => v !== item.id)
  opsRefreshBadges?.()
}

async function batchDismiss(): Promise<void> {
  const ids = [...selectedIds.value]
  for (const id of ids) {
    const item = suggestions.value.find((s) => s.id === id)
    if (item) {
      await resolve(item, 'dismissed')
    }
  }
  ElMessage.success(`已忽略 ${ids.length} 条建议`)
}

async function runScan(): Promise<void> {
  if (!kbFilter.value) return
  scanning.value = true
  try {
    const result = await spaceStatsApi.runContradictionScan(spaceId.value, kbFilter.value)
    if (result.suggestions_created > 0) {
      ElMessage.success(`检测完成：新建 ${result.suggestions_created} 条矛盾建议`)
    } else {
      ElMessage.info('检测完成：本轮未发现内容矛盾')
    }
    await loadSuggestions()
    opsRefreshBadges?.()
  } catch (e) {
    console.warn('[SpaceOpsQueue] 矛盾检测失败', e)
    ElMessage.error('检测失败（需要空间管理员权限，或 LLM 服务不可用）')
  } finally {
    scanning.value = false
  }
}

function goDocument(doc: KbOpsDueReview): void {
  void router.push({
    path: `/home/spaces/${spaceId.value}/documents/${doc.document_id}`,
    query: { kbId: String(doc.kb_id) },
  })
}

// ===== 工具 =====

function shortDate(iso?: string | null): string {
  return iso ? iso.slice(0, 10) : '—'
}

function shortTime(iso?: string | null): string {
  return iso ? iso.slice(0, 16).replace('T', ' ') : '—'
}

function formatScore(v: number | null): string {
  return v === null ? '—' : `${(v / 100).toFixed(0)}%`
}

// ===== 加载 =====

async function loadSuggestions(): Promise<void> {
  try {
    const data = await spaceStatsApi.getReviewSuggestions(spaceId.value)
    suggestions.value = data.items ?? []
  } catch (e) {
    console.warn('[SpaceOpsQueue] 建议加载失败', e)
    suggestions.value = []
  }
}

onMounted(async () => {
  loading.value = true
  try {
    const [ov] = await Promise.all([spaceStatsApi.getOpsOverview(spaceId.value), loadSuggestions()])
    overview.value = ov
  } catch (e) {
    console.warn('[SpaceOpsQueue] 加载失败', e)
  } finally {
    loading.value = false
  }
  void resolveDocNames()
  try {
    const kbs = await knowledgeBaseApi.getKnowledgeBases(spaceId.value)
    kbOptions.value = (kbs.items ?? []).map((k) => ({ id: k.id, name: k.name }))
  } catch {
    kbOptions.value = []
  }
})
</script>

<style scoped>
.ops-queue {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
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

.filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.filter-chip {
  border: 1px solid var(--ops-line);
  background: transparent;
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 12px;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition:
    border-color 0.15s,
    color 0.15s;
}

.filter-chip:hover {
  color: var(--color-text);
  border-color: var(--ops-line-hover);
}

.filter-chip--active {
  background: var(--color-chip-active);
  border-color: var(--color-chip-active);
  color: var(--color-chip-active-text);
}

.filter-chip b {
  font-variant-numeric: tabular-nums;
}

.batch-bar {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}

.queue-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.queue-card {
  border: 1px solid var(--ops-line);
  border-radius: 8px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.15s;
}

.queue-card:hover {
  border-color: var(--ops-line-hover);
}

.queue-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}

.queue-docs {
  font-size: 13px;
  color: var(--color-text);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.queue-score {
  font-size: 12px;
  color: var(--color-warning);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.queue-time {
  font-size: 11px;
  color: var(--color-text-faint);
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.queue-reason {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.55;
  background: var(--color-bg-stripe);
  border-radius: 6px;
  padding: 6px 10px;
}

.queue-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.due-list {
  display: flex;
  flex-direction: column;
}

.due-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 8px 4px;
  border-bottom: 1px solid var(--ops-line);
  font-size: 13px;
  cursor: pointer;
}

.due-item:hover .due-name {
  color: var(--color-primary);
}

.due-item:last-child {
  border-bottom: none;
}

.due-name {
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

.due-meta {
  font-size: 12px;
  color: var(--color-text-faint);
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
</style>
