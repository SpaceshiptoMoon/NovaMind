<template>
  <div class="traj-split">
    <!-- ===== 左：平铺记录时间线 ===== -->
    <div class="traj-table-pane" :style="{ flex: '1 1 auto', minWidth: '280px' }">
      <!-- toolbar：搜索 + Turns/Calls 折叠 -->
      <div class="traj-toolbar">
        <button
          class="traj-tb-btn"
          :class="{ active: allTurnsCollapsed }"
          :disabled="!records.length"
          title="折叠/展开所有 Turn"
          @click="toggleAllTurns"
        >
          <span class="traj-tb-glyph">{{ allTurnsCollapsed ? '⊞' : '⊟' }}</span>
          <span>Turns</span>
        </button>
        <button
          class="traj-tb-btn"
          :class="{ active: allCallsCollapsed }"
          :disabled="!hasAssistantDecisions"
          title="折叠/展开所有工具调用"
          @click="toggleAllCalls"
        >
          <span class="traj-tb-glyph">{{ allCallsCollapsed ? '⊞' : '⊟' }}</span>
          <span>Calls</span>
        </button>
        <input v-model="searchQuery" class="traj-search" placeholder="搜索消息…" type="search" />
      </div>

      <!-- 记录列表 -->
      <div class="traj-body">
        <div v-if="!records.length" class="traj-empty">暂无消息</div>

        <!-- system 固定顶部行（#0，按需拉全文） -->
        <div
          class="traj-row system"
          :class="{ selected: selectedRecordId === 'system' }"
          data-record-id="system"
          @click="selectRecord('system')"
        >
          <span class="traj-index">#0</span>
          <span class="traj-role system">SYSTEM</span>
          <div class="traj-content">
            <span class="traj-preview">Initial System Prompt</span>
          </div>
        </div>

        <!-- 平铺记录 -->
        <template v-for="rec in visibleRecords" :key="rec.recordId">
          <!-- compaction 行：统一序号 + 展开摘要 -->
          <div
            v-if="rec.kind === 'compaction'"
            class="traj-row compaction"
            :class="{ selected: selectedRecordId === rec.recordId }"
            :data-record-id="rec.recordId"
            @click="selectRecord(rec.recordId)"
          >
            <span class="traj-index">#{{ rec.seq }}</span>
            <span class="traj-role compaction">COMPACTED</span>
            <div class="traj-content">
              <button class="compaction-toggle" @click.stop="toggleCompaction(rec.recordId)">
                <span class="compaction-chevron" :class="{ expanded: expandedCompactions.has(rec.recordId) }">▶</span>
                <span class="compaction-label">{{ rec.summary }}</span>
              </button>
            </div>
          </div>
          <div v-if="rec.kind === 'compaction' && expandedCompactions.has(rec.recordId)" class="traj-compaction-body">
            <MarkdownRenderer :content="compactionSummary(rec)" />
          </div>

          <!-- 普通记录行 -->
          <div
            v-else
            class="traj-row"
            :class="[rec.kind, { selected: selectedRecordId === rec.recordId, error: isToolFailed(rec) }]"
            :data-record-id="rec.recordId"
            @click="selectRecord(rec.recordId)"
          >
            <span class="traj-index">#{{ rec.seq }}</span>
            <span class="traj-role" :class="rec.kind">{{ roleLabel(rec.kind) }}</span>
            <span v-if="rec.msg.iteration != null" class="traj-iter">L{{ rec.msg.iteration }}</span>

            <div class="traj-content">
              <!-- user -->
              <template v-if="rec.kind === 'user'">
                <span class="traj-preview">{{ rec.summary }}</span>
              </template>

              <!-- assistant 决策 -->
              <template v-else-if="rec.kind === 'assistant' && rec.toolCalls?.length">
                <span v-if="rec.isToolCallOnly" class="traj-preview traj-muted">(tool call only)</span>
                <span v-else-if="rec.msg.reasoning" class="traj-preview traj-reasoning">{{ firstLine(rec.msg.reasoning) }}</span>
                <span v-else class="traj-preview">{{ firstLine(rec.msg.content) }}</span>
                <span class="traj-tools">→ {{ toolCallNames(rec.toolCalls) }}</span>
              </template>

              <!-- assistant 最终 -->
              <template v-else-if="rec.kind === 'assistant'">
                <span class="traj-preview">{{ rec.summary }}</span>
              </template>

              <!-- tool -->
              <template v-else-if="rec.kind === 'tool'">
                <span class="traj-tool-name">{{ rec.msg.tool_name || rec.toolCall?.toolName }}</span>
                <span class="traj-preview traj-args">{{ compactArgs(rec.toolCall?.arguments) }}</span>
                <span v-if="rec.toolCall?.result" class="traj-result">→ {{ firstLine(rec.toolCall.result, 60) }}</span>
              </template>

              <!-- plan -->
              <template v-else-if="rec.kind === 'plan'">
                <button class="compaction-toggle" @click.stop="togglePlan(rec.recordId)">
                  <span class="compaction-chevron" :class="{ expanded: expandedPlans.has(rec.recordId) }">▶</span>
                  <span class="compaction-label">{{ rec.summary }}</span>
                </button>
              </template>

              <!-- notice -->
              <template v-else-if="rec.kind === 'notice'">
                <span class="traj-preview">{{ rec.summary }}</span>
              </template>

              <!-- 折叠徽章 + 指标 -->
              <span
                v-if="rec.kind === 'user' && isTurnFolded(rec)"
                class="traj-fold-badge"
                @click.stop="toggleTurn(rec.turnIndex)"
                title="展开该 Turn"
              >
                ⊞ {{ turnFoldedCount(rec.turnIndex) }} 步
              </span>
              <span
                v-if="isAssistantDecision(rec) && isCallsFolded(rec)"
                class="traj-fold-badge"
                @click.stop="toggleCalls(rec.recordId)"
                title="展开工具调用"
              >
                ⊞ {{ rec.childToolRecordIds?.length || 0 }} calls
              </span>

              <span v-if="rec.durationMs != null" class="traj-duration">{{ formatDurationMs(rec.durationMs) }}</span>
              <span v-if="rec.toolCall?.durationMs != null" class="traj-duration">{{ formatDurationMs(rec.toolCall.durationMs) }}</span>
              <span v-if="totalTokensOf(rec)" class="traj-duration">{{ totalTokensOf(rec) }} tok</span>
              <span v-if="rec.kind === 'tool'" class="traj-tool-status" :class="rec.toolCall?.status">{{ toolStatusLabel(rec) }}</span>
            </div>
          </div>
          <!-- plan 行展开体：步骤清单 + 状态符号 -->
          <div v-if="rec.kind === 'plan' && expandedPlans.has(rec.recordId)" class="traj-plan-body">
            <div v-for="(step, i) in planSteps(rec)" :key="i" class="plan-step">
              <span class="plan-status-glyph">{{ planStatusGlyph(rec, i) }}</span>
              <span class="plan-step-text">{{ step }}</span>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- ===== 拖拽分隔条 ===== -->
    <div
      v-if="selectedRecordId"
      class="traj-resize-handle"
      role="separator"
      aria-orientation="vertical"
      tabindex="0"
      title="拖拽改宽（双击重置）"
      @pointerdown="onResizeStart"
      @dblclick="resetWidth"
      @keydown="onResizeKey"
    ></div>

    <!-- ===== 右：inspector ===== -->
    <TrajectoryInspector
      v-if="selectedRecordId"
      :record="selectedRecord"
      :session-id="sessionId"
      :style="{ width: inspectorWidth + 'px', flexShrink: 0 }"
      @select-record="selectRecord"
      @select-tool-call="selectToolCall"
      @close="selectedRecordId = null"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import type { AgentMessage, ToolCallRecord } from '@/api/types'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import TrajectoryInspector from './TrajectoryInspector.vue'
import {
  useTrajectoryRecords,
  formatDurationMs,
  toolCallNames as toolCallNamesHelper,
  type TrajectoryRecord,
} from '@/composables/useTrajectoryRecords'

const props = defineProps<{
  messages: AgentMessage[]
  toolCalls: ToolCallRecord[]
  sessionId?: string | null
}>()

// ===== record 派生 =====
const records = useTrajectoryRecords(
  computed(() => props.messages),
  computed(() => props.toolCalls),
)

// system 伪 record（不在 messages 里，固定 #0）
const systemRecord = computed<TrajectoryRecord>(() => ({
  recordId: 'system',
  seq: 0,
  kind: 'system',
  msg: {
    id: 0,
    conversation_id: 0,
    role: 'system',
    content: null,
    tool_call_id: null,
    tool_name: null,
    token_count: null,
    created_at: '',
  },
  turnIndex: 0,
  summary: 'Initial System Prompt',
}))

// ===== 选中态 =====
const selectedRecordId = ref<string | null>(null)
const selectedRecord = computed<TrajectoryRecord | null>(() => {
  if (!selectedRecordId.value) return null
  if (selectedRecordId.value === 'system') return systemRecord.value
  return records.value.find((r) => r.recordId === selectedRecordId.value) ?? null
})

// ===== 折叠态 =====
const collapsedTurns = ref(new Set<number>())
const collapsedAssistants = ref(new Set<string>())
const expandedCompactions = ref(new Set<string>())
const expandedPlans = ref(new Set<string>())

function toggleTurn(turnIndex: number) {
  const next = new Set(collapsedTurns.value)
  if (next.has(turnIndex)) next.delete(turnIndex)
  else next.add(turnIndex)
  collapsedTurns.value = next
}
function toggleCalls(recordId: string) {
  const next = new Set(collapsedAssistants.value)
  if (next.has(recordId)) next.delete(recordId)
  else next.add(recordId)
  collapsedAssistants.value = next
}
function toggleCompaction(recordId: string) {
  const next = new Set(expandedCompactions.value)
  if (next.has(recordId)) next.delete(recordId)
  else next.add(recordId)
  expandedCompactions.value = next
}
function togglePlan(recordId: string) {
  const next = new Set(expandedPlans.value)
  if (next.has(recordId)) next.delete(recordId)
  else next.add(recordId)
  expandedPlans.value = next
}

const turnKeys = computed(() => {
  const map = new Map<number, { first: boolean; count: number }>()
  for (const r of records.value) {
    const entry = map.get(r.turnIndex) ?? { first: false, count: 0 }
    entry.count += 1
    map.set(r.turnIndex, entry)
  }
  // 标记每 turn 首条
  const seen = new Set<number>()
  for (const r of records.value) {
    if (!seen.has(r.turnIndex)) {
      seen.add(r.turnIndex)
      const entry = map.get(r.turnIndex)!
      entry.first = true
    }
  }
  return map
})

function isFirstInTurn(rec: TrajectoryRecord): boolean {
  return turnKeys.value.get(rec.turnIndex)?.first === true && firstRecordOfTurn(rec.turnIndex) === rec.recordId
}
function firstRecordOfTurn(turnIndex: number): string | null {
  const r = records.value.find((x) => x.turnIndex === turnIndex)
  return r?.recordId ?? null
}
function turnFoldedCount(turnIndex: number): number {
  const total = turnKeys.value.get(turnIndex)?.count ?? 0
  return Math.max(0, total - 1)
}
function isTurnFolded(rec: TrajectoryRecord): boolean {
  return collapsedTurns.value.has(rec.turnIndex) && isFirstInTurn(rec) && turnFoldedCount(rec.turnIndex) > 0
}
function isCallsFolded(rec: TrajectoryRecord): boolean {
  return isAssistantDecision(rec) && collapsedAssistants.value.has(rec.recordId) && !!rec.childToolRecordIds?.length
}
function isAssistantDecision(rec: TrajectoryRecord): boolean {
  return rec.kind === 'assistant' && !!rec.toolCalls?.length
}

// 一键折叠/展开
const allTurnsCollapsed = computed(
  () => records.value.length > 0 && collapsedTurns.value.size >= turnKeys.value.size,
)
const hasAssistantDecisions = computed(() => records.value.some(isAssistantDecision))
const allAssistantDecisionIds = computed(() => records.value.filter(isAssistantDecision).map((r) => r.recordId))
const allCallsCollapsed = computed(
  () => hasAssistantDecisions.value && allAssistantDecisionIds.value.every((id) => collapsedAssistants.value.has(id)),
)
function toggleAllTurns() {
  if (allTurnsCollapsed.value) {
    collapsedTurns.value = new Set()
  } else {
    collapsedTurns.value = new Set(turnKeys.value.keys())
  }
}
function toggleAllCalls() {
  if (allCallsCollapsed.value) {
    collapsedAssistants.value = new Set()
  } else {
    collapsedAssistants.value = new Set(allAssistantDecisionIds.value)
  }
}

// ===== 搜索 =====
const searchQuery = ref('')
function matchesSearch(rec: TrajectoryRecord): boolean {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return true
  const hay = [
    rec.summary,
    rec.msg.content || '',
    rec.msg.reasoning || '',
    rec.msg.tool_name || '',
    JSON.stringify(rec.msg.extra?.tool_calls || []),
  ]
    .join(' ')
    .toLowerCase()
  return q.split(/\s+/).every((term) => hay.includes(term))
}

// 搜索时自动展开命中记录所在 turn / calls
watch(searchQuery, (q) => {
  if (!q.trim()) return
  const next1 = new Set(collapsedTurns.value)
  const next2 = new Set(collapsedAssistants.value)
  for (const rec of records.value) {
    if (matchesSearch(rec)) {
      next1.delete(rec.turnIndex)
      if (rec.parentAssistantRecordId) next2.delete(rec.parentAssistantRecordId)
    }
  }
  collapsedTurns.value = next1
  collapsedAssistants.value = next2
})

// ===== 可见记录（应用折叠） =====
const filteredRecords = computed(() => records.value.filter(matchesSearch))

const visibleRecords = computed<TrajectoryRecord[]>(() => {
  const out: TrajectoryRecord[] = []
  for (const rec of filteredRecords.value) {
    // turn 折叠：隐藏 turn 内非首条
    if (collapsedTurns.value.has(rec.turnIndex) && !isFirstInTurn(rec)) continue
    // calls 折叠：隐藏 assistant 决策下的 tool 记录
    if (rec.kind === 'tool' && rec.parentAssistantRecordId && collapsedAssistants.value.has(rec.parentAssistantRecordId)) {
      continue
    }
    out.push(rec)
  }
  return out
})

// ===== hierarchy 跳转 =====
function selectRecord(recordId: string) {
  // auto un-fold：目标所在 turn / 父 assistant calls 折叠则先展开
  const target = recordId === 'system' ? systemRecord.value : records.value.find((r) => r.recordId === recordId)
  if (target && target.kind !== 'system') {
    if (collapsedTurns.value.has(target.turnIndex)) {
      const next = new Set(collapsedTurns.value)
      next.delete(target.turnIndex)
      collapsedTurns.value = next
    }
    if (target.parentAssistantRecordId && collapsedAssistants.value.has(target.parentAssistantRecordId)) {
      const next = new Set(collapsedAssistants.value)
      next.delete(target.parentAssistantRecordId)
      collapsedAssistants.value = next
    }
  }
  selectedRecordId.value = recordId
  nextTick(() => {
    const el = document.querySelector(`[data-record-id="${cssEscape(recordId)}"]`)
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })
}

function selectToolCall(callId: string) {
  const target = records.value.find((r) => r.msg.tool_call_id === callId && r.kind === 'tool')
  if (target) selectRecord(target.recordId)
}

// ===== 拖拽缩放 =====
const inspectorWidth = ref(420)
let resizing = false
let startX = 0
let startWidth = 0
let containerWidth = 0

function onResizeStart(e: PointerEvent) {
  resizing = true
  startX = e.clientX
  startWidth = inspectorWidth.value
  const container = (e.currentTarget as HTMLElement).parentElement
  containerWidth = container?.getBoundingClientRect().width ?? 1200
  window.addEventListener('pointermove', onResizeMove)
  window.addEventListener('pointerup', onResizeEnd)
  e.preventDefault()
}
function onResizeMove(e: PointerEvent) {
  if (!resizing) return
  // 向左拖增大 inspector 宽度
  const delta = startX - e.clientX
  let w = startWidth + delta
  const max = Math.max(320, containerWidth - 280)
  w = Math.min(720, Math.max(320, w))
  if (w > max) w = max
  inspectorWidth.value = Math.round(w)
}
function onResizeEnd() {
  resizing = false
  window.removeEventListener('pointermove', onResizeMove)
  window.removeEventListener('pointerup', onResizeEnd)
}
function resetWidth() {
  inspectorWidth.value = 420
}
function onResizeKey(e: KeyboardEvent) {
  if (e.key === 'ArrowLeft') {
    inspectorWidth.value = Math.min(720, inspectorWidth.value + 16)
    e.preventDefault()
  } else if (e.key === 'ArrowRight') {
    inspectorWidth.value = Math.max(320, inspectorWidth.value - 16)
    e.preventDefault()
  }
}

// ===== helpers =====
function roleLabel(kind: TrajectoryRecord['kind']): string {
  switch (kind) {
    case 'user': return 'USER'
    case 'assistant': return 'ASSISTANT'
    case 'tool': return 'TOOL'
    case 'compaction': return 'COMPACTED'
    case 'system': return 'SYSTEM'
    case 'plan': return 'PLAN'
    case 'notice': return 'NOTICE'
  }
}
function firstLine(text: string | null | undefined, max = 120): string {
  if (!text) return ''
  const line = text.split('\n').find((l) => l.trim()) || ''
  return line.length > max ? line.slice(0, max) + '…' : line
}
function compactArgs(args: Record<string, unknown> | undefined): string {
  if (!args || Object.keys(args).length === 0) return ''
  try {
    const s = JSON.stringify(args)
    return s.length > 60 ? s.slice(0, 60) + '…' : s
  } catch {
    return ''
  }
}
function toolCallNames(tcs: TrajectoryRecord['toolCalls']): string {
  return toolCallNamesHelper(tcs)
}
function totalTokensOf(rec: TrajectoryRecord): number | null {
  return rec.usage?.total_tokens ?? null
}
function isToolFailed(rec: TrajectoryRecord): boolean {
  return rec.kind === 'tool' && rec.toolCall?.status === 'failed'
}
function toolStatusLabel(rec: TrajectoryRecord): string {
  switch (rec.toolCall?.status) {
    case 'running': return '执行中'
    case 'completed': return '完成'
    case 'failed': return '失败'
    case 'pending': return '等待'
    default: return ''
  }
}
function compactionSummary(rec: TrajectoryRecord): string {
  const comp = rec.msg.extra?.compaction as { summary?: string } | undefined
  return comp?.summary || ''
}
function planSteps(rec: TrajectoryRecord): string[] {
  const plan = rec.msg.extra?.plan as { steps?: string[] } | undefined
  return plan?.steps ?? []
}
function planStatusGlyph(rec: TrajectoryRecord, i: number): string {
  const plan = rec.msg.extra?.plan as { statuses?: string[] } | undefined
  const s = plan?.statuses?.[i]
  if (s === 'completed') return '[✓]'
  if (s === 'in_progress') return '[→]'
  return '[ ]'
}
function cssEscape(s: string): string {
  if (typeof CSS !== 'undefined' && CSS.escape) return CSS.escape(s)
  return s.replace(/["\\]/g, '\\$&')
}
</script>

<style scoped>
.traj-split {
  display: flex;
  height: 100%;
  min-height: 0;
  width: 100%;
  background: var(--color-bg-elevated);
}

/* ===== 左侧 table pane ===== */
.traj-table-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
}

.traj-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
  background: var(--color-bg-card);
}

.traj-tb-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.traj-tb-btn:hover:not(:disabled) {
  background: var(--color-bg-hover);
  color: var(--color-text);
}
.traj-tb-btn.active {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-text);
  font-weight: 600;
}
.traj-tb-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.traj-tb-glyph {
  font-size: 11px;
}

.traj-search {
  flex: 1;
  min-width: 0;
  padding: 4px 10px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-input, var(--color-bg-card));
  font-size: var(--text-xs);
  color: var(--color-text);
  outline: none;
}
.traj-search:focus {
  border-color: var(--color-primary);
}

.traj-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2) var(--space-3);
  min-height: 0;
}

.traj-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-faint, var(--color-text-muted));
}

/* ===== 记录行 ===== */
.traj-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--transition-fast);
  font-size: var(--text-xs);
  border-left: 2px solid transparent;
}
.traj-row:hover {
  background: var(--color-bg-hover);
}
.traj-row.selected {
  background: var(--color-bg-hover);
  border-left-color: var(--color-text);
}
.traj-row.error {
  background: rgba(254, 226, 226, 0.4);
}
.traj-row.error:hover {
  background: rgba(254, 226, 226, 0.7);
}
.traj-row.notice {
  background: rgba(254, 243, 199, 0.4);
}
.traj-row.notice:hover {
  background: rgba(254, 243, 199, 0.7);
}

.traj-index {
  flex-shrink: 0;
  width: 32px;
  color: var(--color-text-faint, var(--color-text-muted));
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono, ui-monospace, monospace);
}

.traj-role {
  flex-shrink: 0;
  min-width: 64px;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  font-size: 10px;
  font-weight: 600;
  font-family: var(--font-mono, ui-monospace, monospace);
  text-align: center;
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}
.traj-role.user { background: rgba(17, 24, 39, 0.08); color: var(--color-text); }
.traj-role.assistant { background: rgba(99, 102, 241, 0.12); color: #4338ca; }
.traj-role.tool { background: rgba(20, 184, 166, 0.12); color: #0f766e; }
.traj-role.system { background: rgba(245, 158, 11, 0.12); color: #b45309; }
.traj-role.compaction { background: rgba(107, 114, 128, 0.12); color: #4b5563; }
.traj-role.plan { background: rgba(139, 92, 246, 0.12); color: #6d28d9; }
.traj-role.notice { background: rgba(245, 158, 11, 0.12); color: #b45309; }

.traj-iter {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--color-text-muted);
  font-family: var(--font-mono, ui-monospace, monospace);
}

.traj-content {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.traj-preview {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-secondary);
}
.traj-preview.traj-reasoning {
  font-style: italic;
  color: var(--color-text-muted);
}
.traj-preview.traj-muted {
  color: var(--color-text-muted);
}
.traj-preview.traj-args {
  flex: 0 1 auto;
  font-family: var(--font-mono, ui-monospace, monospace);
  color: var(--color-text-muted);
  max-width: 240px;
}

.traj-tools {
  flex-shrink: 0;
  font-family: var(--font-mono, ui-monospace, monospace);
  color: var(--color-text);
  font-weight: 500;
}

.traj-tool-name {
  flex-shrink: 0;
  font-family: var(--font-mono, ui-monospace, monospace);
  color: var(--color-text);
  font-weight: 500;
}

.traj-result {
  flex-shrink: 0;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-muted);
}

.traj-fold-badge {
  flex-shrink: 0;
  padding: 1px 6px;
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-sm);
  font-size: 10px;
  color: var(--color-text-muted);
  cursor: pointer;
}
.traj-fold-badge:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.traj-duration {
  flex-shrink: 0;
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono, ui-monospace, monospace);
}

.traj-tool-status {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: var(--radius-full);
  font-size: 10px;
}
.traj-tool-status.completed { background: rgba(17, 24, 39, 0.06); color: var(--color-text-secondary); }
.traj-tool-status.running { background: #fef9c3; color: #a16207; }
.traj-tool-status.failed { background: #fee2e2; color: #b91c1c; }
.traj-tool-status.pending { background: rgba(17, 24, 39, 0.06); color: var(--color-text-muted); }

/* compaction 行展开体 */
.traj-compaction-body {
  margin: var(--space-1) 0 var(--space-2) 40px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card, #fff);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--color-text-secondary);
  max-height: 320px;
  overflow-y: auto;
}
.traj-compaction-body :deep(p:last-child) {
  margin-bottom: 0;
}

/* plan 行展开体 */
.traj-plan-body {
  margin: var(--space-1) 0 var(--space-2) 40px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card, #fff);
  font-size: var(--text-sm);
  max-height: 320px;
  overflow-y: auto;
}
.plan-step {
  display: flex;
  gap: var(--space-2);
  padding: 2px 0;
}
.plan-status-glyph {
  flex-shrink: 0;
  font-family: var(--font-mono, ui-monospace, monospace);
  color: var(--color-text-muted);
}
.plan-step-text {
  color: var(--color-text-secondary);
}

.compaction-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  padding: 0;
  font: inherit;
  color: var(--color-text-secondary);
  cursor: pointer;
}
.compaction-toggle:hover {
  color: var(--color-text);
}
.compaction-chevron {
  font-size: 9px;
  color: var(--color-text-muted);
  transition: transform var(--transition-fast);
}
.compaction-chevron.expanded {
  transform: rotate(90deg);
}
.compaction-label {
  color: var(--color-text-secondary);
}

/* ===== 拖拽分隔条 ===== */
.traj-resize-handle {
  flex-shrink: 0;
  width: 5px;
  cursor: col-resize;
  background: var(--color-border-light);
  transition: background var(--transition-fast);
}
.traj-resize-handle:hover,
.traj-resize-handle:active {
  background: var(--color-border);
}
</style>