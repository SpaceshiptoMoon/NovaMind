<template>
  <div class="workspace-layout">
    <a href="#workspace-main" class="skip-link">跳到主内容</a>

    <!-- 顶栏：全宽置顶（全局导航 + 全局项） -->
    <AppHeader
      :sidebar-collapsed="isWorkspaceRoute ? sidebarCollapsed : undefined"
      @toggle-sidebar="sidebarCollapsed = !sidebarCollapsed"
    />

    <!-- 下方：侧栏（上下文列表，可折叠；仅工作台路由） + 主内容。
         侧栏在全部工作台路由（含 agent 对话页）常驻文档流：单栏承担
         「agent/群目录 + 会话子列表」，对话页主区只留聊天画布 -->
    <div class="workspace-body">
      <aside
        v-if="isWorkspaceRoute"
        class="workspace-sidebar"
        :class="{ collapsed: sidebarCollapsed }"
        role="navigation"
        aria-label="工作台侧边栏"
      >
        <!-- 展开模式：上下文列表 -->
        <template v-if="!sidebarCollapsed">
          <div class="sidebar-body">
            <!-- 会话中心：按主体分组（助手/协作群作分组头，组内挂各自会话）；
                 头部「新建对话」开统一创建弹窗、「助手」开助手管理抽屉 -->
            <div class="list-section">
              <div class="list-section-header">
                <span class="list-section-title">会话</span>
                <button class="header-action" title="助手管理" @click="openAgentDrawer()">
                  助手
                </button>
              </div>
              <div v-loading="recentSessionsLoading" class="list-area">
                <template v-for="cat in groupedSessions" :key="cat.key">
                  <!-- 分类头：纯文字类名 + 会话数（点击进该类最近会话）；管理动作收在「助手」抽屉与条目 hover -->
                  <div class="session-group-head">
                    <button
                      class="session-group-toggle"
                      :aria-expanded="!collapsedCategories.has(cat.key)"
                      @click="toggleCategory(cat.key)"
                    >
                      <el-icon
                        :size="12"
                        class="session-group-chevron"
                        :class="{ collapsed: collapsedCategories.has(cat.key) }"
                      >
                        <ArrowDown />
                      </el-icon>
                      <span class="session-group-name">{{ cat.label }}</span>
                      <span class="session-group-count">{{ cat.sessions.length }}</span>
                    </button>
                    <!-- 分类级创建入口：协作类直接展开协作配置；本地项目类创建后自动弹目录绑定 -->
                    <button
                      v-if="cat.key !== 'group'"
                      class="session-group-add"
                      title="新建对话"
                      @click.stop="openUnifiedCreate('agent', cat.key === 'workspace')"
                    >
                      <el-icon :size="12"><Plus /></el-icon>
                    </button>
                    <button
                      v-else
                      class="session-group-add"
                      title="新建协作对话"
                      @click.stop="openUnifiedCreate('group')"
                    >
                      <el-icon :size="12"><Plus /></el-icon>
                    </button>
                  </div>
                  <!-- 类内会话条目：标题 + 归属名两行，点击续聊；协作条目 hover 带群管理 -->
                  <div
                    v-for="s in cat.sessions"
                    v-show="!collapsedCategories.has(cat.key)"
                    :key="s.session_id"
                    class="session-item"
                    :class="{ active: isAgentSessionActive(s) || isGroupSessionActive(s) }"
                    @click="handleOpenSession(s)"
                  >
                    <div class="session-item-info">
                      <span class="session-title">{{ sessionDisplayTitle(s) }}</span>
                      <span class="session-item-desc">{{ sessionDesc(s) }}</span>
                    </div>
                    <div class="session-item-actions" @click.stop>
                      <template v-if="s.kind === 'group'">
                        <button class="session-delete" title="编辑协作对话" @click="openGroupDialog(null, s.ref_id)">
                          <el-icon :size="12"><EditPen /></el-icon>
                        </button>
                        <button
                          class="session-delete"
                          title="解散协作对话"
                          @click="handleDissolveGroup({ id: s.ref_id, name: s.name })"
                        >
                          <el-icon :size="12"><Delete /></el-icon>
                        </button>
                      </template>
                      <button
                        class="session-delete"
                        title="删除会话"
                        @click="s.kind === 'agent' ? handleDeleteConversation(s.session_id) : handleDeleteGroupSession(s.session_id)"
                      >
                        <el-icon :size="12"><Delete /></el-icon>
                      </button>
                    </div>
                  </div>
                </template>
                <div
                  v-if="recentSessions.length === 0 && !recentSessionsLoading"
                  class="list-empty"
                >
                  暂无会话
                </div>
              </div>
            </div>

          </div>
        </template>

        <!-- 折叠模式：图标栏（新建 + agent 首字头像快捷切换），填满 48px 空白柱；
             对话页页内已有会话栏，rail 主体让位只留展开键 -->
        <div
          v-else
          class="sidebar-rail"
          role="toolbar"
          :aria-label="inChatRoute ? '侧边栏开关' : '智能体快捷操作'"
        >
          <template v-if="!inChatRoute">
            <button class="rail-btn rail-new" title="创建智能体" @click="openAgentDialog()">
              <el-icon :size="16"><Plus /></el-icon>
            </button>
            <div class="rail-agents">
              <button
                v-for="agent in agentStore.agents"
                :key="agent.id"
                class="rail-btn rail-agent"
                :class="{ active: isAgentChatRoute(agent.id) }"
                :title="agent.name"
                @click="handleSelectAgent(agent)"
              >
                {{ agent.name.charAt(0) }}
              </button>
            </div>
            <div class="rail-groups">
              <button
                v-for="group in groupStore.groups"
                :key="group.id"
                class="rail-btn rail-group"
                :class="{ active: isGroupChatRoute(group.id) }"
                :title="group.name"
                @click="handleSelectGroup(group)"
              >
                <NavIcon name="group" :size="15" />
              </button>
            </div>
          </template>
          <button
            class="rail-btn rail-expand"
            title="展开侧边栏"
            aria-expanded="false"
            @click="sidebarCollapsed = false"
          >
            <el-icon :size="14"><ArrowRight /></el-icon>
          </button>
        </div>

        <!-- 右缘吸附折叠手柄：展开态 ‹ 收起 / 折叠态 › 展开（悬停浮现，吸附在边框线上） -->
        <button
          class="sidebar-collapse-handle"
          :title="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
          :aria-expanded="!sidebarCollapsed"
          @click="sidebarCollapsed = !sidebarCollapsed"
        >
          <el-icon :size="12"><ArrowLeft v-if="!sidebarCollapsed" /><ArrowRight v-else /></el-icon>
        </button>
      </aside>

      <!-- 统一创建对话弹窗 + 助手管理抽屉 + Agent 编辑弹窗 + 协作编辑弹窗 + 配置抽屉（表单逻辑收编在 manage 组件；append-to-body 需挂布局层） -->
      <UnifiedCreateDialog
        v-model="unifiedCreateVisible"
        :preset="unifiedCreatePreset"
        :auto-bind="unifiedCreateAutoBind"
        @created="fetchRecentSessions"
      />
      <el-drawer
        v-model="agentDrawerVisible"
        direction="rtl"
        size="320px"
        :append-to-body="true"
      >
        <template #header>
          <div class="drawer-header">
            <span class="drawer-title">助手管理</span>
            <el-button type="primary" size="small" @click="openAgentDialog()">
              <el-icon :size="12"><Plus /></el-icon>
              <span>创建助手</span>
            </el-button>
          </div>
        </template>
        <div class="drawer-agent-list">
          <!-- 创建入口常驻列表首位（主按钮形态，不与 hover 动作竞争） -->
          <button class="drawer-create-entry" @click="openAgentDialog()">
            <span class="drawer-create-icon">
              <el-icon :size="16"><Plus /></el-icon>
            </span>
            <span class="drawer-create-info">
              <span class="drawer-create-title">创建助手</span>
              <span class="drawer-create-desc">定义人设、模型与工具</span>
            </span>
          </button>
          <div
            v-for="agent in agentStore.agents"
            :key="agent.id"
            class="list-item drawer-agent-item"
          >
            <div class="agent-avatar-sm">{{ agent.name.charAt(0) }}</div>
            <div class="item-info">
              <span class="item-title">{{ agent.name }}</span>
              <span class="item-desc">{{ agent.description || '暂无描述' }}</span>
            </div>
            <div class="item-actions">
              <button class="item-action-btn" title="配置" @click="openAgentConfig(agent)">
                <el-icon :size="12"><Setting /></el-icon>
              </button>
              <button class="item-action-btn" title="编辑" @click="openAgentDialog(agent)">
                <el-icon :size="12"><EditPen /></el-icon>
              </button>
              <button
                class="item-action-btn item-action-btn--danger"
                title="删除"
                @click="handleDeleteAgent(agent)"
              >
                <el-icon :size="12"><Delete /></el-icon>
              </button>
            </div>
          </div>
          <div v-if="agentStore.agents.length === 0" class="list-empty">
            还没有助手——点击上方「创建助手」开始
          </div>
        </div>
      </el-drawer>
      <AgentFormDialog v-model="agentFormVisible" :agent="agentFormTarget" />
      <GroupFormDialog v-model="groupFormVisible" :group-id="groupFormTarget" />
      <AgentConfigDrawer v-model="configDrawerVisible" :agent="configAgent" />

      <main class="workspace-main" id="workspace-main" role="main">
        <div class="workspace-content" :class="{ 'is-page': !isWorkspaceRoute }">
          <router-view v-slot="{ Component }">
            <transition name="fade" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </div>
        <!-- 右抽屉：引用来源 / 工具结果 / 工作目录（仅单聊路由——数据源是 agentStore，
             群聊路由挂载会显示单聊残留数据，故不挂）折叠态 width:0 不占位 -->
        <WorkbenchDrawer
          v-if="inAgentChatRoute"
          :sources="drawerSources"
          :tool-calls="drawerToolCalls"
        />
        <!-- 面板展开按钮（面板关闭时浮在主区右上角，仅单聊路由） -->
        <button
          v-if="inAgentChatRoute && !workbench.drawerOpen"
          class="drawer-toggle"
          title="打开工作面板"
          @click="workbench.openDrawer('sources')"
        >
          <el-icon :size="14"><Expand /></el-icon>
        </button>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 工作台主布局：全宽顶栏 + 可折叠侧栏 + 主内容区
 *
 * 侧栏仅在工作台路由渲染（上下文列表）；skip-link 供键盘导航。
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Delete,
  Expand,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  Plus,
  Setting,
  EditPen,
} from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import { useAgentGroupStore } from '@/stores/agentGroup'
import { useWorkbenchStore } from '@/stores/workbench'
import { agentApi } from '@/api/agent'
import AppHeader from './AppHeader.vue'
import WorkbenchDrawer from '@/components/workbench/WorkbenchDrawer.vue'
import NavIcon from '@/components/common/NavIcon.vue'
import AgentFormDialog from '@/components/agent/manage/AgentFormDialog.vue'
import GroupFormDialog from '@/components/agent/manage/GroupFormDialog.vue'
import UnifiedCreateDialog from '@/components/agent/manage/UnifiedCreateDialog.vue'
import AgentConfigDrawer from '@/components/agent/manage/AgentConfigDrawer.vue'
import { formatDate } from '@/utils/format'
import type { Agent, AgentGroup, RecentSessionItem, SourceRef, ToolCallRecord } from '@/api/types'

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const groupStore = useAgentGroupStore()
const workbench = useWorkbenchStore()


const sidebarCollapsed = ref(false)

const isWorkspaceRoute = computed(() => route.path.startsWith('/home/workspace'))

// ===================== 会话中心（按主体分组：助手/协作群作分组头，组内挂各自会话） =====================

const recentSessions = ref<RecentSessionItem[]>([])
const recentSessionsLoading = ref(false)

async function fetchRecentSessions() {
  recentSessionsLoading.value = true
  try {
    const data = await agentApi.listRecentSessions()
    recentSessions.value = data.items || []
  } catch {
    recentSessions.value = []
  } finally {
    recentSessionsLoading.value = false
  }
}

function isAgentSessionActive(item: RecentSessionItem): boolean {
  return isAgentChatRoute(item.ref_id) && agentStore.currentSessionId === item.session_id
}

function isGroupSessionActive(item: RecentSessionItem): boolean {
  return isGroupChatRoute(item.ref_id) && groupStore.currentSessionId === item.session_id
}

/**
 * 会话中心条目统一入口（单聊/协作同路）：跳直达路由 /chat/:sessionId，
 * 由 SessionEntryView 拉会话详情判 kind 后转跳单聊/群聊页（批3）。
 */
function handleOpenSession(item: RecentSessionItem) {
  // 已在该会话页内（store 当前会话即目标）：不绕行直达入口，避免视图重挂闪烁
  if (isAgentSessionActive(item) || isGroupSessionActive(item)) return
  router.push({ name: 'WorkspaceSessionChat', params: { sessionId: item.session_id } })
}

// ===================== 主体分组视图模型（按助手/协作群聚合会话） =====================

/** 会话中心固定三分类：助手对话 / 本地项目（绑定工作目录的单聊）/ 协作对话 */
type SessionCategoryKey = "agent" | "workspace" | "group"

interface SessionCategory {
  key: SessionCategoryKey
  label: string
  sessions: RecentSessionItem[]
}

const SESSION_CATEGORY_DEFS: { key: SessionCategoryKey; label: string }[] = [
  { key: "agent", label: "助手对话" },
  { key: "workspace", label: "本地项目" },
  { key: "group", label: "协作对话" },
]

/** 会话按用途分三类：类间固定顺序，类内沿用端点 updated_at 倒序；空类不占位 */
const groupedSessions = computed<SessionCategory[]>(() => {
  const buckets: Record<SessionCategoryKey, RecentSessionItem[]> = {
    agent: [],
    workspace: [],
    group: [],
  }
  for (const item of recentSessions.value) {
    if (item.kind === "group") buckets.group.push(item)
    else if (item.workspace_bound) buckets.workspace.push(item)
    else buckets.agent.push(item)
  }
  return SESSION_CATEGORY_DEFS.map((c) => ({ ...c, sessions: buckets[c.key] })).filter(
    (c) => c.sessions.length > 0,
  )
})

/** 条目主标题：单聊未命名回退「新对话」，协作回退更新时间 */
function sessionDisplayTitle(item: RecentSessionItem): string {
  if (item.title) return item.title
  return item.kind === "agent" ? "新对话" : formatDate(item.updated_at)
}

/** 条目归属副标题：单聊=助手名，协作=成员名（缺员回退人数） */
function sessionDesc(item: RecentSessionItem): string {
  if (item.kind === "agent") return item.name
  if (item.members && item.members.length > 0) return item.members.join("、")
  return item.member_count != null ? `${item.member_count} 人` : item.name
}

/** 分类折叠态：类头点击切换（会话内存态，默认全展开） */
const collapsedCategories = ref(new Set<SessionCategoryKey>())

function toggleCategory(key: SessionCategoryKey) {
  const next = new Set(collapsedCategories.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedCategories.value = next
}

// ===================== 助手管理抽屉（会话中心头部的「助手」入口） =====================

const agentDrawerVisible = ref(false)

function openAgentDrawer() {
  agentDrawerVisible.value = true
}

// ===================== 右抽屉数据聚合 =====================
// 统一对话面后所有聊天数据都在 agentStore：来源在 messages[].sources（SourceRef[]），
// 工具记录在 toolCalls。chat 频道（即 agent 聊天）与 agents 频道共用同一份数据。
const drawerSources = computed<SourceRef[]>(() => {
  const out: SourceRef[] = []
  for (const m of agentStore.messages) {
    if (m.sources) out.push(...m.sources)
  }
  return out
})

const drawerToolCalls = computed<ToolCallRecord[]>(() => agentStore.toolCalls)

// ===================== Agents =====================

// 当前路由是否正处某 agent 的对话页（侧栏列表 active 态）
function isAgentChatRoute(agentId: number): boolean {
  return route.name === 'WorkspaceAgentChat' && Number(route.params.agentId) === agentId
}

// 对话页（单聊/群聊）页内自带会话侧栏：折叠态 rail 的 agent/群聊轨道与其重复，
// 此时 rail 主体不渲染、只留展开键（用户点进对话即已离开「全局切换」场景）；
// WorkspaceSessionChat 是会话直达过渡页，同属会话上下文
const inChatRoute = computed(
  () =>
    route.name === 'WorkspaceAgentChat' ||
    route.name === 'WorkspaceGroupChat' ||
    route.name === 'WorkspaceSessionChat',
)

// 单聊路由（WorkspaceAgentChat）：右抽屉与其浮动展开按钮仅在此挂载——
// 抽屉数据源是 agentStore（单聊），群聊路由挂载会显示残留数据
const inAgentChatRoute = computed(() => route.name === 'WorkspaceAgentChat')

// 点 agent 条目（rail 折叠态快捷轨道）：直接进对话页
function handleSelectAgent(agent: Agent) {
  agentStore.currentAgent = agent
  agentStore.fetchConversations(agent.id)
  router.push({ name: 'WorkspaceAgentChat', params: { agentId: agent.id } })
}

// ===================== 会话子列表动作（单栏合并：页内会话栏已删，会话切换收编布局层） =====================

async function handleDeleteConversation(sessionId: string) {
  try {
    await ElMessageBox.confirm('确定删除此对话？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await agentStore.deleteConversation(sessionId)
    // 删的是当前会话则回欢迎态
    if (agentStore.currentSessionId === sessionId) agentStore.clearChat()
    ElMessage.success('对话已删除')
    fetchRecentSessions()
  } catch {
    // cancelled
  }
}

async function handleDeleteGroupSession(sessionId: string) {
  try {
    await ElMessageBox.confirm('删除后该会话的时间线与成员讨论上下文将一并清除，确定删除？', '删除会话', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await groupStore.deleteSession(sessionId)
    fetchRecentSessions()
  } catch (e) {
    if (e instanceof Error) ElMessage.error(e.message)
    // 取消则静默
  }
}

// ===================== 统一创建对话弹窗（分区 + 号共用：选 1 人直进单聊，≥2 人转协作配置） =====================

const unifiedCreateVisible = ref(false)
const unifiedCreatePreset = ref<'agent' | 'group'>('agent')
const unifiedCreateAutoBind = ref(false)

function openUnifiedCreate(preset: 'agent' | 'group' = 'agent', autoBind = false) {
  unifiedCreatePreset.value = preset
  unifiedCreateAutoBind.value = autoBind
  unifiedCreateVisible.value = true
}

// ===================== Agent 创建/编辑弹窗 + 配置抽屉（表单逻辑在 manage 组件内） =====================

const agentFormVisible = ref(false)
const agentFormTarget = ref<Agent | null>(null)

/** 不传 agent = 创建；传 = 编辑（弹窗打开即回填，system_prompt 由组件拉详情补齐） */
function openAgentDialog(agent?: Agent) {
  agentFormTarget.value = agent ?? null
  agentFormVisible.value = true
}

async function handleDeleteAgent(agent: Agent) {
  try {
    await ElMessageBox.confirm(`确定删除智能体 "${agent.name}" 吗？`, '删除', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await agentStore.deleteAgent(agent.id)
    // 删除的是当前对话中的 agent 时退出对话页
    if (isAgentChatRoute(agent.id)) {
      router.push('/home/workspace/chat')
    }
    ElMessage.success('智能体已删除')
    fetchRecentSessions()
  } catch {
    // cancelled
  }
}

// ===================== 群聊（侧栏分区 + 建/编辑弹窗 + 解散） =====================

function isGroupChatRoute(groupId: number): boolean {
  return route.name === 'WorkspaceGroupChat' && Number(route.params.groupId) === groupId
}

function handleSelectGroup(group: AgentGroup) {
  router.push({ name: 'WorkspaceGroupChat', params: { groupId: group.id } })
}

// 占位页经 inject 调用建群弹窗（与单聊 openAgentDialog 同收编模式）

// 群条目「编辑」与空态页「创建群聊」共用弹窗：groupId 非空 = 编辑（弹窗拉详情回填）
const groupFormVisible = ref(false)
const groupFormTarget = ref<number | null>(null)

function openGroupDialog(_agent?: unknown, groupId?: number) {
  groupFormTarget.value = groupId ?? null
  groupFormVisible.value = true
}

/** 解散群聊：参数取 {id, name} 结构（legacy 群条目与会话中心协作条目两处复用） */
async function handleDissolveGroup(group: { id: number; name: string }) {
  try {
    await ElMessageBox.confirm(`确定解散群聊 "${group.name}" 吗？`, '解散群聊', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await groupStore.deleteGroup(group.id)
    // 解散的是当前群时退到对话入口
    if (isGroupChatRoute(group.id)) {
      router.push('/home/workspace/chat')
    }
    ElMessage.success('群已解散')
    fetchRecentSessions()
  } catch {
    // cancelled
  }
}

// ===================== Agent 配置抽屉 =====================

const configAgent = ref<Agent | null>(null)
const configDrawerVisible = ref(false)

function openAgentConfig(agent: Agent) {
  configAgent.value = agent
  configDrawerVisible.value = true
}

// ===================== Init =====================

onMounted(async () => {
  // 窄视口（开发者工具/小窗）默认折叠侧栏，避免遮挡内容
  if (window.innerWidth < 900) sidebarCollapsed.value = true
  await Promise.all([
    agentStore.fetchAgents(),
    agentStore.fetchTools(),
    agentStore.fetchMcpServers(),
    groupStore.fetchGroups(),
    fetchRecentSessions(),
  ])
})
</script>

<style scoped>
.workspace-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  min-height: 0;
  background: var(--color-bg);
  overflow: hidden;
  position: relative;
}

/* ========================================
   Body — 顶栏下方：侧栏 + 主内容
   ======================================== */
.workspace-body {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
  /* 定位参照：抽屉浮动拉出按钮 absolute 定位须锚定在本层（顶栏之下），
     否则回溯到 layout 顶层被 56px 顶栏盖住不可点 */
  position: relative;
}

/* ========================================
   Sidebar — 顶栏下方首列（频道分段 + 上下文列表）
   ======================================== */
.workspace-sidebar {
  width: var(--sidebar-width);
  flex-shrink: 0;
  height: 100%;
  /* 侧栏磨砂玻璃：透出全局氛围背景（body::before 墨水晕） */
  background: var(--glass-bg);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(1.3);
  backdrop-filter: blur(var(--glass-blur)) saturate(1.3);
  border-right: 1px solid var(--glass-border-hairline);
  box-shadow: inset -1px 0 0 var(--glass-border), 1px 0 8px rgba(10, 10, 10, 0.03);
  display: flex;
  flex-direction: column;
  overflow: visible; /* 右缘折叠手柄外突一半，hidden 会裁掉；内层各自管理滚动 */
  position: relative; /* 折叠手柄 absolute 定位锚点 */
  transition: width var(--transition-slow);
}

@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .workspace-sidebar { background: var(--color-bg-sidebar); }
}

.workspace-sidebar.collapsed {
  width: var(--sidebar-width-collapsed);
  border-right-color: transparent;
}

/* 右缘吸附折叠手柄：骑在侧栏右边框线上（右缘外突一半），垂直居中；
   默认低调（淡边框浅底），悬停侧栏或手柄本体时浮现为主色 */
.sidebar-collapse-handle {
  position: absolute;
  right: -12px;
  top: 50%;
  transform: translateY(-50%);
  z-index: var(--z-raised);
  width: 24px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: var(--color-bg-card, #fff);
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 0;
  opacity: 0;
  transition:
    opacity var(--transition-fast),
    color var(--transition-fast),
    border-color var(--transition-fast);
}

/* 悬停侧栏任意位置或手柄本体时浮现；键盘聚焦同现（可达性） */
.workspace-sidebar:hover .sidebar-collapse-handle,
.sidebar-collapse-handle:hover,
.sidebar-collapse-handle:focus-visible {
  opacity: 1;
}

.sidebar-collapse-handle:hover {
  color: var(--color-primary);
  border-color: var(--color-border-focus);
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

/* 群分区与智能体分区同构：不抢主区滚动（分区各自内部滚），占高度按内容收缩 */
.list-section--group {
  flex: 0 1 auto;
}

.list-section--group > .list-area {
  flex: 0 1 auto;
  max-height: 32vh;
}

/* 分区头：标题（点击折叠）+ 创建 + 号并列——常驻创建动作收进一行 */
.list-section-header {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  width: 100%;
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
  flex-shrink: 0;
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

/* 会话中心头部动作钮：文字小钮（「助手」/「新建对话」） */
.header-action {
  display: flex;
  align-items: center;
  padding: 3px var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  font-family: var(--font-body);
  font-size: var(--text-xs);
  cursor: pointer;
  flex-shrink: 0;
  white-space: nowrap;
  transition: all var(--transition-fast);
}

.header-action:hover {
  background: var(--color-primary-muted);
  color: var(--color-primary);
}

.header-action--primary {
  color: var(--color-primary);
  font-weight: var(--weight-semibold);
}

/* 助手管理抽屉：复用 list-item 结构，行本体不可点（动作在 hover 钮上） */
.drawer-agent-list {
  display: flex;
  flex-direction: column;
}

.drawer-agent-item {
  cursor: default;
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.drawer-title {
  font-size: var(--text-base);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

/* 创建条目：常驻列表首位的主入口（与助手条目同构但可点、主色强调） */
.drawer-create-entry {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-3);
  margin-bottom: var(--space-2);
  border: 1px dashed var(--color-primary);
  border-radius: var(--radius-md);
  background: var(--color-primary-muted);
  cursor: pointer;
  text-align: left;
  font-family: var(--font-body);
  transition: all var(--transition-fast);
}

.drawer-create-entry:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
  filter: brightness(0.97);
}

.drawer-create-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  background: var(--color-primary);
  color: var(--color-btn-primary-text);
  flex-shrink: 0;
}

.drawer-create-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.drawer-create-title {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
}

.drawer-create-desc {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

/* 主体分组头：纯文字名 + 会话数（点击进最近会话），hover 浮现管理动作 */
.session-group-head {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-2) var(--space-1) var(--space-1);
  margin-top: var(--space-1);
}

.session-group-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  padding: 2px 4px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background var(--transition-fast);
}

.session-group-toggle:hover {
  background: var(--color-bg-hover);
}

.session-group-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold, 600);
  color: var(--color-text-secondary);
}

.session-group-count {
  font-size: var(--text-xs);
  color: var(--color-text-faint, var(--color-text-muted));
  flex-shrink: 0;
}

.session-group-chevron {
  color: var(--color-text-muted);
  transition: transform var(--transition-fast);
  flex-shrink: 0;
}

.session-group-chevron.collapsed {
  transform: rotate(-90deg);
}

/* 分类级新建 + 号：hover 类头浮现 */
.session-group-add {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  flex-shrink: 0;
  opacity: 0;
  transition: all var(--transition-fast);
}

.session-group-head:hover .session-group-add,
.session-group-add:hover {
  opacity: 1;
}

.session-group-add:hover {
  background: var(--color-primary-muted);
  color: var(--color-primary);
}

.session-group-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity var(--transition-fast);
  flex-shrink: 0;
}

.session-group-head:hover .session-group-actions {
  opacity: 1;
}

/* 类内条目两行结构：标题 + 归属名，hover 浮现动作组 */
.session-item-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.session-item-desc {
  font-size: 11px;
  color: var(--color-text-faint, var(--color-text-muted));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-item-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity var(--transition-fast);
  flex-shrink: 0;
}

.session-item:hover .session-item-actions {
  opacity: 1;
}

.session-item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: 5px var(--space-2);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--transition-fast);
  position: relative;
}

.session-item:hover {
  background: var(--color-bg-hover);
}

.session-item.active {
  background: var(--color-bg-hover);
}

.session-item.active .session-title {
  color: var(--color-text);
  font-weight: var(--weight-medium);
}

.session-title {
  flex: 1;
  min-width: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: var(--leading-normal);
}

.session-delete {
  opacity: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.session-item:hover .session-delete {
  opacity: 1;
}

.session-delete:hover {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

.session-empty {
  padding: var(--space-3) var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

/* 折叠时 list-area 隐藏，section 收成一条 header */
.list-section > .list-area {
  flex: 1;
  overflow-y: auto;
}

/* ========================================
   折叠态图标栏：新建 + agent 头像快捷切换 + 展开按钮
   ======================================== */
.sidebar-rail {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) 0 var(--space-2);
  min-height: 0;
  overflow: hidden;
}

.rail-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-muted);
  font-family: var(--font-display);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  cursor: pointer;
  flex-shrink: 0;
  padding: 0;
  transition: all var(--transition-fast);
}

.rail-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.rail-new {
  color: var(--color-text-muted);
}

.rail-new:hover {
  color: var(--color-primary);
  border-color: var(--color-border);
  background: var(--color-primary-muted);
}

.rail-agents {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) 0;
  width: 100%;
  /* 隐藏滚动条但保留滚动：头像列是视觉条，不露轨道 */
  scrollbar-width: none;
}

.rail-agents::-webkit-scrollbar {
  display: none;
}

.rail-agent {
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}

.rail-agent:hover {
  background: var(--color-bg-card, #fff);
  color: var(--color-text);
  box-shadow: var(--shadow-xs);
}

.rail-agent.active {
  background: var(--color-primary-muted);
  color: var(--color-primary);
}

/* 群聊快捷图标组：与 agent 头像列之间留白分隔（不画分割线） */
.rail-groups {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) 0 var(--space-1);
  width: 100%;
  flex-shrink: 0;
  max-height: 40vh;
  overflow-y: auto;
  scrollbar-width: none;
}

.rail-groups::-webkit-scrollbar {
  display: none;
}

.rail-group {
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}

.rail-group:hover {
  background: var(--color-bg-card, #fff);
  color: var(--color-text);
  box-shadow: var(--shadow-xs);
}

.rail-group.active {
  background: var(--color-primary-muted);
  color: var(--color-primary);
}

.rail-expand {
  color: var(--color-text-muted);
}

.rail-expand:hover {
  color: var(--color-primary);
  border-color: var(--color-border-focus);
}

/* Sidebar body */
.sidebar-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  padding-top: var(--space-2);
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
  /* 中性首字头像（与知识库 kb-avatar 同款）：accent 不浸染中性面 */
  background: var(--color-bg-hover);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text-secondary);
  flex-shrink: 0;
}

/* agent 条目 hover 动作组（配置/编辑/删除） */
.item-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity var(--transition-fast);
  flex-shrink: 0;
}

.list-item:hover .item-actions {
  opacity: 1;
}

.item-action-btn {
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
}

.item-action-btn:hover {
  background: var(--color-bg-card);
  color: var(--color-text);
  box-shadow: var(--shadow-xs);
}

.item-action-btn--danger:hover {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
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
  /* 定位包含块必须闭合在本层：内层视图（ChatView 等）用 absolute+inset:0 铺满，
     若本层非定位祖先会越级命中 .workspace-main，抽屉展开后视图仍按主区全宽绘制
     盖住抽屉（现象即「点开引用面板没反应」） */
  position: relative;
}

/* 非工作台页面（首页/知识空间/系统等）：页内滚动（各页面自管 padding，
   原 MainLayout .main-content 的 padding 由页面自身样式承接） */
.workspace-content.is-page {
  overflow-y: auto;
}

.fade-enter-active {
  transition:
    opacity var(--transition-base),
    transform var(--transition-base);
}

.fade-leave-active {
  transition: opacity var(--transition-fast);
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.fade-leave-to {
  opacity: 0;
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
  color: var(--color-btn-primary-text);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  z-index: var(--z-toast);
  text-decoration: none;
  transition: top var(--transition-fast);
}

.skip-link:focus {
  top: var(--space-2);
}

/* Responsive: 窄视口（开发者工具/小窗）——侧栏收窄为浮层，默认折叠态不遮挡 */
@media (max-width: 900px) {
  /* 侧栏改 fixed 浮层后脱离 flex 流，主区按折叠图标列宽度让位，
     否则 48px 图标列永久盖住内容左缘（窄视口穿模根因） */
  .workspace-main {
    margin-left: var(--sidebar-width-collapsed);
  }

  .workspace-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: var(--z-overlay);
    box-shadow: var(--shadow-lg);
  }

  .workspace-sidebar.collapsed {
    box-shadow: none;
  }
}
</style>
