<template>
  <div class="agent-view">
    <!-- 智能体广场（Tbox 社区风：渐变 CTA + 灰底搜索 + 白卡网格；工作台态同样展示，侧栏列表由 WorkspaceLayout 承载） -->
    <div class="plaza">
      <div class="plaza-header">
        <div class="plaza-heading">
          <h1 class="plaza-title">智能体广场</h1>
          <p class="plaza-subtitle">按你的指令自主调用工具、检索知识库，完成复杂任务</p>
        </div>
        <button class="plaza-cta" @click="openCreateDialog">
          <el-icon :size="14"><Plus /></el-icon>
          <span>创建智能体</span>
        </button>
      </div>

      <div class="plaza-toolbar">
        <div class="plaza-search">
          <el-icon :size="14" class="search-icon"><Search /></el-icon>
          <input
            v-model="searchKeyword"
            class="search-input"
            type="text"
            placeholder="搜索智能体名称或描述..."
          />
          <button v-if="searchKeyword" class="search-clear" @click="searchKeyword = ''">
            <el-icon :size="12"><Close /></el-icon>
          </button>
        </div>
      </div>

      <!-- 空状态：无任何智能体 -->
      <div v-if="agentStore.agents.length === 0 && !agentStore.agentsLoading" class="empty-state">
        <div class="empty-inner">
          <div class="empty-icon">
            <NavIcon name="agents" :size="36" />
          </div>
          <h2 class="empty-title">选择或创建一个智能体</h2>
          <p class="empty-desc">智能体可以根据你的指令自主调用工具、检索知识库，完成复杂任务</p>
          <button class="empty-action" @click="openCreateDialog">
            <el-icon :size="14"><Plus /></el-icon>
            创建第一个智能体
          </button>
        </div>
      </div>

      <!-- 搜索无结果 -->
      <div v-else-if="filteredAgents.length === 0" class="empty-state">
        <div class="empty-inner">
          <h2 class="empty-title">未找到匹配的智能体</h2>
          <p class="empty-desc">换个关键词试试，或清空搜索查看全部</p>
        </div>
      </div>

      <!-- Agent 卡片网格 -->
      <div v-else class="agent-grid">
        <div
          v-for="agent in filteredAgents"
          :key="agent.id"
          class="agent-card"
          @click="startChat(agent)"
        >
          <div class="card-cover" :class="`cover-hue-${agent.id % 4}`">
            <button class="card-delete" title="删除" @click.stop="handleDeleteAgent(agent)">
              <el-icon :size="12"><Delete /></el-icon>
            </button>
            <div class="card-avatar">{{ agent.name.charAt(0) }}</div>
          </div>
          <div class="card-body">
            <div class="card-name">{{ agent.name }}</div>
            <div class="card-desc">{{ agent.description || '暂无描述' }}</div>
            <div v-if="agent.enabled_tools?.length" class="card-tags">
              <span v-for="s in agent.enabled_tools.slice(0, 2)" :key="s" class="card-tag">{{
                toolLabel(s)
              }}</span>
              <span v-if="agent.enabled_tools.length > 2" class="card-tag card-tag--more">
                +{{ agent.enabled_tools.length - 2 }}
              </span>
            </div>
            <div class="card-actions">
              <button class="card-chat-btn" @click.stop="startChat(agent)">
                <el-icon :size="13"><ChatDotRound /></el-icon>
                <span>开始对话</span>
              </button>
              <button class="card-icon-btn" title="配置" @click.stop="openConfig(agent)">
                <el-icon :size="13"><Setting /></el-icon>
              </button>
              <button class="card-icon-btn" title="编辑" @click.stop="openEditDialog(agent)">
                <el-icon :size="13"><EditPen /></el-icon>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Agent 配置抽屉（详情八卡片自平铺主区收编） -->
    <el-drawer
      v-model="configDrawerVisible"
      :title="`${currentAgent?.name || '智能体'} · 配置`"
      direction="rtl"
      size="420px"
      :append-to-body="true"
    >
      <div class="config-drawer-body">
        <div class="config-card config-card--full">
          <div class="config-label">系统提示词</div>
          <div class="config-value system-prompt">{{ currentAgent?.system_prompt || '-' }}</div>
        </div>
        <div class="config-card">
          <div class="config-label">模型</div>
          <div class="config-value">{{ currentAgent?.llm_model || '默认' }}</div>
        </div>
        <div class="config-card">
          <div class="config-label">最大生成 Token</div>
          <div class="config-value">{{ currentAgent?.max_tokens ?? '-' }}</div>
        </div>
        <div class="config-card">
          <div class="config-label">上下文窗口</div>
          <div class="config-value">{{ currentAgent?.context_window ?? '-' }}</div>
        </div>
        <div class="config-card">
          <div class="config-label">Temperature</div>
          <div class="config-value">{{ currentAgent?.temperature ?? '-' }}</div>
        </div>
        <div class="config-card">
          <div class="config-label">Top P</div>
          <div class="config-value">{{ currentAgent?.top_p ?? '-' }}</div>
        </div>
        <div class="config-card config-card--full">
          <div class="config-label">工具</div>
          <div class="config-value">
            <template v-if="currentAgent?.enabled_tools?.length">
              <span v-for="s in currentAgent.enabled_tools" :key="s" class="tag">{{ s }}</span>
            </template>
            <template v-else>未启用</template>
          </div>
        </div>
        <div class="config-card config-card--full">
          <div class="config-label">MCP 服务器</div>
          <div class="config-value">
            <template v-if="currentAgent?.enabled_mcp_servers?.length">
              <span v-for="m in currentAgent.enabled_mcp_servers" :key="m" class="tag"
                >Server #{{ m }}</span
              >
            </template>
            <template v-else>未启用</template>
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 创建/编辑 Agent 弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEditing ? '编辑智能体' : '创建智能体'"
      width="600px"
      destroy-on-close
      append-to-body
    >
      <el-form :model="form" :rules="formRules" ref="formRef" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="为智能体起个名字" maxlength="50" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="2"
            placeholder="简要描述智能体的用途"
            maxlength="200"
          />
        </el-form-item>
        <el-form-item label="系统提示词" prop="system_prompt">
          <el-input
            v-model="form.system_prompt"
            type="textarea"
            :rows="5"
            placeholder="定义智能体的行为、角色和能力"
            maxlength="4000"
          />
        </el-form-item>
        <el-form-item label="LLM 模型">
          <el-select
            v-model="form.llm_model"
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
          <el-slider v-model="form.temperature" :min="0" :max="2" :step="0.1" show-input />
        </el-form-item>
        <el-form-item label="Top P">
          <el-slider v-model="form.top_p" :min="0" :max="1" :step="0.1" show-input />
        </el-form-item>
        <el-form-item label="最大生成 Token">
          <el-input-number v-model="form.max_tokens" :min="1" :max="32768" :step="256" />
        </el-form-item>
        <el-form-item label="上下文窗口">
          <el-input-number v-model="form.context_window" :min="2048" :max="1048576" :step="4096" />
        </el-form-item>
        <el-form-item label="最大工具调用">
          <el-input-number v-model="form.max_tool_calls_per_turn" :min="1" :max="50" />
        </el-form-item>
        <el-form-item label="启用工具">
          <el-select
            v-model="form.enabled_tools"
            multiple
            placeholder="选择要启用的工具"
            style="width: 100%"
          >
            <el-option
              v-for="tool in orderedTools"
              :key="tool.name"
              :label="toolDisplayName(tool.name)"
              :value="tool.name"
            >
              <span>{{ toolDisplayName(tool.name) }}</span>
              <span style="color: var(--color-text-muted); font-size: 12px; margin-left: 8px">{{
                tool.description
              }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="MCP 服务器">
          <el-select
            v-model="form.enabled_mcp_servers"
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
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>

    <!-- MCP 服务器创建/编辑弹窗 -->
    <el-dialog
      v-model="mcpDialogVisible"
      :title="isMcpEditing ? '编辑 MCP 服务器' : '添加 MCP 服务器'"
      width="560px"
      destroy-on-close
      append-to-body
    >
      <el-form :model="mcpForm" :rules="mcpFormRules" ref="mcpFormRef" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="mcpForm.name" placeholder="服务器名称" maxlength="50" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="mcpForm.description" placeholder="可选描述" maxlength="200" />
        </el-form-item>
        <el-form-item label="传输类型" prop="transport_type">
          <el-select v-model="mcpForm.transport_type" style="width: 100%">
            <el-option label="Streamable HTTP" value="streamable_http" />
            <el-option label="Stdio" value="stdio" />
          </el-select>
        </el-form-item>
        <el-form-item label="服务器地址" prop="url">
          <el-input v-model="mcpForm.url" placeholder="例如 http://localhost:3000/mcp" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="mcpForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mcpDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="mcpSubmitLoading" @click="handleMcpSubmit"
          >确定</el-button
        >
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus,
  Delete,
  EditPen,
  ChatDotRound,
  Setting,
  Search,
  Close,
} from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { useAgentStore } from '@/stores/agent'
import { chatApi } from '@/api/chat'
import NavIcon from '@/components/common/NavIcon.vue'
import type {
  Agent,
  CreateAgentRequest,
  UpdateAgentRequest,
  McpServer,
  CreateMcpServerRequest,
} from '@/api/types'

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()

// 配置抽屉展示目标
const selectedAgentId = ref<number | null>(null)
const currentAgent = computed(
  () => agentStore.agents.find((a) => a.id === selectedAgentId.value) || agentStore.currentAgent,
)

// ===================== 广场搜索 =====================
// 前端本地过滤（名称/描述），智能体量级小，无需后端分页
const searchKeyword = ref('')
const filteredAgents = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return agentStore.agents
  return agentStore.agents.filter(
    (a) =>
      a.name.toLowerCase().includes(kw) || (a.description || '').toLowerCase().includes(kw),
  )
})

// 卡片「配置」按钮：就地设置抽屉展示目标，避免误带出 store.currentAgent
function openConfig(agent: Agent) {
  selectedAgentId.value = agent.id
  agentStore.currentAgent = agent
  configDrawerVisible.value = true
}

// 工具展示：高频工具加 emoji 前缀并置顶，提升辨识度（value 仍用原始 name，保证后端匹配）
const PRIORITY_TOOLS = ['knowledge_search', 'web_search']
// 卡片标签用中文短词（蛇形 ID 直接裸露太工程味）
const TOOL_LABELS: Record<string, string> = {
  knowledge_search: '📚 知识库',
  web_search: '🌐 联网',
  memory: '🧠 记忆',
}
function toolLabel(name: string): string {
  return TOOL_LABELS[name] || name
}
function toolDisplayName(name: string): string {
  if (name === 'knowledge_search') return '📚 knowledge_search'
  if (name === 'web_search') return '🌐 web_search'
  return name
}
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

// 弹窗
const dialogVisible = ref(false)
// Agent 配置抽屉（详情八卡片收编）
const configDrawerVisible = ref(false)
const isEditing = ref(false)
const editingId = ref<number | null>(null)
const submitLoading = ref(false)
const formRef = ref<FormInstance>()

const form = reactive<
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

const formRules: FormRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  system_prompt: [{ required: true, message: '请输入系统提示词', trigger: 'blur' }],
}

function resetForm() {
  form.name = ''
  form.description = ''
  form.system_prompt = ''
  form.llm_model = ''
  form.temperature = 0.7
  form.top_p = 0.8
  form.max_tokens = 4096
  form.context_window = 32768
  form.max_tool_calls_per_turn = 10
  form.enabled_tools = []
  form.enabled_mcp_servers = []
}

function openCreateDialog() {
  isEditing.value = false
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

function openEditDialog(agent: Agent) {
  isEditing.value = true
  editingId.value = agent.id
  form.name = agent.name
  form.description = agent.description || ''
  form.system_prompt = agent.system_prompt ?? ''
  form.llm_model = agent.llm_model || ''
  form.temperature = agent.temperature
  form.top_p = agent.top_p
  form.max_tokens = agent.max_tokens
  form.context_window = agent.context_window || 32768
  form.max_tool_calls_per_turn = agent.max_tool_calls_per_turn
  form.enabled_tools = agent.enabled_tools || []
  form.enabled_mcp_servers = agent.enabled_mcp_servers || []
  dialogVisible.value = true
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitLoading.value = true
  try {
    const data: CreateAgentRequest | UpdateAgentRequest = {
      name: form.name,
      description: form.description || undefined,
      system_prompt: form.system_prompt,
      llm_model: form.llm_model || undefined,
      temperature: form.temperature,
      top_p: form.top_p,
      max_tokens: form.max_tokens,
      context_window: form.context_window,
      max_tool_calls_per_turn: form.max_tool_calls_per_turn,
      enabled_tools: form.enabled_tools?.length ? form.enabled_tools : undefined,
      enabled_mcp_servers: form.enabled_mcp_servers?.length ? form.enabled_mcp_servers : undefined,
    }

    if (isEditing.value && editingId.value) {
      await agentStore.updateAgent(editingId.value, data)
      ElMessage.success('智能体已更新')
    } else {
      await agentStore.createAgent(data as CreateAgentRequest)
      ElMessage.success('智能体已创建')
    }
    dialogVisible.value = false
  } catch {
    // Error already shown
  } finally {
    submitLoading.value = false
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
    if (selectedAgentId.value === agent.id) {
      selectedAgentId.value = null
    }
    ElMessage.success('智能体已删除')
  } catch {
    // cancelled
  }
}

function startChat(agent: Agent) {
  // /home/agents 等旧路径已重定向到工作台，统一走工作台对话路由
  router.push({ name: 'WorkspaceAgentChat', params: { agentId: agent.id } })
}

// ===================== MCP 服务器管理 =====================

const mcpDialogVisible = ref(false)
const isMcpEditing = ref(false)
const editingMcpId = ref<number | null>(null)
const mcpSubmitLoading = ref(false)
const mcpFormRef = ref<FormInstance>()

const mcpForm = reactive({
  name: '',
  description: '',
  transport_type: 'streamable_http' as 'stdio' | 'streamable_http',
  url: '',
  enabled: true,
})

const mcpFormRules: FormRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  transport_type: [{ required: true, message: '请选择传输类型', trigger: 'change' }],
  url: [{ required: true, message: '请输入服务器地址', trigger: 'blur' }],
}

function resetMcpForm() {
  mcpForm.name = ''
  mcpForm.description = ''
  mcpForm.transport_type = 'streamable_http'
  mcpForm.url = ''
  mcpForm.enabled = true
}

function openMcpCreateDialog() {
  isMcpEditing.value = false
  editingMcpId.value = null
  resetMcpForm()
  mcpDialogVisible.value = true
}

function openMcpEditDialog(server: McpServer) {
  isMcpEditing.value = true
  editingMcpId.value = server.id
  mcpForm.name = server.name
  mcpForm.description = server.description || ''
  mcpForm.transport_type = server.transport_type
  const config = server.connection_config as { url?: string }
  mcpForm.url = config?.url || ''
  mcpForm.enabled = server.enabled
  mcpDialogVisible.value = true
}

async function handleMcpSubmit() {
  const valid = await mcpFormRef.value?.validate().catch(() => false)
  if (!valid) return

  mcpSubmitLoading.value = true
  try {
    const connectionConfig: Record<string, unknown> =
      mcpForm.transport_type === 'streamable_http' ? { url: mcpForm.url } : { command: mcpForm.url }

    const data: CreateMcpServerRequest = {
      name: mcpForm.name,
      description: mcpForm.description || undefined,
      transport_type: mcpForm.transport_type,
      connection_config: connectionConfig,
      enabled: mcpForm.enabled,
    }

    if (isMcpEditing.value && editingMcpId.value) {
      await agentStore.updateMcpServer(editingMcpId.value, data)
      ElMessage.success('服务器已更新')
    } else {
      await agentStore.createMcpServer(data)
      ElMessage.success('服务器已添加')
    }
    mcpDialogVisible.value = false
  } catch {
    // Error already shown
  } finally {
    mcpSubmitLoading.value = false
  }
}

async function handleConnectServer(serverId: number) {
  try {
    await agentStore.connectMcpServer(serverId)
    ElMessage.success('连接成功')
  } catch {
    // Error already shown
  }
}

async function handleDisconnectServer(serverId: number) {
  try {
    await agentStore.disconnectMcpServer(serverId)
    ElMessage.success('已断开连接')
  } catch {
    // Error already shown
  }
}

async function handleRefreshTools(serverId: number) {
  try {
    const res = await agentStore.refreshMcpTools(serverId)
    ElMessage.success(`已刷新，发现 ${res.tools?.length || 0} 个工具`)
    await agentStore.fetchMcpServers()
  } catch {
    // Error already shown
  }
}

async function handleDeleteServer(server: McpServer) {
  try {
    await ElMessageBox.confirm(`确定删除 MCP 服务器 "${server.name}" 吗？`, '删除', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await agentStore.deleteMcpServer(server.id)
    ElMessage.success('服务器已删除')
  } catch {
    // cancelled
  }
}

function mcpStatusLabel(status: string): string {
  const map: Record<string, string> = {
    disconnected: '未连接',
    connecting: '连接中',
    connected: '已连接',
    error: '错误',
  }
  return map[status] || status
}

// 工作台侧栏"创建智能体"按钮通过 query 触发
watch(
  () => route.query.action,
  (action) => {
    if (action === 'create') {
      openCreateDialog()
      router.replace({ query: {} })
    }
  },
)

onMounted(async () => {
  await Promise.all([
    agentStore.fetchAgents(),
    agentStore.fetchTools(),
    agentStore.fetchMcpServers(),
    fetchModels(),
  ])
})
</script>

<style scoped>
/* ========================================
   Plaza — 智能体广场（Tbox 社区风：白卡大圆角 + 渐变 CTA + 灰底搜索）
   ======================================== */
.agent-view {
  position: absolute;
  inset: 0;
  display: flex;
  background: var(--color-bg);
  overflow: hidden;
}

.plaza {
  flex: 1;
  width: 100%;
  max-width: 1120px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-6) var(--space-10);
  overflow-y: auto;
}

.plaza-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-5);
}

.plaza-heading {
  min-width: 0;
}

/* 米哈游式左对齐排版层级：大标题 + 灰字副题 */
.plaza-title {
  font-family: var(--font-display);
  font-size: var(--text-3xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  letter-spacing: var(--tracking-tight);
  margin: 0 0 var(--space-2);
}

.plaza-subtitle {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  line-height: var(--leading-normal);
}

/* 渐变主 CTA（Tbox 点睛：紫蓝→紫胶囊，hover 提亮上浮） */
.plaza-cta {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5);
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-gradient-accent);
  color: var(--color-gradient-contrast);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition: all var(--transition-base);
  flex-shrink: 0;
  box-shadow: 0 4px 14px rgba(90, 80, 255, 0.25);
}

.plaza-cta:hover {
  background: var(--color-gradient-accent-hover);
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(90, 80, 255, 0.32);
}

/* ========================================
   Toolbar — 灰底无边框搜索框（Tbox search-input 语言）
   ======================================== */
.plaza-toolbar {
  margin-bottom: var(--space-6);
}

.plaza-search {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 40px;
  max-width: 440px;
  padding: 0 var(--space-4);
  border: 1px solid transparent;
  border-radius: var(--radius-lg);
  background: var(--color-bg-input);
  transition: all var(--transition-base);
}

.plaza-search:focus-within {
  background: var(--color-bg-card);
  border-color: var(--color-border);
  box-shadow: var(--shadow-sm);
}

.search-icon {
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  height: 100%;
  border: none;
  outline: none;
  background: transparent;
  font-family: var(--font-body);
  font-size: var(--text-sm);
  color: var(--color-text);
}

.search-input::placeholder {
  color: var(--color-text-faint);
}

.search-clear {
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

.search-clear:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

/* ========================================
   Agent Grid — 白卡网格（Tbox card：15px 圆角 + 极浅边框 + hover 上浮）
   ======================================== */
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--space-4);
}

/* 卡片：顶部渐变色盖 + 白底内容区（Tbox card + cover 语言） */
.agent-card {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--color-border-light);
  border-radius: 16px;
  background: var(--color-bg-card);
  overflow: hidden;
  cursor: pointer;
  transition: all var(--transition-base);
}

.agent-card:hover {
  transform: translateY(-3px);
  border-color: var(--color-border);
  box-shadow: var(--shadow-lg);
}

/* 色盖：低饱和透明渐变叠在卡底色上，亮暗两主题通用；按 agent.id 轮换 4 色相 */
.card-cover {
  position: relative;
  height: 64px;
  flex-shrink: 0;
}

.cover-hue-0 {
  background: linear-gradient(120deg, rgba(99, 101, 255, 0.18), rgba(188, 87, 255, 0.1));
}

.cover-hue-1 {
  background: linear-gradient(120deg, rgba(59, 130, 246, 0.16), rgba(99, 101, 255, 0.08));
}

.cover-hue-2 {
  background: linear-gradient(120deg, rgba(236, 72, 153, 0.14), rgba(188, 87, 255, 0.08));
}

.cover-hue-3 {
  background: linear-gradient(120deg, rgba(20, 184, 166, 0.14), rgba(59, 130, 246, 0.08));
}

/* 头像：白底圆角方压在色盖下缘（悬浮锚点） */
.card-avatar {
  position: absolute;
  left: var(--space-4);
  bottom: -23px;
  width: 46px;
  height: 46px;
  border-radius: 14px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: var(--weight-bold);
  color: var(--color-text);
  box-shadow: var(--shadow-sm);
  user-select: none;
}

.card-delete {
  position: absolute;
  top: var(--space-2);
  right: var(--space-2);
  opacity: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-xs);
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.agent-card:hover .card-delete {
  opacity: 1;
}

.card-delete:hover {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

.card-body {
  display: flex;
  flex-direction: column;
  flex: 1;
  padding: 31px var(--space-4) var(--space-4);
}

.card-name {
  font-size: 15px;
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  margin-bottom: var(--space-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-desc {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  line-height: var(--leading-normal);
  margin-bottom: var(--space-3);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: calc(var(--leading-normal) * var(--text-sm) * 2);
  flex: 1;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: var(--space-3);
}

.card-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  font-size: 11px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-tag--more {
  color: var(--color-text-muted);
}

.card-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* 开始对话：默认灰底，卡片 hover 时点亮渐变（Tbox mask-reveal 语言） */
.card-chat-btn {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  border: none;
  border-radius: var(--radius-lg);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  font-family: var(--font-body);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition: all var(--transition-base);
}

.agent-card:hover .card-chat-btn {
  background: var(--color-gradient-accent);
  color: var(--color-gradient-contrast);
}

.card-chat-btn:hover {
  background: var(--color-gradient-accent-hover) !important;
}

/* 配置/编辑：ghost 方钮 */
.card-icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border: none;
  border-radius: var(--radius-lg);
  background: var(--color-bg-hover);
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.card-icon-btn:hover {
  background: var(--color-bg-card-elevated);
  color: var(--color-text);
  box-shadow: var(--shadow-xs);
}

/* ========================================
   Empty State
   ======================================== */
.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-16, 64px) var(--space-8);
}

.empty-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  max-width: 420px;
}

.empty-icon {
  width: 72px;
  height: 72px;
  border-radius: var(--radius-xl);
  background: var(--color-primary-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-6);
  box-shadow: var(--shadow-md);
}

.empty-title {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin-bottom: var(--space-3);
}

.empty-desc {
  font-size: var(--text-base);
  color: var(--color-text-muted);
  text-align: center;
  margin-bottom: var(--space-6);
  line-height: var(--leading-relaxed);
}

.empty-action {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-base);
}

.empty-action:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-muted);
}

/* ========================================
   Config Drawer（配置抽屉；drawer append-to-body，样式非 scoped）
   ======================================== */
</style>

<style>
/* Agent 配置抽屉内容（append-to-body 需全局） */
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

.config-drawer-body .config-card--full {
  /* 单列布局下与普通卡片同宽，保留类名仅为语义 */
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
