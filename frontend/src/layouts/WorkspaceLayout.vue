<template>
  <div class="workspace-layout">
    <a href="#workspace-main" class="skip-link">跳到主内容</a>

    <!-- Gap div: 在文档流中占位，防止 fixed 侧边栏遮挡主内容 -->
    <div class="sidebar-gap" :class="{ collapsed: sidebarCollapsed }"></div>

    <!-- Fixed sidebar -->
    <aside class="workspace-sidebar" :class="{ collapsed: sidebarCollapsed }" role="navigation" aria-label="工作台侧边栏">
      <div class="sidebar-header">
        <!-- 展开模式：频道下拉 + 新建按钮 -->
        <template v-if="!sidebarCollapsed">
          <el-select
            v-model="activeChannelKey"
            class="channel-select"
            @change="handleChannelChange"
          >
            <el-option-group label="核心">
              <el-option
                v-for="ch in primaryChannels"
                :key="ch.key"
                :label="ch.label"
                :value="ch.key"
              >
                <div class="channel-option">
                  <NavIcon :name="ch.icon" :size="16" />
                  <span>{{ ch.label }}</span>
                </div>
              </el-option>
            </el-option-group>
            <el-option-group label="更多">
              <el-option
                v-for="ch in moreChannels"
                :key="ch.key"
                :label="ch.label"
                :value="ch.key"
              >
                <div class="channel-option">
                  <NavIcon :name="ch.icon" :size="16" />
                  <span>{{ ch.label }}</span>
                </div>
              </el-option>
            </el-option-group>
            <template #prefix>
              <NavIcon :name="activeChannel.icon" :size="16" />
            </template>
          </el-select>
          <button class="new-btn" @click="handleNew">
            <el-icon :size="14"><Plus /></el-icon>
          </button>
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
              @click="switchChannel(ch.key)"
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
                @click="switchChannel(ch.key)"
              >
                <NavIcon :name="ch.icon" :size="20" />
              </button>
            </template>
          </div>
        </template>
      </div>

      <!-- Sidebar content -->
      <div class="sidebar-body" v-show="!sidebarCollapsed">
        <!-- Chat: session list -->
        <template v-if="activeChannelKey === 'chat'">
          <div class="list-area">
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
        </template>

        <!-- Agents: agent list -->
        <template v-else-if="activeChannelKey === 'agents'">
          <div class="list-area">
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
        </template>

        <!-- Research: space list -->
        <template v-else-if="activeChannelKey === 'research'">
          <div class="list-area">
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
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, provide } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Delete, DArrowLeft, DArrowRight, More } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import { useSpaceStore } from '@/stores/space'
import { useChatStore } from '@/stores/chat'
import NavIcon from '@/components/common/NavIcon.vue'
import type { Agent } from '@/api/types'

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const spaceStore = useSpaceStore()
const chatStore = useChatStore()

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

const activeChannel = computed(() =>
  channels.find(c => c.key === activeChannelKey.value) || channels[0],
)

const currentResearchSpaceId = computed(() => String(route.params.spaceId ?? ''))
const researchSpaces = computed(() => spaceStore.spaces)

function switchChannel(key: string) {
  activeChannelKey.value = key
  handleChannelChange(key)
}

// Sync activeChannelKey with route
function syncChannelFromRoute() {
  const path = route.path
  if (path.includes('/workspace/chat')) activeChannelKey.value = 'chat'
  else if (path.includes('/workspace/agents')) activeChannelKey.value = 'agents'
  else if (path.includes('/workspace/research')) activeChannelKey.value = 'research'
  else if (path.includes('/workspace/skills')) activeChannelKey.value = 'skills'
  else if (path.includes('/workspace/clawmate')) activeChannelKey.value = 'clawmate'
}

function handleChannelChange(key: string) {
  const map: Record<string, string> = {
    chat: '/home/workspace/chat',
    agents: '/home/workspace/agents',
    research: '/home/workspace/research',
    skills: '/home/workspace/skills',
    clawmate: '/home/workspace/clawmate',
  }
  router.push(map[key] || map.chat)
}

function handleNew() {
  switch (activeChannelKey.value) {
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

.new-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.new-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-muted);
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
  background: var(--el-color-primary-light-9);
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
  background: var(--el-color-primary-light-9);
}

.list-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: var(--space-1);
  bottom: var(--space-1);
  width: 3px;
  border-radius: var(--radius-sm);
  background: var(--color-primary);
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
}

/* Skip link */
.skip-link {
  position: absolute;
  top: -100%;
  left: var(--space-4);
  padding: var(--space-2) var(--space-4);
  background: var(--color-primary);
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
