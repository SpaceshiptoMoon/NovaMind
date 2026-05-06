<template>
  <div class="agent-view">
    <!-- 左侧边栏：Agent 列表（仅在非工作台模式显示） -->
    <div v-if="!isChatRoute && !isInWorkspace" class="agent-sidebar">
      <div class="sidebar-top">
        <button class="create-agent-btn" @click="openCreateDialog">
          <el-icon :size="16"><Plus /></el-icon>
          <span>创建智能体</span>
        </button>
      </div>
      <div class="agent-list">
        <div
          v-for="agent in agentStore.agents"
          :key="agent.id"
          class="agent-item"
          :class="{ active: selectedAgentId === agent.id }"
          @click="handleSelectAgent(agent)"
        >
          <div class="agent-avatar">{{ agent.name.charAt(0) }}</div>
          <div class="agent-info">
            <div class="agent-name">{{ agent.name }}</div>
            <div class="agent-desc">{{ agent.description || '暂无描述' }}</div>
          </div>
          <button class="agent-delete" @click.stop="handleDeleteAgent(agent)">
            <el-icon :size="12"><Delete /></el-icon>
          </button>
        </div>
        <div v-if="agentStore.agents.length === 0 && !agentStore.agentsLoading" class="sidebar-empty">
          <span>暂无智能体</span>
        </div>
      </div>
    </div>

    <!-- 右侧主区域 -->
    <div class="agent-main">
      <!-- 空状态 -->
      <div v-if="!currentAgent" class="empty-state">
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

      <!-- Agent 详情 + 对话入口 -->
      <div v-else class="agent-detail">
        <div class="detail-header">
          <div class="detail-avatar">{{ currentAgent?.name.charAt(0) }}</div>
          <div class="detail-meta">
            <h2 class="detail-name">{{ currentAgent?.name }}</h2>
            <p class="detail-desc">{{ currentAgent?.description || '暂无描述' }}</p>
          </div>
          <div class="detail-actions">
            <button class="action-btn" @click="openEditDialog(currentAgent!)">
              <el-icon :size="14"><EditPen /></el-icon>
              <span>编辑</span>
            </button>
            <button class="action-btn primary" @click="startChat(currentAgent!)">
              <el-icon :size="14"><ChatDotRound /></el-icon>
              <span>开始对话</span>
            </button>
          </div>
        </div>

        <!-- Agent 配置信息 -->
        <div class="detail-body">
          <div class="config-grid">
            <div class="config-card">
              <div class="config-label">系统提示词</div>
              <div class="config-value system-prompt">{{ currentAgent?.system_prompt || '-' }}</div>
            </div>
            <div class="config-card">
              <div class="config-label">模型</div>
              <div class="config-value">{{ currentAgent?.llm_model || '默认' }}</div>
            </div>
            <div class="config-card">
              <div class="config-label">最大 Token</div>
              <div class="config-value">{{ currentAgent?.max_tokens ?? '-' }}</div>
            </div>
            <div class="config-card">
              <div class="config-label">Temperature</div>
              <div class="config-value">{{ currentAgent?.temperature ?? '-' }}</div>
            </div>
            <div class="config-card">
              <div class="config-label">Top P</div>
              <div class="config-value">{{ currentAgent?.top_p ?? '-' }}</div>
            </div>
            <div class="config-card">
              <div class="config-label">技能</div>
              <div class="config-value">
                <template v-if="currentAgent?.enabled_skills?.length">
                  <span v-for="s in currentAgent.enabled_skills" :key="s" class="tag">{{ s }}</span>
                </template>
                <template v-else>未启用</template>
              </div>
            </div>
            <div class="config-card">
              <div class="config-label">MCP 服务器</div>
              <div class="config-value">
                <template v-if="currentAgent?.enabled_mcp_servers?.length">
                  <span v-for="m in currentAgent.enabled_mcp_servers" :key="m" class="tag">Server #{{ m }}</span>
                </template>
                <template v-else>未启用</template>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 子路由出口（仅在非工作台模式下使用） -->
      <router-view v-if="!isInWorkspace" />
    </div>

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
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="简要描述智能体的用途" maxlength="200" />
        </el-form-item>
        <el-form-item label="系统提示词" prop="system_prompt">
          <el-input v-model="form.system_prompt" type="textarea" :rows="5" placeholder="定义智能体的行为、角色和能力" maxlength="4000" />
        </el-form-item>
        <el-form-item label="LLM 模型">
          <el-select v-model="form.llm_model" placeholder="留空使用默认模型" clearable style="width: 100%">
            <el-option v-for="(_, name) in availableModels" :key="name" :label="name" :value="name" />
          </el-select>
        </el-form-item>
        <el-form-item label="Temperature">
          <el-slider v-model="form.temperature" :min="0" :max="2" :step="0.1" show-input />
        </el-form-item>
        <el-form-item label="Top P">
          <el-slider v-model="form.top_p" :min="0" :max="1" :step="0.1" show-input />
        </el-form-item>
        <el-form-item label="最大 Token">
          <el-input-number v-model="form.max_tokens" :min="1" :max="32768" :step="256" />
        </el-form-item>
        <el-form-item label="最大工具调用">
          <el-input-number v-model="form.max_tool_calls_per_turn" :min="1" :max="50" />
        </el-form-item>
        <el-form-item label="启用技能">
          <el-select v-model="form.enabled_skills" multiple placeholder="选择要启用的技能" style="width: 100%">
            <el-option v-for="skill in agentStore.skills" :key="skill.name" :label="skill.name" :value="skill.name">
              <span>{{ skill.name }}</span>
              <span style="color: var(--color-text-muted); font-size: 12px; margin-left: 8px">{{ skill.description }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="MCP 服务器">
          <el-select v-model="form.enabled_mcp_servers" multiple placeholder="选择要启用的 MCP 服务器" style="width: 100%">
            <el-option v-for="server in agentStore.mcpServers" :key="server.id" :label="server.name" :value="server.id">
              <span>{{ server.name }}</span>
              <span style="color: var(--color-text-muted); font-size: 12px; margin-left: 8px">{{ server.status }}</span>
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
        <el-button type="primary" :loading="mcpSubmitLoading" @click="handleMcpSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, inject, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, EditPen, ChatDotRound } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { useAgentStore } from '@/stores/agent'
import { chatApi } from '@/api/chat'
import NavIcon from '@/components/common/NavIcon.vue'
import type { Agent, CreateAgentRequest, UpdateAgentRequest, McpServer, CreateMcpServerRequest } from '@/api/types'

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const isInWorkspace = inject('isInWorkspace', false)

const isChatRoute = computed(() => route.name === 'AgentChat')

const selectedAgentId = ref<number | null>(null)
const currentAgent = computed(() => agentStore.agents.find((a) => a.id === selectedAgentId.value) || agentStore.currentAgent)

const availableModels = ref<Record<string, { max_tokens: number; temperature: number; top_p: number }>>({})

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
const isEditing = ref(false)
const editingId = ref<number | null>(null)
const submitLoading = ref(false)
const formRef = ref<FormInstance>()

const form = reactive<CreateAgentRequest & { temperature: number; top_p: number; max_tokens: number; max_tool_calls_per_turn: number }>({
  name: '',
  description: '',
  system_prompt: '',
  llm_model: '',
  temperature: 0.7,
  top_p: 0.8,
  max_tokens: 4096,
  max_tool_calls_per_turn: 10,
  enabled_skills: [],
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
  form.max_tool_calls_per_turn = 10
  form.enabled_skills = []
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
  form.system_prompt = agent.system_prompt
  form.llm_model = agent.llm_model || ''
  form.temperature = agent.temperature
  form.top_p = agent.top_p
  form.max_tokens = agent.max_tokens
  form.max_tool_calls_per_turn = agent.max_tool_calls_per_turn
  form.enabled_skills = agent.enabled_skills || []
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
      max_tool_calls_per_turn: form.max_tool_calls_per_turn,
      enabled_skills: form.enabled_skills?.length ? form.enabled_skills : undefined,
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

function handleSelectAgent(agent: Agent) {
  selectedAgentId.value = agent.id
  agentStore.currentAgent = agent
}

function startChat(agent: Agent) {
  if (isInWorkspace) {
    router.push({ name: 'WorkspaceAgentChat', params: { agentId: agent.id } })
  } else {
    router.push({ name: 'AgentChat', params: { agentId: agent.id } })
  }
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
    const connectionConfig: Record<string, unknown> = mcpForm.transport_type === 'streamable_http'
      ? { url: mcpForm.url }
      : { command: mcpForm.url }

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
watch(() => route.query.action, (action) => {
  if (action === 'create') {
    openCreateDialog()
    router.replace({ query: {} })
  }
})

onMounted(async () => {
  await Promise.all([
    agentStore.fetchAgents(),
    agentStore.fetchSkills(),
    agentStore.fetchMcpServers(),
    fetchModels(),
  ])
})
</script>

<style scoped>
.agent-view {
  display: flex;
  height: 100%;
  background: var(--color-bg);
  overflow: hidden;
}

/* ========================================
   Sidebar
   ======================================== */
.agent-sidebar {
  width: 280px;
  border-right: 1px solid var(--color-border-light);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  background: var(--color-bg-card);
}

.sidebar-top {
  padding: var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
}

.create-agent-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-lg);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-base);
}

.create-agent-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-muted);
}

.agent-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

.agent-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
  margin-bottom: 2px;
  position: relative;
}

.agent-item:hover {
  background: var(--color-bg-hover);
}

.agent-item.active {
  background: var(--color-primary-muted);
}

.agent-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  border-radius: 2px;
  background: var(--color-primary);
}

.agent-avatar {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, #E8F0FE 0%, #FEF1EE 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-primary);
  flex-shrink: 0;
}

.agent-info {
  flex: 1;
  min-width: 0;
}

.agent-name {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-desc {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 2px;
}

.agent-delete {
  opacity: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.agent-item:hover .agent-delete {
  opacity: 1;
}

.agent-delete:hover {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

.sidebar-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-faint);
}

/* ========================================
   Main Area — Empty State
   ======================================== */
.agent-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow-y: auto;
  position: relative;
}

.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8);
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
  background: linear-gradient(135deg, #E8F0FE 0%, #FEF1EE 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-6);
  box-shadow: 0 4px 16px rgba(66, 133, 244, 0.12);
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
   Agent Detail
   ======================================== */
.agent-detail {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: var(--space-6);
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-6);
  padding-bottom: var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
}

.detail-avatar {
  width: 52px;
  height: 52px;
  border-radius: var(--radius-xl);
  background: linear-gradient(135deg, #E8F0FE 0%, #FEF1EE 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-primary);
  flex-shrink: 0;
}

.detail-meta {
  flex: 1;
  min-width: 0;
}

.detail-name {
  font-size: var(--text-xl);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  margin: 0;
}

.detail-desc {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-top: var(--space-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-base);
}

.action-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.action-btn.primary {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #FFFFFF;
}

.action-btn.primary:hover {
  background: var(--color-primary-hover);
}

/* ========================================
   Config Grid
   ======================================== */
.detail-body {
  flex: 1;
}

.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}

.config-card {
  padding: var(--space-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
}

.config-card:first-child {
  grid-column: 1 / -1;
}

.config-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: var(--space-2);
}

.config-value {
  font-size: var(--text-sm);
  color: var(--color-text);
  line-height: var(--leading-relaxed);
}

.system-prompt {
  max-height: 120px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.tag {
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
