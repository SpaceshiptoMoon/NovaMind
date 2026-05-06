<template>
  <div class="workspace-layout">
    <aside class="workspace-sidebar">
      <!-- Channel tabs -->
      <div class="channel-tabs">
        <button
          v-for="ch in channels"
          :key="ch.key"
          class="channel-tab"
          :class="{ active: activeChannel === ch.key }"
          @click="switchChannel(ch.key)"
        >
          <NavIcon :name="ch.icon" :size="16" />
          <span>{{ ch.label }}</span>
        </button>
      </div>

      <div class="sidebar-divider" />

      <!-- Channel-specific content -->
      <div class="sidebar-body">
        <!-- Chat channel -->
        <template v-if="activeChannel === 'chat'">
          <div class="list-empty">选择对话或开始新对话</div>
        </template>

        <!-- Agent channel: agent list -->
        <template v-else-if="activeChannel === 'agents'">
          <div class="sidebar-action">
            <button class="action-btn" @click="openCreateAgentDialog">
              <el-icon :size="14"><Plus /></el-icon>
              <span>创建智能体</span>
            </button>
          </div>
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

        <!-- Research channel -->
        <template v-else-if="activeChannel === 'research'">
          <div class="sidebar-action">
            <button class="action-btn" @click="handleNewResearch">
              <el-icon :size="14"><Plus /></el-icon>
              <span>新研究</span>
            </button>
          </div>
          <div class="research-info">
            <p class="info-text">对特定主题进行深度研究，自动搜索并生成报告。</p>
          </div>
          <div v-if="researchSpaces.length" class="list-area">
            <div class="section-label">知识空间</div>
            <div
              v-for="space in researchSpaces"
              :key="space.id"
              class="list-item"
              :class="{ active: currentResearchSpaceId === String(space.id) }"
              @click="handleSelectResearchSpace(space.id)"
            >
              <span class="item-title">{{ space.name }}</span>
            </div>
          </div>
        </template>
      </div>
    </aside>

    <!-- Main content -->
    <main class="workspace-main">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, provide, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, ArrowLeft } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import { useSpaceStore } from '@/stores/space'
import NavIcon from '@/components/common/NavIcon.vue'
import type { Agent } from '@/api/types'

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const spaceStore = useSpaceStore()

provide('isInWorkspace', true)

const selectedAgentId = ref<number | null>(null)

const channels = [
  { key: 'chat', label: 'AI 对话', icon: 'chat' },
  { key: 'agents', label: '智能体', icon: 'agents' },
  { key: 'research', label: '深度研究', icon: 'research' },
]

const activeChannel = computed(() => {
  const path = route.path
  if (path.includes('/workspace/chat')) return 'chat'
  if (path.includes('/workspace/agents')) return 'agents'
  if (path.includes('/workspace/research')) return 'research'
  return 'chat'
})

const currentResearchSpaceId = computed(() => String(route.params.spaceId ?? ''))
const researchSpaces = computed(() => spaceStore.spaces)

function switchChannel(key: string) {
  const map: Record<string, string> = {
    chat: '/home/workspace/chat',
    agents: '/home/workspace/agents',
    research: '/home/workspace/research',
  }
  router.push(map[key] || map.chat)
}

// ===================== Agents =====================

function openCreateAgentDialog() {
  // Emit event to AgentView via route query
  router.push({ path: '/home/workspace/agents', query: { action: 'create' } })
}

function handleSelectAgent(agent: Agent) {
  selectedAgentId.value = agent.id
  agentStore.currentAgent = agent
  agentStore.fetchConversations(agent.id)
  router.push({ name: 'WorkspaceAgents' })
}

function goBackToAgents() {
  selectedAgentId.value = null
  agentStore.currentAgent = null
  router.push('/home/workspace/agents')
}

// ===================== Research =====================

function handleNewResearch() {
  router.push('/home/workspace/research')
}

function handleSelectResearchSpace(spaceId: number) {
  router.push(`/home/workspace/research/${spaceId}`)
}

// ===================== Init =====================

watch(activeChannel, (channel) => {
  if (channel === 'agents' && agentStore.agents.length === 0) {
    agentStore.fetchAgents()
    agentStore.fetchSkills()
    agentStore.fetchMcpServers()
  }
})

onMounted(async () => {
  await Promise.all([
    agentStore.fetchAgents(),
    agentStore.fetchSkills(),
    agentStore.fetchMcpServers(),
    spaceStore.spaces.length === 0 ? spaceStore.fetchSpaces() : Promise.resolve(),
  ])
})
</script>

<style scoped>
.workspace-layout {
  display: flex;
  height: 100%;
  background: var(--color-bg);
  overflow: hidden;
}

/* ========================================
   Sidebar
   ======================================== */
.workspace-sidebar {
  width: 280px;
  border-right: 1px solid var(--color-border-light);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  background: var(--color-bg-card);
}

.channel-tabs {
  display: flex;
  gap: 2px;
  padding: var(--space-3) var(--space-3) 0;
}

.channel-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-2);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: var(--font-body);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.channel-tab:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.channel-tab.active {
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  font-weight: var(--weight-medium);
}

.sidebar-divider {
  height: 1px;
  background: var(--color-border-light);
  margin: var(--space-3);
}

.sidebar-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

/* Action button */
.sidebar-action {
  padding: 0 var(--space-3) var(--space-2);
  display: flex;
  gap: var(--space-2);
}

.action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  padding: var(--space-2);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: var(--font-body);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.action-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-muted);
}

/* List area */
.list-area {
  flex: 1;
  overflow-y: auto;
  padding: 0 var(--space-2) var(--space-2);
}

.list-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
  margin-bottom: 2px;
  position: relative;
}

.list-item:hover {
  background: var(--color-bg-hover);
}

.list-item.active {
  background: var(--color-primary-muted);
}

.list-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  border-radius: 2px;
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
  background: linear-gradient(135deg, #E8F0FE 0%, #FEF1EE 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-primary);
  flex-shrink: 0;
}

/* Research */
.research-info {
  padding: var(--space-3);
}

.info-text {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin: 0;
  line-height: var(--leading-relaxed);
}

.section-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: var(--space-2) var(--space-3) var(--space-1);
}

/* ========================================
   Main Content
   ======================================== */
.workspace-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}
</style>
