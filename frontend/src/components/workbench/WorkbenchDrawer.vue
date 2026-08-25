<template>
  <!-- 抽屉容器：折叠态 width:0、溢出隐藏；展开态 --drawer-width -->
  <aside
    class="workbench-drawer"
    :class="{ open: workbench.drawerOpen }"
    role="complementary"
    aria-label="工作台右侧抽屉"
  >
    <div v-if="workbench.drawerOpen" class="drawer-inner">
      <!-- 顶部：视图切换 + 收起 -->
      <header class="drawer-header">
        <div class="view-switcher">
          <button
            v-for="v in views"
            :key="v.key"
            class="view-pill"
            :class="{ active: workbench.drawerView === v.key }"
            @click="workbench.setView(v.key)"
          >
            {{ v.label }}
            <span v-if="v.key === 'sources' && sources.length" class="pill-badge">{{ sources.length }}</span>
          </button>
        </div>
        <button class="drawer-close" title="收起右栏" @click="workbench.closeDrawer()">
          <el-icon :size="14"><Close /></el-icon>
        </button>
      </header>

      <!-- 概览视图：产物占位 + 引用来源入口 -->
      <div v-if="workbench.drawerView === 'overview'" class="drawer-body">
        <section class="overview-section">
          <div class="section-title">产物</div>
          <div class="overview-empty">暂无内容</div>
        </section>
        <section class="overview-section">
          <button
            class="section-title section-title--link"
            :disabled="!sources.length"
            @click="workbench.setView('sources')"
          >
            <span>引用来源</span>
            <span class="section-count">{{ sources.length }}</span>
          </button>
          <div v-if="sources.length" class="overview-source-preview">
            <div v-for="s in sources.slice(0, 3)" :key="s.index" class="preview-item">
              <span class="preview-index">{{ s.index }}</span>
              <span class="preview-name">{{ displayName(s) }}</span>
            </div>
            <button v-if="sources.length > 3" class="preview-more" @click="workbench.setView('sources')">
              查看全部 {{ sources.length }} 条
            </button>
          </div>
          <div v-else class="overview-empty">暂无引用</div>
        </section>
      </div>

      <!-- 引用来源视图 -->
      <div v-else-if="workbench.drawerView === 'sources'" class="drawer-body">
        <div v-if="!sources.length" class="drawer-empty">暂无引用来源</div>
        <div v-else class="source-list-wrap">
          <template v-if="webSources.length">
            <div class="source-group-title web">🌐 联网来源</div>
            <div
              v-for="s in webSources"
              :key="s.index"
              class="source-card"
              :class="{ expanded: expandedSources.has(s.index) }"
              @click="toggleSource(s.index)"
            >
              <span class="source-index">{{ s.index }}</span>
              <div class="source-meta">
                <div class="source-name-row">
                  <span class="source-name" :title="displayName(s)">{{ displayName(s) }}</span>
                  <span class="source-kind web">联网</span>
                </div>
                <div class="source-sub">
                  <span v-if="s.score != null" class="source-score">相关度 {{ formatScore(s.score) }}</span>
                  <a
                    v-if="s.url"
                    :href="s.url"
                    target="_blank"
                    rel="noopener"
                    class="source-link"
                    @click.stop
                  >链接 ↗</a>
                </div>
                <div v-if="s.snippet" class="source-snippet">{{ s.snippet }}</div>
              </div>
            </div>
          </template>
          <template v-if="kbSources.length">
            <div class="source-group-title kb">📚 知识库来源</div>
            <div
              v-for="s in kbSources"
              :key="s.index"
              class="source-card"
              :class="{ expanded: expandedSources.has(s.index) }"
              @click="toggleSource(s.index)"
            >
              <span class="source-index">{{ s.index }}</span>
              <div class="source-meta">
                <div class="source-name-row">
                  <span class="source-name" :title="displayName(s)">{{ displayName(s) }}</span>
                  <span class="source-kind kb">知识库</span>
                </div>
                <div class="source-sub">
                  <span v-if="s.score != null" class="source-score">相关度 {{ formatScore(s.score) }}</span>
                  <span v-if="s.page != null" class="source-page">第 {{ s.page }} 页</span>
                </div>
                <div v-if="s.snippet" class="source-snippet">{{ s.snippet }}</div>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- 工具结果视图 -->
      <div v-else-if="workbench.drawerView === 'tool'" class="drawer-body">
        <div v-if="!selectedToolCall" class="drawer-empty">未选中工具调用</div>
        <div v-else class="tool-detail">
          <div class="tool-detail-header">
            <span class="tool-detail-icon"><el-icon :size="14"><SetUp /></el-icon></span>
            <span class="tool-detail-name">{{ selectedToolCall.toolName }}</span>
            <span
              class="tool-detail-status"
              :class="selectedToolCall.status"
            >{{ statusLabel(selectedToolCall.status) }}</span>
            <span v-if="selectedToolCall.durationMs" class="tool-detail-duration">
              {{ selectedToolCall.durationMs }}ms
            </span>
          </div>
          <div v-if="Object.keys(selectedToolCall.arguments || {}).length" class="tool-detail-section">
            <div class="tool-detail-label">参数</div>
            <pre class="tool-detail-json">{{ formatJson(selectedToolCall.arguments) }}</pre>
          </div>
          <div v-if="selectedToolCall.result" class="tool-detail-section">
            <div class="tool-detail-label">结果</div>
            <pre class="tool-detail-json">{{ selectedToolCall.result }}</pre>
          </div>
          <div v-else-if="selectedToolCall.status === 'running'" class="tool-detail-section">
            <div class="tool-detail-label">结果</div>
            <div class="tool-detail-running">执行中…</div>
          </div>
        </div>
      </div>

      <!-- 消息全文视图（轨迹视图选中 assistant/user 行，展示 reasoning/content） -->
      <div v-else-if="workbench.drawerView === 'message'" class="drawer-body">
        <div v-if="!selectedMessage" class="drawer-empty">未选中消息</div>
        <div v-else class="message-detail">
          <div class="message-detail-header">
            <span class="message-detail-role" :class="selectedMessage.role">{{ roleLabel(selectedMessage.role) }}</span>
            <span v-if="selectedMessage.iteration != null" class="message-detail-iter">第 {{ selectedMessage.iteration }} 轮</span>
          </div>
          <div v-if="selectedMessage.reasoning" class="message-detail-section">
            <div class="tool-detail-label">思考过程</div>
            <div class="message-detail-md"><MarkdownRenderer :content="selectedMessage.reasoning" /></div>
          </div>
          <div v-if="selectedMessage.content" class="message-detail-section">
            <div class="tool-detail-label">内容</div>
            <div class="message-detail-md"><MarkdownRenderer :content="selectedMessage.content" /></div>
          </div>
          <div v-if="!selectedMessage.content && !selectedMessage.reasoning" class="drawer-empty">
            该消息无文本内容
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Close, SetUp } from '@element-plus/icons-vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useAgentStore } from '@/stores/agent'
import type { SourceRef, ToolCallRecord, AgentMessage } from '@/api/types'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'

const props = defineProps<{
  sources: SourceRef[]
  toolCalls: ToolCallRecord[]
}>()

const workbench = useWorkbenchStore()

const views = [
  { key: 'overview' as const, label: '概览' },
  { key: 'sources' as const, label: '引用来源' },
  { key: 'tool' as const, label: '工具结果' },
  { key: 'message' as const, label: '消息' },
]

// 引用来源展开集合
const expandedSources = ref(new Set<number>())

const webSources = computed(() => props.sources.filter((s) => s.kind === 'web'))
const kbSources = computed(() => props.sources.filter((s) => s.kind !== 'web'))

// 当前选中的工具调用记录（按 store.selectedToolCallId 匹配 callId）
const selectedToolCall = computed(
  () => props.toolCalls.find((c) => c.callId === workbench.selectedToolCallId) ?? null,
)

// 消息全文视图：从 agentStore.messages 按 selectedMessageId 查（message view 仅 agent 频道触发）
const agentStore = useAgentStore()
const selectedMessage = computed(
  () => agentStore.messages.find((m) => m.id === workbench.selectedMessageId) ?? null,
)

function roleLabel(role: AgentMessage['role']): string {
  switch (role) {
    case 'user': return 'USER'
    case 'assistant': return 'ASSISTANT'
    case 'system': return 'SYSTEM'
    case 'tool': return 'TOOL'
    case 'compaction': return 'COMPACTED'
    case 'plan': return 'PLAN'
    case 'notice': return 'NOTICE'
  }
}

function toggleSource(index: number) {
  const next = new Set(expandedSources.value)
  if (next.has(index)) next.delete(index)
  else next.add(index)
  expandedSources.value = next
}

function displayName(s: SourceRef): string {
  return s.document_name || s.url || `来源 ${s.index}`
}

function formatScore(score: number): string {
  return Math.round(score * 100) + '%'
}

function statusLabel(status: ToolCallRecord['status']): string {
  switch (status) {
    case 'completed': return '完成'
    case 'running': return '执行中'
    case 'pending': return '等待中'
    case 'failed': return '失败'
  }
}

function formatJson(obj: Record<string, unknown>): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}
</script>

<style scoped>
.workbench-drawer {
  width: 0;
  flex-shrink: 0;
  overflow: hidden;
  border-left: 1px solid transparent;
  background: var(--color-bg-sidebar);
  transition: width var(--transition-slow), border-color var(--transition-slow);
  display: flex;
}

.workbench-drawer.open {
  width: var(--drawer-width, 340px);
  border-left-color: var(--color-border-light);
}

.drawer-inner {
  width: var(--drawer-width, 340px);
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}

/* ========================================
   Header
   ======================================== */
.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-3);
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.view-switcher {
  display: flex;
  gap: var(--space-1);
  flex: 1;
  min-width: 0;
}

.view-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
}

.view-pill:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.view-pill.active {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-text);
  font-weight: var(--weight-medium, 500);
}

.pill-badge {
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: var(--radius-full);
  background: var(--color-text-secondary);
  color: #fff;
  font-size: 10px;
  line-height: 16px;
  text-align: center;
}

.drawer-close {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.drawer-close:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

/* ========================================
   Body
   ======================================== */
.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-3);
  min-height: 0;
}

.drawer-empty,
.overview-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-faint, var(--color-text-muted));
}

/* 概览 */
.overview-section {
  margin-bottom: var(--space-4);
}

.section-title {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold, 600);
  color: var(--color-text);
  margin-bottom: var(--space-2);
}

.section-title--link {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 0;
  font: inherit;
  color: inherit;
}

.section-title--link:hover:not(:disabled) {
  color: var(--color-primary);
}

.section-title--link:disabled {
  cursor: default;
  color: var(--color-text-muted);
}

.section-count {
  font-size: var(--text-xs);
  font-weight: var(--weight-regular, 400);
  color: var(--color-text-muted);
}

.overview-source-preview {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.preview-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.preview-item:hover {
  background: var(--color-bg-hover);
}

.preview-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  font-size: 10px;
  font-weight: 600;
}

.preview-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-more {
  align-self: flex-start;
  margin-top: var(--space-1);
  background: transparent;
  border: none;
  padding: 0;
  font-size: var(--text-xs);
  color: var(--color-primary);
  cursor: pointer;
}

.preview-more:hover {
  text-decoration: underline;
}

/* 引用来源 */
.source-list-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.source-group-title {
  font-size: var(--text-xs);
  font-weight: 600;
  padding: var(--space-2) var(--space-1) var(--space-1);
  color: var(--color-text-muted);
}

.source-card {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
  background: var(--color-bg-card, #fff);
}

.source-card:hover {
  background: var(--color-bg-hover);
}

.source-index {
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
  flex: 1;
  min-width: 0;
  font-size: var(--text-sm);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-kind {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}

.source-kind.web {
  background: rgba(17, 24, 39, 0.12);
  color: var(--color-text);
}

.source-kind.kb {
  background: rgba(17, 24, 39, 0.08);
  color: var(--color-text-secondary);
}

.source-sub {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.source-link {
  color: var(--color-primary);
  text-decoration: none;
}

.source-link:hover {
  text-decoration: underline;
}

.source-snippet {
  margin-top: 2px;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  line-height: 1.5;
  max-height: 3em;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.source-card.expanded .source-snippet {
  max-height: none;
  -webkit-line-clamp: unset;
}

/* 工具结果 */
.tool-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.tool-detail-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card, #fff);
}

.tool-detail-icon {
  color: var(--color-text-muted);
}

.tool-detail-name {
  flex: 1;
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold, 600);
  color: var(--color-text);
}

.tool-detail-status {
  font-size: var(--text-xs);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}

.tool-detail-status.completed {
  background: rgba(17, 24, 39, 0.06);
  color: var(--color-text-secondary);
}

.tool-detail-status.running {
  background: #fef9c3;
  color: #a16207;
}

.tool-detail-status.failed {
  background: #fee2e2;
  color: #b91c1c;
}

.tool-detail-duration {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.tool-detail-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.tool-detail-label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-text-muted);
}

.tool-detail-json {
  margin: 0;
  padding: var(--space-2);
  background: var(--color-bg-sidebar);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12px;
  line-height: 1.5;
  color: var(--color-text);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 320px;
  overflow-y: auto;
}

.tool-detail-running {
  padding: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  text-align: center;
}

/* 消息全文 */
.message-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.message-detail-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card, #fff);
}

.message-detail-role {
  font-size: var(--text-xs);
  font-weight: 600;
  font-family: var(--font-mono, ui-monospace, monospace);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}

.message-detail-role.assistant {
  background: rgba(99, 102, 241, 0.12);
  color: #4338ca;
}

.message-detail-role.user {
  background: rgba(17, 24, 39, 0.08);
  color: var(--color-text);
}

.message-detail-role.tool {
  background: rgba(20, 184, 166, 0.12);
  color: #0f766e;
}

.message-detail-iter {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.message-detail-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.message-detail-md {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card, #fff);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--color-text);
  max-height: 360px;
  overflow-y: auto;
}

.message-detail-md :deep(p:last-child) {
  margin-bottom: 0;
}
</style>