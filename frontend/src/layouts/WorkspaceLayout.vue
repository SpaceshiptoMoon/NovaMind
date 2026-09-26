<template>
  <div class="workspace-layout">
    <a href="#workspace-main" class="skip-link">跳到主内容</a>

    <!-- 顶栏：全宽置顶（全局导航 + 全局项；频道分段在侧栏，折叠切换经 prop 传入） -->
    <AppHeader
      :sidebar-collapsed="isWorkspaceRoute ? sidebarCollapsed : undefined"
      @toggle-sidebar="sidebarCollapsed = !sidebarCollapsed"
    />

    <!-- 下方：侧栏（频道分段 + 上下文列表，可折叠；仅工作台路由） + 主内容 -->
    <div class="workspace-body">
      <aside
        v-if="isWorkspaceRoute"
        class="workspace-sidebar"
        :class="{ collapsed: sidebarCollapsed }"
        role="navigation"
        aria-label="工作台侧边栏"
      >
        <!-- 频道分段（侧栏顶部，展开态显示） -->
        <nav
          v-if="!sidebarCollapsed"
          class="channel-segments"
          role="tablist"
          aria-label="工作台频道"
        >
          <button
            v-for="ch in channels"
            :key="ch.key"
            class="channel-seg"
            :class="{ active: activeChannelKey === ch.key }"
            role="tab"
            :aria-selected="activeChannelKey === ch.key"
            :title="ch.label"
            @click="activateChannel(ch.key)"
          >
            <NavIcon :name="ch.icon" :size="15" />
            <span class="channel-seg-label">{{ ch.label }}</span>
          </button>
        </nav>

        <!-- 展开模式：上下文列表 -->
        <template v-if="!sidebarCollapsed">
          <!-- Chat: session list（可折叠） -->
          <div class="sidebar-body">
            <template v-if="activeChannelKey === 'chat'">
              <div class="list-section">
                <button class="list-section-header" @click="toggleSection('chat')">
                  <span class="list-section-title">最近对话</span>
                  <span class="list-section-count">{{ chatStore.sessions.length }}</span>
                  <el-icon
                    :size="12"
                    class="list-section-chevron"
                    :class="{ collapsed: sectionCollapsed.chat }"
                  >
                    <ArrowDown />
                  </el-icon>
                </button>
                <button class="section-new-btn" @click="handleNewChatSession">
                  <el-icon :size="14"><Plus /></el-icon>
                  <span>新对话</span>
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
                    <button
                      class="item-delete"
                      @click.stop="handleDeleteChatSession(session.session_id)"
                    >
                      <el-icon :size="12"><Delete /></el-icon>
                    </button>
                  </div>
                  <div v-if="chatStore.sessions.length === 0" class="list-empty">暂无对话记录</div>
                </div>
              </div>
            </template>

            <!-- Agents: agent list（可折叠；点条目进对话，hover 出配置/编辑/删除动作） -->
            <template v-else-if="isWorkspaceRoute && activeChannelKey === 'agents'">
              <div class="list-section">
                <button class="list-section-header" @click="toggleSection('agents')">
                  <span class="list-section-title">我的智能体</span>
                  <span class="list-section-count">{{ agentStore.agents.length }}</span>
                  <el-icon
                    :size="12"
                    class="list-section-chevron"
                    :class="{ collapsed: sectionCollapsed.agents }"
                  >
                    <ArrowDown />
                  </el-icon>
                </button>
                <button class="section-new-btn" @click="openAgentDialog()">
                  <el-icon :size="14"><Plus /></el-icon>
                  <span>创建智能体</span>
                </button>
                <div v-show="!sectionCollapsed.agents" class="list-area">
                  <div
                    v-for="agent in agentStore.agents"
                    :key="agent.id"
                    class="list-item"
                    :class="{ active: isAgentChatRoute(agent.id) }"
                    @click="handleSelectAgent(agent)"
                  >
                    <div class="agent-avatar-sm">{{ agent.name.charAt(0) }}</div>
                    <div class="item-info">
                      <span class="item-title">{{ agent.name }}</span>
                      <span class="item-desc">{{ agent.description || '暂无描述' }}</span>
                    </div>
                    <div class="item-actions">
                      <button
                        class="item-action-btn"
                        title="配置"
                        @click.stop="openAgentConfig(agent)"
                      >
                        <el-icon :size="12"><Setting /></el-icon>
                      </button>
                      <button
                        class="item-action-btn"
                        title="编辑"
                        @click.stop="openAgentDialog(agent)"
                      >
                        <el-icon :size="12"><EditPen /></el-icon>
                      </button>
                      <button
                        class="item-action-btn item-action-btn--danger"
                        title="删除"
                        @click.stop="handleDeleteAgent(agent)"
                      >
                        <el-icon :size="12"><Delete /></el-icon>
                      </button>
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
                  <el-icon
                    :size="12"
                    class="list-section-chevron"
                    :class="{ collapsed: sectionCollapsed.research }"
                  >
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
          </div>
        </template>

        <!-- 折叠模式：频道 icon 列表 -->
        <template v-else>
          <div class="channel-icons">
            <button
              v-for="ch in channels"
              :key="ch.key"
              class="channel-icon-btn"
              :class="{ active: activeChannelKey === ch.key }"
              :title="ch.label"
              @click="activateChannel(ch.key)"
            >
              <NavIcon :name="ch.icon" :size="20" />
            </button>
          </div>
        </template>
      </aside>

      <!-- Agent 创建/编辑弹窗 + 配置抽屉（广场页已删，管理动作收编侧栏；append-to-body 需挂布局层） -->
      <el-dialog
        v-model="agentDialogVisible"
        :title="agentEditingId ? '编辑智能体' : '创建智能体'"
        width="600px"
        destroy-on-close
        append-to-body
      >
        <el-form :model="agentForm" :rules="agentFormRules" ref="agentFormRef" label-width="100px">
          <el-form-item label="名称" prop="name">
            <el-input v-model="agentForm.name" placeholder="为智能体起个名字" maxlength="50" />
          </el-form-item>
          <el-form-item label="描述" prop="description">
            <el-input
              v-model="agentForm.description"
              type="textarea"
              :rows="2"
              placeholder="简要描述智能体的用途"
              maxlength="200"
            />
          </el-form-item>
          <el-form-item label="系统提示词" prop="system_prompt">
            <el-input
              v-model="agentForm.system_prompt"
              type="textarea"
              :rows="5"
              placeholder="定义智能体的行为、角色和能力"
              maxlength="4000"
            />
          </el-form-item>
          <el-form-item label="LLM 模型">
            <el-select
              v-model="agentForm.llm_model"
              placeholder="留空使用默认模型"
              clearable
              style="width: 100%"
            >
              <el-option-group v-if="llmModelNames.length" label="LLM 文本模型">
                <el-option v-for="name in llmModelNames" :key="name" :label="name" :value="name" />
              </el-option-group>
              <el-option-group v-if="vlmModelNames.length" label="VLM 视觉模型">
                <el-option v-for="name in vlmModelNames" :key="name" :label="name" :value="name" />
              </el-option-group>
            </el-select>
          </el-form-item>
          <el-form-item label="Temperature">
            <el-slider v-model="agentForm.temperature" :min="0" :max="2" :step="0.1" show-input />
          </el-form-item>
          <el-form-item label="Top P">
            <el-slider v-model="agentForm.top_p" :min="0" :max="1" :step="0.1" show-input />
          </el-form-item>
          <el-form-item label="最大生成 Token">
            <el-input-number v-model="agentForm.max_tokens" :min="1" :max="32768" :step="256" />
          </el-form-item>
          <el-form-item label="上下文窗口">
            <el-input-number
              v-model="agentForm.context_window"
              :min="2048"
              :max="1048576"
              :step="4096"
            />
          </el-form-item>
          <el-form-item label="最大工具调用">
            <el-input-number v-model="agentForm.max_tool_calls_per_turn" :min="1" :max="50" />
          </el-form-item>
          <el-form-item label="启用工具">
            <el-select
              v-model="agentForm.enabled_tools"
              multiple
              placeholder="选择要启用的工具"
              style="width: 100%"
            >
              <el-option
                v-for="tool in orderedTools"
                :key="tool.name"
                :label="tool.name"
                :value="tool.name"
              >
                <span>{{ tool.name }}</span>
                <span style="color: var(--color-text-muted); font-size: 12px; margin-left: 8px">{{
                  tool.description
                }}</span>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="MCP 服务器">
            <el-select
              v-model="agentForm.enabled_mcp_servers"
              multiple
              placeholder="选择要启用的 MCP 服务器"
              style="width: 100%"
            >
              <el-option
                v-for="server in agentStore.mcpServers"
                :key="server.id"
                :label="server.name"
                :value="server.id"
              >
                <span>{{ server.name }}</span>
                <span style="color: var(--color-text-muted); font-size: 12px; margin-left: 8px">{{
                  server.status
                }}</span>
              </el-option>
            </el-select>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="agentDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="agentSubmitLoading" @click="handleAgentSubmit"
            >确定</el-button
          >
        </template>
      </el-dialog>

      <el-drawer
        v-model="configDrawerVisible"
        :title="`${configAgent?.name || '智能体'} · 配置`"
        direction="rtl"
        size="420px"
        :append-to-body="true"
      >
        <div class="config-drawer-body">
          <div class="config-card config-card--full">
            <div class="config-label">系统提示词</div>
            <div class="config-value system-prompt">{{ configAgent?.system_prompt || '-' }}</div>
          </div>
          <div class="config-card">
            <div class="config-label">模型</div>
            <div class="config-value">{{ configAgent?.llm_model || '默认' }}</div>
          </div>
          <div class="config-card">
            <div class="config-label">最大生成 Token</div>
            <div class="config-value">{{ configAgent?.max_tokens ?? '-' }}</div>
          </div>
          <div class="config-card">
            <div class="config-label">上下文窗口</div>
            <div class="config-value">{{ configAgent?.context_window ?? '-' }}</div>
          </div>
          <div class="config-card">
            <div class="config-label">Temperature</div>
            <div class="config-value">{{ configAgent?.temperature ?? '-' }}</div>
          </div>
          <div class="config-card">
            <div class="config-label">Top P</div>
            <div class="config-value">{{ configAgent?.top_p ?? '-' }}</div>
          </div>
          <div class="config-card config-card--full">
            <div class="config-label">工具</div>
            <div class="config-value">
              <template v-if="configAgent?.enabled_tools?.length">
                <span v-for="s in configAgent.enabled_tools" :key="s" class="tag">{{ s }}</span>
              </template>
              <template v-else>未启用</template>
            </div>
          </div>
          <div class="config-card config-card--full">
            <div class="config-label">MCP 服务器</div>
            <div class="config-value">
              <template v-if="configAgent?.enabled_mcp_servers?.length">
                <span v-for="m in configAgent.enabled_mcp_servers" :key="m" class="tag"
                  >Server #{{ m }}</span
                >
              </template>
              <template v-else>未启用</template>
            </div>
          </div>
        </div>
      </el-drawer>

      <main class="workspace-main" id="workspace-main" role="main">
        <div class="workspace-content" :class="{ 'is-page': !isWorkspaceRoute }">
          <router-view v-slot="{ Component }">
            <transition name="fade" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </div>
        <!-- 右抽屉：引用来源 / 工具结果（仅工作台路由）。折叠态 width:0 不占位 -->
        <WorkbenchDrawer
          v-if="isWorkspaceRoute"
          :sources="drawerSources"
          :tool-calls="drawerToolCalls"
        />
        <!-- 抽屉展开按钮（抽屉关闭时浮在主区右上角） -->
        <button
          v-if="isWorkspaceRoute && !workbench.drawerOpen"
          class="drawer-toggle"
          title="打开引用面板"
          @click="workbench.openDrawer('overview')"
        >
          <el-icon :size="14"><Expand /></el-icon>
        </button>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, provide, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Expand, ArrowDown, Plus, Setting, EditPen } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { useAgentStore } from '@/stores/agent'
import { useSpaceStore } from '@/stores/space'
import { useChatStore } from '@/stores/chat'
import { useWorkbenchStore } from '@/stores/workbench'
import { usePermissionStore } from '@/stores/permission'
import { chatApi } from '@/api/chat'
import NavIcon from '@/components/common/NavIcon.vue'
import AppHeader from './AppHeader.vue'
import WorkbenchDrawer from '@/components/workbench/WorkbenchDrawer.vue'
import type {
  Agent,
  ChatSource,
  SourceRef,
  ToolCallRecord,
  CreateAgentRequest,
  UpdateAgentRequest,
} from '@/api/types'

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const spaceStore = useSpaceStore()
const chatStore = useChatStore()
const workbench = useWorkbenchStore()

provide('isInWorkspace', true)

const sidebarCollapsed = ref(false)

const permStore = usePermissionStore()

const isWorkspaceRoute = computed(() => route.path.startsWith('/home/workspace'))

// 频道清单：app 键对应应用门禁代码（AppCode）；research 属空间功能不进门禁（常驻）
const allChannels = [
  { key: 'chat', label: 'AI 对话', icon: 'chat', group: 'primary', app: 'qa' },
  { key: 'agents', label: '智能体', icon: 'agents', group: 'primary', app: 'agent' },
  { key: 'research', label: '深度研究', icon: 'research', group: 'more', app: null },
  { key: 'skills', label: '技能广场', icon: 'skill', group: 'more', app: 'skill' },
] as const

// 应用级权限过滤（admin 短路全过；被禁应用的频道不渲染）
const channels = computed(() =>
  allChannels.filter((c) => c.app === null || permStore.hasApp(c.app)),
)

const activeChannelKey = ref('chat')

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
}

// 按频道执行「新建/开启」动作。chat=开启新对话；agents=进入智能体页（添加入口在页面内）；其余=跳转
function handleNew(key: string = activeChannelKey.value) {
  switch (key) {
    case 'chat':
      startNewChatSession()
      break
    case 'agents':
      router.push('/home/workspace/agents')
      break
    case 'research':
      router.push('/home/workspace/research')
      break
    case 'skills':
      router.push('/home/workspace/skills')
      break
  }
}

// ===================== Chat =====================

// 开新对话：流式中先取消 SSE（否则回调会写入新会话的消息造成污染），再清空当前上下文
function startNewChatSession() {
  if (chatStore.isStreaming) chatStore.cancelStream()
  chatStore.clearMessages()
  router.push('/home/workspace/chat')
}

// 侧栏「新对话」按钮（+）：与点 chat 频道 tab 同一动作
function handleNewChatSession() {
  startNewChatSession()
}

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

// 当前路由是否正处某 agent 的对话页（侧栏列表 active 态）
function isAgentChatRoute(agentId: number): boolean {
  return route.name === 'WorkspaceAgentChat' && Number(route.params.agentId) === agentId
}

// 占位页经 inject 调用创建弹窗（广场页已删，创建入口收编在布局层）
provide('openAgentDialog', openAgentDialog)

// 点 agent 条目：直接进对话页（广场页已删，对话即详情）
function handleSelectAgent(agent: Agent) {
  agentStore.currentAgent = agent
  agentStore.fetchConversations(agent.id)
  router.push({ name: 'WorkspaceAgentChat', params: { agentId: agent.id } })
}

// ===================== Agent 创建/编辑弹窗（原广场页逻辑收编） =====================

const agentDialogVisible = ref(false)
const agentEditingId = ref<number | null>(null)
const agentSubmitLoading = ref(false)
const agentFormRef = ref<FormInstance>()

const agentForm = reactive<
  CreateAgentRequest & {
    temperature: number
    top_p: number
    max_tokens: number
    max_tool_calls_per_turn: number
  }
>({
  name: '',
  description: '',
  system_prompt: '',
  llm_model: '',
  temperature: 0.7,
  top_p: 0.8,
  max_tokens: 4096,
  context_window: 32768,
  max_tool_calls_per_turn: 10,
  enabled_tools: [],
  enabled_mcp_servers: [],
})

const agentFormRules: FormRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  system_prompt: [{ required: true, message: '请输入系统提示词', trigger: 'blur' }],
}

function resetAgentForm() {
  agentForm.name = ''
  agentForm.description = ''
  agentForm.system_prompt = ''
  agentForm.llm_model = ''
  agentForm.temperature = 0.7
  agentForm.top_p = 0.8
  agentForm.max_tokens = 4096
  agentForm.context_window = 32768
  agentForm.max_tool_calls_per_turn = 10
  agentForm.enabled_tools = []
  agentForm.enabled_mcp_servers = []
}

// 不传 agent = 创建；传 = 编辑（name 保留历史语义）
function openAgentDialog(agent?: Agent) {
  if (agent) {
    agentEditingId.value = agent.id
    agentForm.name = agent.name
    agentForm.description = agent.description || ''
    agentForm.system_prompt = agent.system_prompt ?? ''
    agentForm.llm_model = agent.llm_model || ''
    agentForm.temperature = agent.temperature
    agentForm.top_p = agent.top_p
    agentForm.max_tokens = agent.max_tokens
    agentForm.context_window = agent.context_window || 32768
    agentForm.max_tool_calls_per_turn = agent.max_tool_calls_per_turn
    agentForm.enabled_tools = agent.enabled_tools || []
    agentForm.enabled_mcp_servers = agent.enabled_mcp_servers || []
  } else {
    agentEditingId.value = null
    resetAgentForm()
  }
  agentDialogVisible.value = true
}

async function handleAgentSubmit() {
  const valid = await agentFormRef.value?.validate().catch(() => false)
  if (!valid) return

  agentSubmitLoading.value = true
  try {
    const data: CreateAgentRequest | UpdateAgentRequest = {
      name: agentForm.name,
      description: agentForm.description || undefined,
      system_prompt: agentForm.system_prompt,
      llm_model: agentForm.llm_model || undefined,
      temperature: agentForm.temperature,
      top_p: agentForm.top_p,
      max_tokens: agentForm.max_tokens,
      context_window: agentForm.context_window,
      max_tool_calls_per_turn: agentForm.max_tool_calls_per_turn,
      enabled_tools: agentForm.enabled_tools?.length ? agentForm.enabled_tools : undefined,
      enabled_mcp_servers: agentForm.enabled_mcp_servers?.length
        ? agentForm.enabled_mcp_servers
        : undefined,
    }

    if (agentEditingId.value) {
      await agentStore.updateAgent(agentEditingId.value, data)
      ElMessage.success('智能体已更新')
    } else {
      await agentStore.createAgent(data as CreateAgentRequest)
      ElMessage.success('智能体已创建')
    }
    agentDialogVisible.value = false
  } catch {
    // Error already shown
  } finally {
    agentSubmitLoading.value = false
  }
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

// ===================== 模型可选项（创建/编辑弹窗用） =====================

const availableModels = ref<
  Record<string, { max_tokens: number; temperature: number; top_p: number; model_type: string }>
>({})

const llmModelNames = computed(() =>
  Object.entries(availableModels.value)
    .filter(([, v]) => v.model_type !== 'vlm')
    .map(([name]) => name),
)
const vlmModelNames = computed(() =>
  Object.entries(availableModels.value)
    .filter(([, v]) => v.model_type === 'vlm')
    .map(([name]) => name),
)

async function fetchModels() {
  try {
    const data = await chatApi.getModels()
    availableModels.value = data.models
  } catch {
    // ignore
  }
}

// 工具下拉：知识库/联网搜索置顶（原 AgentView PRIORITY_TOOLS 逻辑）
const PRIORITY_TOOLS = ['knowledge_search', 'web_search']
const orderedTools = computed(() => {
  return [...agentStore.tools].sort((a, b) => {
    const ai = PRIORITY_TOOLS.indexOf(a.name)
    const bi = PRIORITY_TOOLS.indexOf(b.name)
    if (ai === -1 && bi === -1) return 0
    if (ai === -1) return 1
    if (bi === -1) return -1
    return ai - bi
  })
})

// ===================== Research =====================

function handleSelectResearchSpace(spaceId: number) {
  router.push(`/home/workspace/research/${spaceId}`)
}

// ===================== Init =====================

onMounted(async () => {
  syncChannelFromRoute()
  // 窄视口（开发者工具/小窗）默认折叠侧栏，避免遮挡内容
  if (window.innerWidth < 900) sidebarCollapsed.value = true
  await Promise.all([
    agentStore.fetchAgents(),
    agentStore.fetchTools(),
    agentStore.fetchMcpServers(),
    fetchModels(),
    spaceStore.spaces.length === 0 ? spaceStore.fetchSpaces() : Promise.resolve(),
    chatStore.fetchSessions(),
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
}

/* ========================================
   Sidebar — 顶栏下方首列（频道分段 + 上下文列表）
   ======================================== */
.workspace-sidebar {
  width: var(--sidebar-width);
  flex-shrink: 0;
  height: 100%;
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

/* ========================================
   Channel Segments — 侧栏纵排胶囊分段
   ======================================== */
.channel-segments {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2);
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.channel-seg {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 7px var(--space-3);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  font-family: var(--font-body);
  cursor: pointer;
  width: 100%;
  text-align: left;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.channel-seg:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

/* 选中态：实底主色 + 白字（与 ChatInput mode-chip.active 同款选中语言，
   未选中仅 hover 浅灰底，选中/未选中一眼可分） */
.channel-seg.active {
  background: var(--color-btn-primary);
  color: #ffffff;
  font-weight: var(--weight-medium, 500);
  box-shadow: var(--shadow-sm);
}

.channel-seg.active :deep(svg) {
  color: #ffffff;
}

.channel-seg-label {
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

/* 侧栏分区常驻新建按钮（如「创建智能体」）：虚线框，hover 主色 */
.section-new-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1, 4px);
  margin: 2px var(--space-3) 6px;
  padding: 6px 10px;
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-muted);
  font-family: var(--font-body);
  font-size: var(--text-xs);
  cursor: pointer;
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

.section-new-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-muted);
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
  background: var(--color-btn-primary);
  color: #ffffff;
  box-shadow: var(--shadow-sm);
}

/* Sidebar body */
.sidebar-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  padding-top: var(--space-2); /* 频道 tabs 与上下文列表的分区呼吸感 */
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
  color: #ffffff;
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
  .workspace-layout {
    /* 触发全局 sidebarCollapsed 初始值无法用 CSS——改为窄视口下侧栏变浮层 */
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

<style>
/* Agent 配置抽屉内容（append-to-body 需全局；自原 AgentView 平移） */
.config-drawer-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.config-drawer-body .config-card {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
}

.config-drawer-body .config-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: var(--space-2);
}

.config-drawer-body .config-value {
  font-size: var(--text-sm);
  color: var(--color-text);
  line-height: var(--leading-relaxed);
  word-break: break-word;
}

.config-drawer-body .system-prompt {
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
}

.config-drawer-body .tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  background: var(--color-primary-muted);
  color: var(--color-primary);
  font-size: var(--text-xs);
  margin-right: var(--space-1);
  margin-bottom: var(--space-1);
}
</style>
