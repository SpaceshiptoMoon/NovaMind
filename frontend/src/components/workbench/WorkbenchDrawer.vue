<template>
  <!-- 抽屉容器：折叠态 width:0、溢出隐藏；展开态 --drawer-width（store 可拖拽调宽） -->
  <aside
    class="workbench-drawer"
    :class="{ open: workbench.drawerOpen, resizing: isResizing }"
    :style="{ '--drawer-width': `${workbench.drawerWidth}px` }"
    role="complementary"
    aria-label="工作台右侧面板"
  >
    <!-- 左缘拖拽把手：向左拖增大面板宽度（320–720 钳制），双击重置默认宽 -->
    <div
      v-if="workbench.drawerOpen"
      class="drawer-resize-handle"
      role="separator"
      aria-orientation="vertical"
      title="拖拽调整面板宽度（双击重置）"
      @pointerdown="onResizeStart"
      @dblclick="resetWidth"
    ></div>

    <div v-if="workbench.drawerOpen" class="drawer-inner">
      <!-- 顶部：视图切换 + 收起 -->
      <header class="drawer-header">
        <div class="view-switcher">
          <button
            v-for="v in tabs"
            :key="v.key"
            class="view-pill"
            :class="{ active: workbench.drawerView === v.key }"
            :title="v.label"
            @click="workbench.setView(v.key)"
          >
            <el-icon :size="12"><component :is="v.icon" /></el-icon>
            <span>{{ v.label }}</span>
            <span v-if="v.key === 'sources' && sources.length" class="pill-badge">{{
              sources.length
            }}</span>
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
            <button
              v-if="sources.length > 3"
              class="preview-more"
              @click="workbench.setView('sources')"
            >
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
                  <span v-if="s.score != null" class="source-score"
                    >相关度 {{ formatScore(s.score) }}</span
                  >
                  <a
                    v-if="s.url"
                    :href="s.url"
                    target="_blank"
                    rel="noopener"
                    class="source-link"
                    @click.stop
                    >链接 ↗</a
                  >
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
                  <span v-if="s.score != null" class="source-score"
                    >相关度 {{ formatScore(s.score) }}</span
                  >
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
            <span class="tool-detail-icon"
              ><el-icon :size="14"><SetUp /></el-icon
            ></span>
            <span class="tool-detail-name">{{ selectedToolCall.toolName }}</span>
            <span class="tool-detail-status" :class="selectedToolCall.status">{{
              statusLabel(selectedToolCall.status)
            }}</span>
            <span v-if="selectedToolCall.durationMs" class="tool-detail-duration">
              {{ selectedToolCall.durationMs }}ms
            </span>
          </div>
          <div
            v-if="Object.keys(selectedToolCall.arguments || {}).length"
            class="tool-detail-section"
          >
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

      <!-- 工作目录视图（仅 agent 单聊会话）：目录浏览器 + 绑定/解绑 -->
      <div v-else-if="workbench.drawerView === 'workspace'" class="drawer-body">
        <p class="ws-hint">
          选择本地文件夹作为智能体的工作目录，进入工作模式后启用 read / glob / grep / bash
          工具。
        </p>

        <div class="ws-browser">
          <div class="ws-browser-toolbar">
            <button
              class="ws-browser-up"
              :disabled="browseParent === null || browseLoading"
              title="上级目录"
              @click="browseParent && browseEnter(browseParent)"
            >
              <el-icon :size="12"><ArrowLeft /></el-icon>
            </button>
            <span class="ws-browser-path" :title="browsePath || '此电脑'">
              {{ browsePath || '此电脑' }}
            </span>
          </div>
          <div v-loading="browseLoading" class="ws-browser-list">
            <div
              v-for="d in browseDirs"
              :key="d.path"
              class="ws-browser-item"
              @click="browseEnter(d.path)"
            >
              <el-icon :size="14"><FolderOpened /></el-icon>
              <span class="ws-browser-name">{{ d.name }}</span>
            </div>
            <div v-if="!browseLoading && browseDirs.length === 0" class="ws-browser-empty">
              此层级无子目录
            </div>
          </div>
        </div>

        <div class="ws-selected-row">
          <span class="ws-selected-label">已选目录：</span>
          <code class="ws-selected-path" :title="browsePath">{{ browsePath || '（请选择）' }}</code>
        </div>

        <div v-if="isWorkspaceBound" class="ws-current">
          当前工作目录：<code :title="workspaceRoot">{{ workspaceRootName }}</code>
        </div>

        <div class="ws-actions">
          <button
            v-if="isWorkspaceBound"
            class="ws-btn ws-btn--danger"
            :disabled="workspaceBinding"
            @click="handleUnbindWorkspace"
          >
            退出工作模式
          </button>
          <button
            class="ws-btn ws-btn--primary"
            :disabled="!browsePath || workspaceBinding"
            @click="handleBindWorkspace"
          >
            {{ isWorkspaceBound ? '更换到此目录' : '进入工作模式' }}
          </button>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
/**
 * Agent 工作台右侧面板（DeerFlow 式侧车）：概览 / 引用来源 / 工具结果 / 消息全文 /
 * 轨迹侧车 / 工作目录六视图切换，左缘拖拽调宽。
 *
 * 数据来源分两路：sources/toolCalls 由父组件 props 传入，
 * 消息与轨迹从 agentStore 取；视图切换、开合与宽度全部托管在 workbench store。
 * 轨迹/工作目录视图仅 agent 单聊会话可用（群聊频道不显示这两个入口）。
 */
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft,
  Close,
  FolderOpened,
  Grid,
  Link,
  SetUp,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'
import { useWorkbenchStore } from '@/stores/workbench'
import { useAgentStore } from '@/stores/agent'
import { agentApi } from '@/api/agent'
import type { SourceRef, ToolCallRecord } from '@/api/types'
import {
  DRAWER_WIDTH_DEFAULT,
  DRAWER_WIDTH_MAX,
  DRAWER_WIDTH_MIN,
} from '@/stores/workbench'

const props = defineProps<{
  sources: SourceRef[]
  toolCalls: ToolCallRecord[]
}>()

const workbench = useWorkbenchStore()
const agentStore = useAgentStore()

interface DrawerTab {
  key: 'overview' | 'sources' | 'tool' | 'workspace'
  label: string
  icon: Component
}

/** 顶层 tab：概览/引用/工具全频道可用；目录仅 agent 单聊会话（有 sessionId）显示。
 *  轨迹不在面板里——它是对话页的全屏互斥视图（TrajectoryList + 内置详情栏） */
const tabs = computed<DrawerTab[]>(() => {
  const list: DrawerTab[] = [
    { key: 'overview', label: '概览', icon: Grid },
    { key: 'sources', label: '引用', icon: Link },
    { key: 'tool', label: '工具', icon: SetUp },
  ]
  if (agentStore.currentSessionId) {
    list.push({ key: 'workspace', label: '目录', icon: FolderOpened })
  }
  return list
})

// ===================== 拖拽调宽 =====================
const isResizing = ref(false)
let resizeStartX = 0
let resizeStartWidth = 0

/** 拖拽把手起始：记录初值并挂全局 pointer 监听；拖拽中禁用 width 过渡 */
function onResizeStart(e: PointerEvent) {
  isResizing.value = true
  resizeStartX = e.clientX
  resizeStartWidth = workbench.drawerWidth
  window.addEventListener('pointermove', onResizeMove)
  window.addEventListener('pointerup', onResizeEnd)
  e.preventDefault()
}

function onResizeMove(e: PointerEvent) {
  // 向左拖增大面板；上限为视口减去主聊天区保底宽度，避免把聊天区挤没
  const delta = resizeStartX - e.clientX
  const viewportMax = Math.max(DRAWER_WIDTH_MIN, window.innerWidth - 560)
  workbench.setDrawerWidth(Math.min(DRAWER_WIDTH_MAX, resizeStartWidth + delta, viewportMax))
}

function onResizeEnd() {
  isResizing.value = false
  window.removeEventListener('pointermove', onResizeMove)
  window.removeEventListener('pointerup', onResizeEnd)
}

function resetWidth() {
  workbench.setDrawerWidth(DRAWER_WIDTH_DEFAULT)
}

// ===================== 引用来源 =====================
// 引用来源展开集合
const expandedSources = ref(new Set<number>())

const webSources = computed(() => props.sources.filter((s) => s.kind === 'web'))
const kbSources = computed(() => props.sources.filter((s) => s.kind !== 'web'))

// 当前选中的工具调用记录（按 store.selectedToolCallId 匹配 callId）
const selectedToolCall = computed(
  () => props.toolCalls.find((c) => c.callId === workbench.selectedToolCallId) ?? null,
)

/** 折叠的来源摘要卡（点击展开/收起）；重建 Set 触发响应式更新 */
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
    case 'completed':
      return '完成'
    case 'running':
      return '执行中'
    case 'pending':
      return '等待中'
    case 'failed':
      return '失败'
  }
}

function formatJson(obj: Record<string, unknown>): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

// ===================== 工作目录（迁自 AgentChatView） =====================
const currentConversation = computed(
  () => agentStore.conversations.find((c) => c.session_id === agentStore.currentSessionId) || null,
)
const workspaceConfig = computed(() => currentConversation.value?.extra_config?.workspace ?? null)
const isWorkspaceBound = computed(() => !!workspaceConfig.value)
const workspaceRoot = computed(() => workspaceConfig.value?.root || '')

/** 工作目录 chip 显示名：取末段（长路径截断），title 里看全路径 */
const workspaceRootName = computed(() => {
  const p = workspaceRoot.value.replace(/\/+$/, '')
  const seg = p.split(/[\\/]/).pop() || p
  return seg.length > 18 ? `${seg.slice(0, 17)}…` : seg
})

const workspaceBinding = ref(false)
// 目录浏览态：path 空=此电脑（盘符列表），选中层即绑定目标
const browsePath = ref('')
const browseParent = ref<string | null>(null)
const browseDirs = ref<{ name: string; path: string }[]>([])
const browseLoading = ref(false)

/** 进入某层目录（列表项点击/上级按钮）；空串=回到根 */
async function browseEnter(path: string) {
  browseLoading.value = true
  try {
    const data = await agentApi.browseWorkspaceDirs(path || undefined)
    browsePath.value = data.path
    browseParent.value = data.is_root ? null : (data.parent ?? null)
    browseDirs.value = data.dirs || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '目录读取失败')
  } finally {
    browseLoading.value = false
  }
}

// 打开目录视图即从已绑定目录（或根）开始浏览
watch(
  () => workbench.drawerView === 'workspace' && workbench.drawerOpen,
  (active) => {
    if (active) browseEnter(workspaceRoot.value)
  },
)

/** 绑定：选中层即根，写会话 workspace + 自动给 agent 并入 local_workspace 勾选 */
async function handleBindWorkspace() {
  const sessionId = agentStore.currentSessionId
  if (!sessionId || !agentStore.currentAgent || !browsePath.value) return
  const root = browsePath.value
  workspaceBinding.value = true
  try {
    await agentApi.updateSessionWorkspace(sessionId, { mode: 'local', root })
    // 工具默认必带：本地模式下 local_workspace 提供者须在 agent.enabled_tools 里
    // 才会随 resolve_tools 下发 schema；未勾选时静默并入
    const agent = agentStore.currentAgent
    const tools = agent.enabled_tools || []
    if (!tools.includes('local_workspace')) {
      await agentStore.updateAgent(agent.id, {
        enabled_tools: [...tools, 'local_workspace'],
      })
    }
    // 回写会话列表里的 workspace 键（不重新拉全量）
    const conv = currentConversation.value
    if (conv) {
      conv.extra_config = { ...conv.extra_config, workspace: { mode: 'local', root } }
    }
    ElMessage.success('已进入工作模式：read / glob / grep / bash 已启用')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '绑定失败')
  } finally {
    workspaceBinding.value = false
  }
}

/** 解绑：清会话 workspace；agent 勾选保留（其他会话可能仍在用） */
async function handleUnbindWorkspace() {
  const sessionId = agentStore.currentSessionId
  if (!sessionId) return
  workspaceBinding.value = true
  try {
    await agentApi.updateSessionWorkspace(sessionId, null)
    const conv = currentConversation.value
    if (conv && conv.extra_config) {
      const next = { ...conv.extra_config }
      delete next.workspace
      conv.extra_config = next
    }
    ElMessage.success('已退出工作模式')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '解绑失败')
  } finally {
    workspaceBinding.value = false
  }
}
</script>

<style scoped>
.workbench-drawer {
  position: relative;
  width: 0;
  flex-shrink: 0;
  overflow: hidden;
  border-left: 1px solid transparent;
  background: var(--color-bg-sidebar);
  transition:
    width var(--transition-slow),
    border-color var(--transition-slow);
  display: flex;
}

.workbench-drawer.open {
  width: var(--drawer-width, 340px);
  border-left-color: var(--color-border-light);
}

/* 拖拽中禁用宽度过渡：逐帧跟手，松手后由 store 落定 */
.workbench-drawer.resizing {
  transition: none;
}

.drawer-inner {
  width: var(--drawer-width, 340px);
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}

/* 左缘拖拽把手：贴边 4px 热区，hover/拖拽时显式 */
.drawer-resize-handle {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  cursor: col-resize;
  z-index: 2;
}

.drawer-resize-handle:hover,
.workbench-drawer.resizing .drawer-resize-handle {
  background: var(--color-border-focus, var(--color-border));
  opacity: 0.5;
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
  overflow: hidden;
}

.view-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 4px 8px;
  border: 1px solid transparent;
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

/* 工作目录浏览器（迁自 AgentChatView 弹窗样式） */
.ws-hint {
  margin: 0 0 var(--space-2);
  font-size: 13px;
  color: var(--color-text-muted);
  line-height: 1.6;
}

.ws-browser {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.ws-browser-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 10px;
  border-bottom: 1px solid var(--color-border-light);
  background: var(--color-bg-elevated);
}

.ws-browser-up {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.ws-browser-up:hover:not(:disabled) {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.ws-browser-up:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.ws-browser-path {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--color-text-muted);
  direction: rtl; /* 长路径从左截断，保尾部可见 */
  text-align: left;
}

.ws-browser-list {
  max-height: 320px;
  overflow-y: auto;
  min-height: 120px;
}

.ws-browser-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 7px 12px;
  cursor: pointer;
  font-size: 13px;
  color: var(--color-text);
  transition: background var(--transition-fast);
}

.ws-browser-item:hover {
  background: var(--color-bg-hover);
}

.ws-browser-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ws-browser-empty {
  padding: 24px 0;
  text-align: center;
  font-size: 12px;
  color: var(--color-text-muted);
}

.ws-selected-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: var(--space-2);
  font-size: 12px;
}

.ws-selected-label {
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.ws-selected-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-muted, rgba(0, 0, 0, 0.04));
  font-size: 12px;
}

.ws-current {
  margin-top: var(--space-2);
  font-size: 12px;
  color: var(--color-text-muted);
}

.ws-current code {
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-muted, rgba(0, 0, 0, 0.04));
  font-size: 12px;
}

.ws-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.ws-btn {
  flex: 1;
  padding: 7px 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
  background: transparent;
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.ws-btn--primary {
  background: var(--color-btn-primary);
  border-color: var(--color-btn-primary);
  color: var(--color-btn-primary-text);
}

.ws-btn--primary:hover:not(:disabled) {
  opacity: 0.9;
}

.ws-btn--primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.ws-btn--danger {
  color: var(--color-danger);
  border-color: var(--color-danger);
}

.ws-btn--danger:hover:not(:disabled) {
  background: var(--color-danger-subtle);
}

.ws-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 窄视口：面板改右侧覆盖层，不再挤压主聊天区（与工作台侧栏浮层断点一致） */
@media (max-width: 900px) {
  .workbench-drawer.open {
    position: absolute;
    right: 0;
    top: 0;
    bottom: 0;
    z-index: var(--z-raised);
    width: min(var(--drawer-width, 340px), 85vw);
    box-shadow: var(--shadow-lg);
  }

  .workbench-drawer.open .drawer-inner {
    width: min(var(--drawer-width, 340px), 85vw);
  }
}
</style>
