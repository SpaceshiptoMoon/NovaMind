<template>
  <div class="workspace-layout">
    <a href="#workspace-main" class="skip-link">跳到主内容</a>

    <!-- Gap div: 在文档流中占位，防止 fixed 侧边栏遮挡主内容 -->
    <div class="sidebar-gap" :class="{ collapsed: sidebarCollapsed }"></div>

    <!-- Fixed sidebar -->
    <aside class="workspace-sidebar" :class="{ collapsed: sidebarCollapsed }" role="navigation" aria-label="工作台侧边栏">
      <div class="sidebar-header">
        <!-- 展开模式：WorkBuddy 风格频道 pill tabs。点击 tab 即「新建/开启」对应频道 -->
        <template v-if="!sidebarCollapsed">
          <nav class="channel-tabs" role="tablist" aria-label="工作台频道">
            <button
              v-for="ch in channels"
              :key="ch.key"
              class="channel-tab"
              :class="{ active: activeChannelKey === ch.key }"
              role="tab"
              :aria-selected="activeChannelKey === ch.key"
              :title="ch.label"
              @click="activateChannel(ch.key)"
            >
              <NavIcon :name="ch.icon" :size="16" />
              <span class="channel-tab-label">{{ ch.label }}</span>
            </button>
          </nav>
        </template>
        <!-- 折叠模式：频道 icon 列表 -->
        <template v-else>
          <div class="channel-icons">
            <button
              v-for="ch in primaryChannels"
              :key="ch.key"
              class="channel-icon-btn"
              :class="{ active: activeChannelKey === ch.key }"
              :title="ch.label"
              @click="activateChannel(ch.key)"
            >
              <NavIcon :name="ch.icon" :size="20" />
            </button>
            <button
              class="channel-icon-btn more-toggle"
              :class="{ active: moreChannels.some(c => c.key === activeChannelKey) }"
              :title="moreExpanded ? '收起更多' : '更多功能'"
              @click="moreExpanded = !moreExpanded"
            >
              <el-icon :size="20"><More /></el-icon>
            </button>
            <template v-if="moreExpanded">
              <button
                v-for="ch in moreChannels"
                :key="ch.key"
                class="channel-icon-btn"
                :class="{ active: activeChannelKey === ch.key }"
                :title="ch.label"
                @click="activateChannel(ch.key)"
              >
                <NavIcon :name="ch.icon" :size="20" />
              </button>
            </template>
          </div>
        </template>
      </div>

      <!-- Sidebar content -->
      <div class="sidebar-body" v-show="!sidebarCollapsed">
        <!-- Chat: session list（可折叠） -->
        <template v-if="activeChannelKey === 'chat'">
          <div class="list-section">
            <button class="list-section-header" @click="toggleSection('chat')">
              <span class="list-section-title">最近对话</span>
              <span class="list-section-count">{{ chatStore.sessions.length }}</span>
              <el-icon :size="12" class="list-section-chevron" :class="{ collapsed: sectionCollapsed.chat }">
                <ArrowDown />
              </el-icon>
            </button>
            <div v-show="!sectionCollapsed.chat" class="list-area">
              <div
                v-for="session in chatStore.sessions"
                :key="session.session_id"
                class="list-item"
                :class="{ active: chatStore.currentSessionId === session.session_id }"
                @click="handleSelectChatSession(session.session_id)"
              >
                <span class="item-title">{{ session.preview || '新对话' }}</span>
                <button class="item-delete" @click.stop="handleDeleteChatSession(session.session_id)">
                  <el-icon :size="12"><Delete /></el-icon>
                </button>
              </div>
              <div v-if="chatStore.sessions.length === 0" class="list-empty">暂无对话记录</div>
            </div>
          </div>
        </template>

        <!-- Agents: agent list（可折叠） -->
        <template v-else-if="activeChannelKey === 'agents'">
          <div class="list-section">
            <button class="list-section-header" @click="toggleSection('agents')">
              <span class="list-section-title">我的智能体</span>
              <span class="list-section-count">{{ agentStore.agents.length }}</span>
              <el-icon :size="12" class="list-section-chevron" :class="{ collapsed: sectionCollapsed.agents }">
                <ArrowDown />
              </el-icon>
            </button>
            <div v-show="!sectionCollapsed.agents" class="list-area">
              <div
                v-for="agent in agentStore.agents"
                :key="agent.id"
                class="list-item"
                :class="{ active: selectedAgentId === agent.id }"
                @click="handleSelectAgent(agent)"
              >
                <div class="agent-avatar-sm">{{ agent.name.charAt(0) }}</div>
                <div class="item-info">
                  <span class="item-title">{{ agent.name }}</span>
                  <span class="item-desc">{{ agent.description || '暂无描述' }}</span>
                </div>
              </div>
              <div v-if="agentStore.agents.length === 0" class="list-empty">暂无智能体</div>
            </div>
          </div>
        </template>

        <!-- Research: space list（可折叠） -->
        <template v-else-if="activeChannelKey === 'research'">
          <div class="list-section">
            <button class="list-section-header" @click="toggleSection('research')">
              <span class="list-section-title">知识空间</span>
              <span class="list-section-count">{{ researchSpaces.length }}</span>
              <el-icon :size="12" class="list-section-chevron" :class="{ collapsed: sectionCollapsed.research }">
                <ArrowDown />
              </el-icon>
            </button>
            <div v-show="!sectionCollapsed.research" class="list-area">
              <div
                v-for="space in researchSpaces"
                :key="space.id"
                class="list-item"
                :class="{ active: currentResearchSpaceId === String(space.id) }"
                @click="handleSelectResearchSpace(space.id)"
              >
                <span class="item-title">{{ space.name }}</span>
              </div>
              <div v-if="researchSpaces.length === 0" class="list-empty">暂无知识空间</div>
            </div>
          </div>
        </template>

        <!-- Skills -->
        <template v-else-if="activeChannelKey === 'skills'">
          <div class="sidebar-info">
            <p class="info-text">发现、上传和分享 AI 技能，安装到你的智能体中。</p>
          </div>
        </template>

        <!-- ClawMate -->
        <template v-else-if="activeChannelKey === 'clawmate'">
          <div class="sidebar-info">
            <p class="info-text">ClawMate：AI 智能对话助手，支持工具调用和上下文分析。</p>
          </div>
        </template>
      </div>
    </aside>

    <!-- Collapse toggle -->
    <button
      class="sidebar-toggle"
      :class="{ 'is-collapsed': sidebarCollapsed }"
      @click="sidebarCollapsed = !sidebarCollapsed"
      :aria-label="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
      :aria-expanded="!sidebarCollapsed"
    >
      <el-icon :size="14">
        <DArrowLeft v-if="!sidebarCollapsed" />
        <DArrowRight v-else />
      </el-icon>
    </button>

    <!-- Main content -->
    <main class="workspace-main" id="workspace-main" role="main">
      <div class="workspace-content">
        <router-view />
      </div>
      <!-- 右抽屉：引用来源 / 工具结果。折叠态 width:0 不占位 -->
      <WorkbenchDrawer :sources="drawerSources" :tool-calls="drawerToolCalls" />
      <!-- 抽屉展开按钮（抽屉关闭时浮在主区右上角） -->
      <button
        v-if="!workbench.drawerOpen"
        class="drawer-toggle"
        title="打开引用面板"
        @click="workbench.openDrawer('overview')"
      >
        <el-icon :size="14"><Expand /></el-icon>
      </button>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted, provide, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Delete, DArrowLeft, DArrowRight, More, Expand, ArrowDown } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import { useSpaceStore } from '@/stores/space'
import { useChatStore } from '@/stores/chat'
import { useWorkbenchStore } from '@/stores/workbench'
import NavIcon from '@/components/common/NavIcon.vue'
import WorkbenchDrawer from '@/components/workbench/WorkbenchDrawer.vue'
import type { Agent, ChatSource, SourceRef, ToolCallRecord } from '@/api/types'

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const spaceStore = useSpaceStore()
const chatStore = useChatStore()
const workbench = useWorkbenchStore()

provide('isInWorkspace', true)

const sidebarCollapsed = ref(false)
const selectedAgentId = ref<number | null>(null)

const channels = [
  { key: 'chat', label: 'AI 对话', icon: 'chat', group: 'primary' },
  { key: 'agents', label: '智能体', icon: 'agents', group: 'primary' },
  { key: 'research', label: '深度研究', icon: 'research', group: 'more' },
  { key: 'skills', label: '技能广场', icon: 'apps', group: 'more' },
  { key: 'clawmate', label: 'ClawMate', icon: 'chat', group: 'more' },
] as const

const primaryChannels = computed(() => channels.filter(c => c.group === 'primary'))
const moreChannels = computed(() => channels.filter(c => c.group === 'more'))

const activeChannelKey = ref('chat')
const moreExpanded = ref(false)

// 下方列表的折叠态：每个频道独立记忆
const sectionCollapsed = reactive({
  chat: false,
  agents: false,
  research: false,
})

function toggleSection(key: 'chat' | 'agents' | 'research') {
  sectionCollapsed[key] = !sectionCollapsed[key]
}

const currentResearchSpaceId = computed(() => String(route.params.spaceId ?? ''))
const researchSpaces = computed(() => spaceStore.spaces)

// ===================== 右抽屉数据聚合 =====================
// 按当前频道从对应 store 聚合 sources / toolCalls 喂给抽屉。
// chat: 来源在 chatStore.messages[].extra.sources（ChatSource[]）
// agents: 来源在 agentStore.messages[].sources（SourceRef[]），工具记录在 agentStore.toolCalls
// 其它频道暂无数据，抽屉显示空态。
function toSourceRef(s: ChatSource): SourceRef {
  return {
    index: s.index,
    kind: s.kind ?? 'kb',
    document_id: s.document_id ?? null,
    document_name: s.document_name ?? null,
    kb_id: s.kb_id ?? null,
    chunk_id: s.chunk_id ?? null,
    score: s.score ?? null,
    snippet: s.snippet ?? null,
    page: s.page ?? null,
    url: s.url ?? null,
  }
}

const drawerSources = computed<SourceRef[]>(() => {
  if (activeChannelKey.value === 'chat') {
    const out: SourceRef[] = []
    for (const m of chatStore.messages) {
      const raw = (m.extra?.sources as ChatSource[] | undefined) ?? undefined
      if (raw) out.push(...raw.map(toSourceRef))
    }
    return out
  }
  if (activeChannelKey.value === 'agents') {
    const out: SourceRef[] = []
    for (const m of agentStore.messages) {
      if (m.sources) out.push(...m.sources)
    }
    return out
  }
  return []
})

const drawerToolCalls = computed<ToolCallRecord[]>(() => {
  if (activeChannelKey.value === 'agents') return agentStore.toolCalls
  return []
})

// 点 tab 即「激活并新建/开启」该频道：对话开新对话、智能体进入创建、其余跳转
function activateChannel(key: string) {
  activeChannelKey.value = key
  handleNew(key)
}

// 切换频道时重置抽屉选中态，避免残留上一频道工具结果
watch(activeChannelKey, () => workbench.resetSelection())

// Sync activeChannelKey with route
function syncChannelFromRoute() {
  const path = route.path
  if (path.includes('/workspace/chat')) activeChannelKey.value = 'chat'
  else if (path.includes('/workspace/agents')) activeChannelKey.value = 'agents'
  else if (path.includes('/workspace/research')) activeChannelKey.value = 'research'
  else if (path.includes('/workspace/skills')) activeChannelKey.value = 'skills'
  else if (path.includes('/workspace/clawmate')) activeChannelKey.value = 'clawmate'
}

// 按频道执行「新建/开启」动作。chat=开启新对话；agents=进入创建；其余=跳转到对应入口
function handleNew(key: string = activeChannelKey.value) {
  switch (key) {
    case 'chat':
      chatStore.clearMessages()
      router.push('/home/workspace/chat')
      break
    case 'agents':
      router.push({ path: '/home/workspace/agents', query: { action: 'create' } })
      break
    case 'research':
      router.push('/home/workspace/research')
      break
    case 'skills':
      router.push('/home/workspace/skills')
      break
    case 'clawmate':
      router.push('/home/workspace/clawmate')
      break
  }
}

// ===================== Chat =====================

async function handleSelectChatSession(sessionId: string) {
  await chatStore.fetchMessages(sessionId)
  chatStore.fetchSessionConfig(sessionId)
  router.push('/home/workspace/chat')
}

async function handleDeleteChatSession(sessionId: string) {
  try {
    await chatStore.deleteSession(sessionId)
  } catch {
    ElMessage.error('删除对话失败')
  }
}

// ===================== Agents =====================

function handleSelectAgent(agent: Agent) {
  selectedAgentId.value = agent.id
  agentStore.currentAgent = agent
  agentStore.fetchConversations(agent.id)
  router.push({ name: 'WorkspaceAgents' })
}

// ===================== Research =====================

function handleSelectResearchSpace(spaceId: number) {
  router.push(`/home/workspace/research/${spaceId}`)
}

// ===================== Init =====================

onMounted(async () => {
  syncChannelFromRoute()
  await Promise.all([
    agentStore.fetchAgents(),
    agentStore.fetchTools(),
    agentStore.fetchMcpServers(),
    spaceStore.spaces.length === 0 ? spaceStore.fetchSpaces() : Promise.resolve(),
    chatStore.fetchSessions(),
  ])
})
</script>

<style scoped>
.workspace-layout {
  display: flex;
  flex: 1;
  min-height: 0;
  background: var(--color-bg);
  overflow: hidden;
  position: relative;
}

/* ========================================
   Sidebar Gap — 在文档流中占位
   ======================================== */
.sidebar-gap {
  width: var(--sidebar-width);
  flex-shrink: 0;
  transition: width var(--transition-slow);
}

.sidebar-gap.collapsed {
  width: var(--sidebar-width-collapsed);
}

/* ========================================
   Sidebar — fixed 覆盖层
   ======================================== */
.workspace-sidebar {
  position: fixed;
  top: var(--header-height);
  left: 0;
  bottom: 0;
  width: var(--sidebar-width);
  z-index: var(--z-raised);
  background: var(--color-bg-sidebar);
  border-right: 1px solid var(--color-border-light);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width var(--transition-slow);
}

.workspace-sidebar.collapsed {
  width: var(--sidebar-width-collapsed);
  border-right-color: transparent;
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3);
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.channel-select {
  flex: 1;
}

.channel-select :deep(.el-input__wrapper) {
  border-radius: var(--radius-lg);
}

.channel-option {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text);
}

/* ========================================
   Channel Tabs (WorkBuddy 风格 pill tabs)
   ======================================== */
.channel-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

.channel-tab {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
  width: 100%;
  text-align: left;
}

.channel-tab:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.channel-tab.active {
  background: var(--color-bg-hover);
  color: var(--color-text);
  font-weight: var(--weight-medium, 500);
}

/* active tab：文字黑、图标保留青绿点缀 */
.channel-tab.active :deep(svg) {
  color: var(--color-primary);
}

.channel-tab-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ========================================
   可折叠列表分组
   ======================================== */
.list-section {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
}

.list-section-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  cursor: pointer;
  user-select: none;
  flex-shrink: 0;
}

.list-section-header:hover {
  background: var(--color-bg-hover);
}

.list-section-title {
  flex: 1;
  text-align: left;
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold, 600);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.list-section-count {
  font-size: var(--text-xs);
  color: var(--color-text-faint, var(--color-text-muted));
}

.list-section-chevron {
  color: var(--color-text-muted);
  transition: transform var(--transition-fast);
}

.list-section-chevron.collapsed {
  transform: rotate(-90deg);
}

/* 折叠时 list-area 隐藏，section 收成一条 header */
.list-section > .list-area {
  flex: 1;
  overflow-y: auto;
}

/* ========================================
   Channel Icon Buttons (collapsed mode)
   ======================================== */
.channel-icons {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) 0;
  width: 100%;
}

.channel-icon-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-lg);
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.channel-icon-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.channel-icon-btn.active {
  background: var(--color-bg-hover);
  color: var(--color-primary);
}

/* Sidebar body */
.sidebar-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.list-area {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

.list-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
  margin-bottom: var(--space-1);
  position: relative;
}

.list-item:hover {
  background: var(--color-bg-hover);
}

.list-item.active {
  background: var(--color-bg-hover);
}

.list-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: var(--space-1);
  bottom: var(--space-1);
  width: 3px;
  border-radius: var(--radius-sm);
  background: var(--color-text);
}

.item-title {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-desc {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.item-delete {
  opacity: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.list-item:hover .item-delete {
  opacity: 1;
}

.item-delete:hover {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

.list-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-faint);
}

.agent-avatar-sm {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-md);
  background: var(--color-primary-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-primary);
  flex-shrink: 0;
}

.sidebar-info {
  padding: var(--space-4);
}

.info-text {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin: 0;
  line-height: var(--leading-relaxed);
}

/* ========================================
   Sidebar Toggle — fixed 定位
   ======================================== */
.sidebar-toggle {
  position: fixed;
  top: 50%;
  transform: translateY(-50%);
  z-index: var(--z-raised);
  width: 20px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-border-light);
  border-left: none;
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  background: var(--color-bg-card);
  color: var(--color-text-muted);
  cursor: pointer;
  transition: left var(--transition-slow);
  left: var(--sidebar-width);
}

.sidebar-toggle:hover {
  color: var(--color-text-secondary);
  background: var(--color-bg-hover);
}

.sidebar-toggle.is-collapsed {
  left: var(--sidebar-width-collapsed);
}

/* ========================================
   Main Content
   ======================================== */
.workspace-main {
  flex: 1;
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: flex;
}

.workspace-content {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* 抽屉折叠时浮在主区右上角的展开按钮 */
.drawer-toggle {
  position: absolute;
  top: var(--space-3);
  right: var(--space-3);
  z-index: var(--z-raised);
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card, #fff);
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
  box-shadow: var(--shadow-sm);
}

.drawer-toggle:hover {
  color: var(--color-primary);
  border-color: var(--color-border-focus);
}

/* Skip link */
.skip-link {
  position: absolute;
  top: -100%;
  left: var(--space-4);
  padding: var(--space-2) var(--space-4);
  background: var(--color-btn-primary);
  color: #FFFFFF;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  z-index: var(--z-toast);
  text-decoration: none;
  transition: top var(--transition-fast);
}

.skip-link:focus {
  top: var(--space-2);
}

/* Responsive: auto-collapse sidebar below 900px */
@media (max-width: 900px) {
  .sidebar-gap {
    display: none;
  }

  .workspace-sidebar {
    box-shadow: var(--shadow-lg);
  }

  .workspace-sidebar.collapsed {
    box-shadow: none;
  }

  .sidebar-toggle {
    left: 0;
  }

  .sidebar-toggle.is-collapsed {
    left: 0;
  }
}
</style>
