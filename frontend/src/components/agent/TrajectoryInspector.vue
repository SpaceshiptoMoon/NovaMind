<template>
  <aside class="traj-inspector" role="complementary" aria-label="轨迹记录详情">
    <div v-if="!record" class="traj-inspector-empty">点击左侧记录查看详情</div>
    <div v-else class="traj-inspector-body">
      <!-- header：kind tag + Turn/序号 + 关闭 -->
      <header class="inspector-header">
        <span class="inspector-kind" :class="record.kind">{{ kindLabel(record.kind) }}</span>
        <span class="inspector-loc">
          <template v-if="record.kind === 'compaction'">Turn {{ record.turnIndex }}</template>
          <template v-else>Turn {{ record.turnIndex }} · #{{ record.seq }}</template>
        </span>
        <button class="inspector-close" title="关闭" @click="$emit('close')">
          <el-icon :size="14"><Close /></el-icon>
        </button>
      </header>

      <!-- tab strip -->
      <nav class="inspector-tabs" role="tablist">
        <button
          v-for="t in tabs"
          :key="t.id"
          class="inspector-tab"
          :class="{ active: activeTab === t.id }"
          role="tab"
          @click="activateTab(t.id)"
        >
          {{ t.label }}
        </button>
      </nav>

      <!-- tab 内容 -->
      <div class="inspector-content">
        <!-- ===== Summary ===== -->
        <section v-if="activeTab === 'summary'">
          <!-- compacted -->
          <template v-if="record.kind === 'compaction'">
            <div class="insp-section">
              <div class="insp-label">摘要</div>
              <div class="insp-md">
                <MarkdownRenderer :content="compactionSummary" />
              </div>
            </div>
          </template>

          <!-- assistant 决策 -->
          <template v-else-if="record.kind === 'assistant' && record.toolCalls?.length">
            <dl class="insp-overview">
              <div class="ov-row"><dt>类型</dt><dd>决策（调用 {{ record.toolCalls.length }} 个工具）</dd></div>
              <div v-if="record.isToolCallOnly" class="ov-row"><dt>文本</dt><dd class="ov-muted">（tool call only，无 reasoning/content）</dd></div>
              <div v-if="record.msg.iteration != null" class="ov-row"><dt>轮次</dt><dd>L{{ record.msg.iteration }}</dd></div>
              <div v-if="record.durationMs != null" class="ov-row"><dt>耗时</dt><dd>{{ formatDurationMs(record.durationMs) }}</dd></div>
              <div v-if="totalTokens" class="ov-row"><dt>Tokens</dt><dd>{{ totalTokens }}</dd></div>
            </dl>
            <div v-if="record.msg.reasoning" class="insp-section">
              <div class="insp-label">思考预览</div>
              <div class="insp-md"><MarkdownRenderer :content="record.msg.reasoning" /></div>
            </div>
            <div v-if="record.msg.content" class="insp-section">
              <div class="insp-label">文本预览</div>
              <div class="insp-md"><MarkdownRenderer :content="record.msg.content" /></div>
            </div>
          </template>

          <!-- assistant 最终 -->
          <template v-else-if="record.kind === 'assistant'">
            <dl class="insp-overview">
              <div class="ov-row"><dt>类型</dt><dd>最终回答</dd></div>
              <div v-if="record.msg.iteration != null" class="ov-row"><dt>轮次</dt><dd>L{{ record.msg.iteration }}</dd></div>
              <div v-if="record.durationMs != null" class="ov-row"><dt>耗时</dt><dd>{{ formatDurationMs(record.durationMs) }}</dd></div>
              <div v-if="totalTokens" class="ov-row"><dt>Tokens</dt><dd>{{ totalTokens }}</dd></div>
            </dl>
            <div v-if="record.msg.content" class="insp-section">
              <div class="insp-label">回答预览</div>
              <div class="insp-md"><MarkdownRenderer :content="record.msg.content" /></div>
            </div>
          </template>

          <!-- tool -->
          <template v-else-if="record.kind === 'tool'">
            <dl class="insp-overview">
              <div class="ov-row"><dt>工具</dt><dd class="ov-mono">{{ record.msg.tool_name || record.toolCall?.toolName }}</dd></div>
              <div class="ov-row"><dt>状态</dt><dd><span class="status-pill" :class="toolStatus">{{ toolStatusLabel }}</span></dd></div>
              <div v-if="record.toolCall?.durationMs != null" class="ov-row"><dt>耗时</dt><dd>{{ formatDurationMs(record.toolCall.durationMs) }}</dd></div>
            </dl>
            <div v-if="record.parentAssistantRecordId" class="insp-section">
              <button class="hierarchy-btn" @click="$emit('select-record', record.parentAssistantRecordId)">
                <el-icon :size="12"><Top /></el-icon>
                <span>跳转到父 Assistant 决策</span>
              </button>
            </div>
          </template>

          <!-- user -->
          <template v-else-if="record.kind === 'user'">
            <div class="insp-section">
              <div class="insp-label">用户消息</div>
              <div class="insp-md"><MarkdownRenderer :content="record.msg.content || ''" /></div>
            </div>
          </template>
        </section>

        <!-- ===== System Prompt ===== -->
        <section v-else-if="activeTab === 'system-prompt'" class="insp-section">
          <div class="insp-label">System Prompt 全文</div>
          <div v-if="systemPromptLoading" class="insp-hint">加载中…</div>
          <div v-else-if="systemPromptError" class="insp-hint error">{{ systemPromptError }}</div>
          <div v-else-if="systemPromptText" class="insp-md"><MarkdownRenderer :content="systemPromptText" /></div>
          <div v-else class="insp-hint">暂无 system prompt</div>
        </section>

        <!-- ===== Tools ===== -->
        <section v-else-if="activeTab === 'tools'" class="insp-section">
          <div v-if="!agentStore.tools.length" class="insp-hint">暂无工具</div>
          <div v-for="provider in agentStore.tools" :key="provider.name" class="tool-provider">
            <div class="provider-name">{{ provider.name }}</div>
            <details v-for="tool in provider.tools" :key="tool.name" class="tool-details">
              <summary class="tool-summary">
                <span class="tool-glyph">🔧</span>
                <span class="tool-name-mono">{{ tool.name }}</span>
                <span class="tool-desc">{{ tool.description }}</span>
              </summary>
              <div class="tool-params">
                <JsonTree :data="tool.parameters" :default-expanded="1" />
              </div>
            </details>
          </div>
        </section>

        <!-- ===== Thinking ===== -->
        <section v-else-if="activeTab === 'thinking'" class="insp-section">
          <div class="insp-label">思考过程</div>
          <div v-if="record.msg.reasoning" class="insp-md"><MarkdownRenderer :content="record.msg.reasoning" /></div>
          <div v-else class="insp-hint">无思考内容</div>
        </section>

        <!-- ===== Content ===== -->
        <section v-else-if="activeTab === 'content'" class="insp-section">
          <div class="insp-label">内容</div>
          <div v-if="record.msg.content" class="insp-md"><MarkdownRenderer :content="record.msg.content" /></div>
          <div v-else class="insp-hint">无文本内容</div>
        </section>

        <!-- ===== Tool Calls（assistant 决策） ===== -->
        <section v-else-if="activeTab === 'tool-calls'" class="insp-section">
          <div class="insp-label">工具调用（{{ record.toolCalls?.length || 0 }}）</div>
          <div v-for="tc in record.toolCalls" :key="tc.id" class="tc-block">
            <div class="tc-head">
              <span class="tc-name">{{ tc.function.name }}</span>
              <button class="tc-jump" title="跳转到工具记录" @click="$emit('select-tool-call', tc.id)">
                <el-icon :size="11"><Right /></el-icon>
                <span>记录</span>
              </button>
            </div>
            <pre class="tc-args">{{ formatToolArgs(tc.function.arguments) }}</pre>
          </div>
        </section>

        <!-- ===== Payload（tool 参数） ===== -->
        <section v-else-if="activeTab === 'payload'" class="insp-section">
          <div class="insp-label">参数</div>
          <JsonTree v-if="hasPayload" :data="record.toolCall?.arguments" :default-expanded="2" />
          <div v-else class="insp-hint">无参数</div>
        </section>

        <!-- ===== Result（tool 结果） ===== -->
        <section v-else-if="activeTab === 'result'" class="insp-section">
          <div class="insp-label">结果</div>
          <div v-if="toolStatus === 'running' && !record.toolCall?.result" class="insp-hint">执行中…</div>
          <template v-else-if="record.toolCall?.result">
            <JsonTree v-if="parsedResult" :data="parsedResult" :default-expanded="2" :class="{ error: toolStatus === 'failed' }" />
            <pre v-else class="insp-pre" :class="{ error: toolStatus === 'failed' }">{{ record.toolCall.result }}</pre>
          </template>
          <div v-else class="insp-hint">无结果</div>
        </section>

        <!-- ===== Sources ===== -->
        <section v-else-if="activeTab === 'sources'" class="insp-section">
          <div class="insp-label">引用来源（{{ record.msg.sources?.length || 0 }}）</div>
          <div v-if="!record.msg.sources?.length" class="insp-hint">无引用</div>
          <div
            v-for="s in record.msg.sources"
            :key="s.index"
            class="source-card"
            :class="s.kind"
          >
            <span class="source-idx">{{ s.index }}</span>
            <div class="source-meta">
              <div class="source-name-row">
                <span class="source-name">{{ s.document_name || s.url || `来源 ${s.index}` }}</span>
                <span class="source-kind-tag" :class="s.kind">{{ s.kind === 'web' ? '联网' : '知识库' }}</span>
              </div>
              <div v-if="s.score != null" class="source-sub">相关度 {{ Math.round(s.score * 100) }}%</div>
              <div v-if="s.snippet" class="source-snippet">{{ s.snippet }}</div>
            </div>
          </div>
        </section>

        <!-- ===== Attachments（user 附件） ===== -->
        <section v-else-if="activeTab === 'attachments'" class="insp-section">
          <div class="insp-label">附件（{{ attachments.length }}）</div>
          <div v-if="!attachments.length" class="insp-hint">无附件</div>
          <div v-for="att in attachments" :key="att.filename" class="att-card">
            <span class="att-ext">{{ fileExt(att.filename) }}</span>
            <span class="att-name">{{ att.filename }}</span>
            <span v-if="att.file_size != null" class="att-size">{{ formatFileSize(att.file_size) }}</span>
          </div>
        </section>

        <!-- ===== Timing ===== -->
        <section v-else-if="activeTab === 'timing'" class="insp-section">
          <div class="insp-label">耗时与 Token</div>
          <dl class="insp-overview">
            <div v-if="record.durationMs != null" class="ov-row"><dt>LLM 耗时</dt><dd>{{ formatDurationMs(record.durationMs) }}</dd></div>
            <div v-if="record.toolCall?.durationMs != null" class="ov-row"><dt>工具耗时</dt><dd>{{ formatDurationMs(record.toolCall.durationMs) }}</dd></div>
            <div v-if="record.usage?.input_tokens != null" class="ov-row"><dt>Input</dt><dd>{{ record.usage.input_tokens }}</dd></div>
            <div v-if="record.usage?.cache_read_tokens != null" class="ov-row"><dt>Cache Read</dt><dd>{{ record.usage.cache_read_tokens }}</dd></div>
            <div v-if="record.usage?.cache_write_tokens != null" class="ov-row"><dt>Cache Write</dt><dd>{{ record.usage.cache_write_tokens }}</dd></div>
            <div v-if="record.usage?.output_tokens != null" class="ov-row"><dt>Output</dt><dd>{{ record.usage.output_tokens }}</dd></div>
            <div v-if="record.usage?.reasoning_tokens != null" class="ov-row"><dt>Reasoning</dt><dd>{{ record.usage.reasoning_tokens }}</dd></div>
            <div v-if="totalTokens" class="ov-row"><dt>Total</dt><dd>{{ totalTokens }}</dd></div>
          </dl>
        </section>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Close, Top, Right } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import { agentApi } from '@/api/agent'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import JsonTree from '@/components/common/JsonTree.vue'
import type { ToolCallRecord } from '@/api/types'
import {
  type TrajectoryRecord,
  parseJsonContainer,
  formatDurationMs,
} from '@/composables/useTrajectoryRecords'

const props = defineProps<{
  record: TrajectoryRecord | null
  sessionId?: string | null
}>()

defineEmits<{
  'select-record': [recordId: string]
  'select-tool-call': [callId: string]
  close: []
}>()

const agentStore = useAgentStore()

// ===== tab 动态分配 =====
type TabId =
  | 'summary'
  | 'system-prompt'
  | 'tools'
  | 'thinking'
  | 'content'
  | 'tool-calls'
  | 'payload'
  | 'result'
  | 'sources'
  | 'attachments'
  | 'timing'

const TAB_LABELS: Record<TabId, string> = {
  summary: '概览',
  'system-prompt': 'System Prompt',
  tools: '工具',
  thinking: '思考',
  content: '内容',
  'tool-calls': '工具调用',
  payload: '参数',
  result: '结果',
  sources: '引用',
  attachments: '附件',
  timing: '耗时',
}

const tabs = computed<{ id: TabId; label: string }[]>(() => {
  const r = props.record
  if (!r) return []
  const list: TabId[] = []
  if (r.kind === 'system') {
    list.push('system-prompt')
    list.push('tools')
  } else if (r.kind === 'user') {
    list.push('content')
    if (attachments.value.length) list.push('attachments')
  } else if (r.kind === 'compaction') {
    list.push('summary')
  } else if (r.kind === 'assistant' && r.toolCalls?.length) {
    list.push('summary')
    if (r.msg.reasoning) list.push('thinking')
    list.push('tool-calls')
    if (r.usage || r.durationMs != null) list.push('timing')
  } else if (r.kind === 'assistant') {
    list.push('summary')
    if (r.msg.reasoning) list.push('thinking')
    list.push('content')
    if (r.msg.sources?.length) list.push('sources')
    if (r.usage || r.durationMs != null) list.push('timing')
  } else if (r.kind === 'tool') {
    list.push('summary')
    if (hasPayload.value) list.push('payload')
    if (r.toolCall?.result || r.toolCall?.status === 'running') list.push('result')
    if (r.toolCall?.durationMs != null) list.push('timing')
  }
  return list.map((id) => ({ id, label: TAB_LABELS[id] }))
})

// ===== activeTab + tab 历史 =====
const activeTab = ref<TabId | null>(null)
const tabHistory = new Set<TabId>()

function activateTab(id: TabId) {
  activeTab.value = id
  tabHistory.delete(id)
  tabHistory.add(id)
}

// record 变化时重置 activeTab：优先恢复最近用过的 tab，否则取 tabs[0]
watch(
  () => props.record?.recordId,
  () => {
    const ids = tabs.value.map((t) => t.id)
    if (!ids.length) {
      activeTab.value = null
      return
    }
    // 找最近用过的、且当前可用的 tab
    let restored: TabId | null = null
    for (const t of Array.from(tabHistory).reverse()) {
      if (ids.includes(t)) {
        restored = t
        break
      }
    }
    activeTab.value = restored ?? ids[0] ?? null
    // system 行切到 system-prompt
    if (props.record?.kind === 'system' && ids.includes('system-prompt')) {
      activeTab.value = 'system-prompt'
    }
  },
  { immediate: true },
)

// tabs 变化时若 activeTab 不在列表里，修正
watch(tabs, (list) => {
  if (activeTab.value && !list.some((t) => t.id === activeTab.value)) {
    activeTab.value = list[0]?.id ?? null
  }
})

// ===== 派生字段 =====
const totalTokens = computed(() => props.record?.usage?.total_tokens ?? null)

const compactionSummary = computed(() => {
  const comp = props.record?.msg.extra?.compaction as { summary?: string } | undefined
  return comp?.summary || ''
})

const toolStatus = computed<ToolCallRecord['status']>(() => {
  if (props.record?.kind !== 'tool') return 'completed'
  return props.record.toolCall?.status ?? 'completed'
})
const toolStatusLabel = computed(() => {
  switch (toolStatus.value) {
    case 'running': return '执行中'
    case 'completed': return '完成'
    case 'failed': return '失败'
    case 'pending': return '等待中'
  }
})

const hasPayload = computed(() => {
  const args = props.record?.toolCall?.arguments
  return !!args && Object.keys(args).length > 0
})

const parsedResult = computed(() => {
  const raw = props.record?.toolCall?.result
  return parseJsonContainer(raw)
})

const attachments = computed(
  () =>
    (props.record?.msg.extra?.attachments as Array<{
      filename: string
      file_size?: number
      file_type?: string
    }> | undefined) ?? [],
)

function kindLabel(kind: TrajectoryRecord['kind'] | 'system'): string {
  switch (kind) {
    case 'user': return 'USER'
    case 'assistant': return 'ASSISTANT'
    case 'tool': return 'TOOL'
    case 'compaction': return 'COMPACTED'
    case 'system': return 'SYSTEM'
  }
}

function formatToolArgs(args: string | undefined): string {
  if (!args) return ''
  try {
    return JSON.stringify(JSON.parse(args), null, 2)
  } catch {
    return args
  }
}

function fileExt(filename?: string): string {
  if (!filename) return 'FILE'
  return filename.split('.').pop()?.toUpperCase() || 'FILE'
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// ===== system prompt 按需拉 =====
const systemPromptText = ref('')
const systemPromptLoading = ref(false)
const systemPromptError = ref('')

async function loadSystemPrompt() {
  if (!props.sessionId) {
    systemPromptError.value = '无会话 ID'
    return
  }
  systemPromptLoading.value = true
  systemPromptError.value = ''
  try {
    const res = await agentApi.getSystemPrompt(props.sessionId)
    systemPromptText.value = res.system_prompt
  } catch (e) {
    systemPromptError.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    systemPromptLoading.value = false
  }
}

// 当 system 行被选中或切到 system-prompt tab 时拉取
watch(
  () => [props.record?.kind, activeTab.value] as const,
  ([kind, tab]) => {
    if (kind === 'system' && tab === 'system-prompt' && !systemPromptText.value && !systemPromptLoading.value) {
      loadSystemPrompt()
    }
  },
)

// 切会话清空 system prompt 缓存
watch(
  () => props.sessionId,
  () => {
    systemPromptText.value = ''
    systemPromptError.value = ''
  },
)

// ===== 兜底加载 tools（initForAgent 未调 fetchTools） =====
if (!agentStore.tools.length) {
  agentStore.fetchTools()
}
</script>

<style scoped>
.traj-inspector {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--color-bg-card);
  border-left: 1px solid var(--color-border-light);
}

.traj-inspector-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: var(--text-sm);
  color: var(--color-text-faint, var(--color-text-muted));
}

.traj-inspector-body {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

/* header */
.inspector-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.inspector-kind {
  font-size: 10px;
  font-weight: 600;
  font-family: var(--font-mono, ui-monospace, monospace);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}
.inspector-kind.user { background: rgba(17, 24, 39, 0.08); color: var(--color-text); }
.inspector-kind.assistant { background: rgba(99, 102, 241, 0.12); color: #4338ca; }
.inspector-kind.tool { background: rgba(20, 184, 166, 0.12); color: #0f766e; }
.inspector-kind.system { background: rgba(245, 158, 11, 0.12); color: #b45309; }
.inspector-kind.compaction { background: rgba(107, 114, 128, 0.12); color: #4b5563; }

.inspector-loc {
  flex: 1;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-family: var(--font-mono, ui-monospace, monospace);
}

.inspector-close {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}
.inspector-close:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

/* tabs */
.inspector-tabs {
  display: flex;
  gap: 2px;
  padding: 0 var(--space-2);
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
  overflow-x: auto;
}
.inspector-tab {
  padding: 6px 10px;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  white-space: nowrap;
  cursor: pointer;
  transition: all var(--transition-fast);
}
.inspector-tab:hover {
  color: var(--color-text);
}
.inspector-tab.active {
  color: var(--color-text);
  border-bottom-color: var(--color-text);
  font-weight: 600;
}

/* content */
.inspector-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-3);
  min-height: 0;
}

.insp-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-bottom: var(--space-3);
}
.insp-section:last-child {
  margin-bottom: 0;
}

.insp-label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-text-muted);
}

.insp-md {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card-elevated, var(--color-bg-sidebar));
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--color-text);
  max-height: 420px;
  overflow-y: auto;
}
.insp-md :deep(p:last-child) {
  margin-bottom: 0;
}

.insp-hint {
  padding: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  text-align: center;
}
.insp-hint.error {
  color: var(--color-danger);
}

.insp-pre {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  background: var(--color-bg-sidebar);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12px;
  line-height: 1.5;
  color: var(--color-text);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 420px;
  overflow-y: auto;
}
.insp-pre.error {
  border-color: var(--color-danger);
  color: var(--color-danger);
}

/* overview dl */
.insp-overview {
  margin: 0 0 var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card-elevated, var(--color-bg-sidebar));
}
.ov-row {
  display: flex;
  gap: var(--space-2);
  padding: 2px 0;
  font-size: var(--text-xs);
}
.ov-row dt {
  flex-shrink: 0;
  min-width: 72px;
  color: var(--color-text-muted);
}
.ov-row dd {
  color: var(--color-text);
}
.ov-row .ov-muted { color: var(--color-text-muted); font-style: italic; }
.ov-mono { font-family: var(--font-mono, ui-monospace, monospace); }

.status-pill {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-full);
  background: rgba(17, 24, 39, 0.06);
  color: var(--color-text-secondary);
}
.status-pill.running { background: #fef9c3; color: #a16207; }
.status-pill.failed { background: #fee2e2; color: #b91c1c; }

/* hierarchy 跳转按钮 */
.hierarchy-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.hierarchy-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
  border-color: var(--color-border);
}

/* tools tab */
.tool-provider {
  margin-bottom: var(--space-3);
}
.provider-name {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-text-muted);
  margin-bottom: var(--space-1);
}
.tool-details {
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card-elevated, var(--color-bg-sidebar));
  margin-bottom: var(--space-1);
}
.tool-summary {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  cursor: pointer;
  font-size: var(--text-xs);
  list-style: none;
}
.tool-summary::-webkit-details-marker { display: none; }
.tool-glyph { flex-shrink: 0; }
.tool-name-mono {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-weight: 600;
  color: var(--color-text);
  flex-shrink: 0;
}
.tool-desc {
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-params {
  padding: var(--space-2) var(--space-3);
  border-top: 1px solid var(--color-border-light);
  max-height: 320px;
  overflow-y: auto;
}

/* tool calls tab */
.tc-block {
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card-elevated, var(--color-bg-sidebar));
  margin-bottom: var(--space-2);
  overflow: hidden;
}
.tc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
}
.tc-name {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-weight: 600;
  font-size: var(--text-xs);
  color: var(--color-text);
}
.tc-jump {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  font-size: 10px;
  cursor: pointer;
}
.tc-jump:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}
.tc-args {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-top: 1px solid var(--color-border-light);
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12px;
  color: var(--color-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow-y: auto;
}

/* sources tab */
.source-card {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card-elevated, var(--color-bg-sidebar));
  margin-bottom: var(--space-1);
}
.source-idx {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}
.source-meta {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.source-name-row {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
.source-name {
  font-size: var(--text-sm);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-kind-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}
.source-kind-tag.web { background: rgba(17, 24, 39, 0.12); color: var(--color-text); }
.source-kind-tag.kb { background: rgba(17, 24, 39, 0.08); color: var(--color-text-secondary); }
.source-sub {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}
.source-snippet {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  line-height: 1.5;
  max-height: 3em;
  overflow: hidden;
}

/* attachments tab */
.att-card {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card-elevated, var(--color-bg-sidebar));
  margin-bottom: var(--space-1);
  font-size: var(--text-xs);
}
.att-ext {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  padding: 2px 4px;
  border-radius: var(--radius-sm);
  background: var(--color-primary-muted);
  color: var(--color-primary);
  font-size: 10px;
  font-weight: 600;
}
.att-name {
  flex: 1;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.att-size {
  color: var(--color-text-muted);
  flex-shrink: 0;
}
</style>