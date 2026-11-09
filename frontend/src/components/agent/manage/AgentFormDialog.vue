<template>
  <el-dialog
    :model-value="modelValue"
    :title="agent ? '编辑智能体' : '创建智能体'"
    width="880px"
    top="7vh"
    class="agent-form-dialog"
    destroy-on-close
    append-to-body
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <div class="agent-form-scroll">
      <el-form
        :model="agentForm"
        :rules="agentFormRules"
        ref="agentFormRef"
        label-position="top"
        class="agent-form"
      >
        <div class="agent-form-columns">
          <!-- 左列：身份设定 -->
          <div class="agent-form-col">
            <div class="form-section">
              <h4>身份设定</h4>
              <el-form-item label="名称" prop="name">
                <el-input
                  v-model="agentForm.name"
                  placeholder="为智能体起个名字"
                  maxlength="50"
                />
              </el-form-item>
              <el-form-item label="描述">
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
                  :rows="14"
                  placeholder="定义智能体的行为、角色和能力"
                  maxlength="4000"
                  class="prompt-textarea"
                />
                <div class="field-hint">描述角色、语气、边界与输出格式，越具体越好</div>
              </el-form-item>
            </div>
          </div>

          <!-- 右列：模型参数 + 能力扩展 -->
          <div class="agent-form-col">
            <div class="form-section">
              <h4>模型与生成参数</h4>
              <el-form-item label="LLM 模型">
                <el-select
                  v-model="agentForm.llm_model"
                  placeholder="留空使用默认模型"
                  clearable
                  style="width: 100%"
                >
                  <el-option-group v-if="llmModelNames.length" label="LLM 文本模型">
                    <el-option
                      v-for="name in llmModelNames"
                      :key="name"
                      :label="name"
                      :value="name"
                    />
                  </el-option-group>
                  <el-option-group v-if="vlmModelNames.length" label="VLM 视觉模型">
                    <el-option
                      v-for="name in vlmModelNames"
                      :key="name"
                      :label="name"
                      :value="name"
                    />
                  </el-option-group>
                </el-select>
              </el-form-item>
              <div class="param-twin">
                <el-form-item label="Temperature">
                  <div class="param-row">
                    <el-slider
                      v-model="agentForm.temperature"
                      :min="0"
                      :max="2"
                      :step="0.1"
                      class="param-slider"
                    />
                    <el-input-number
                      v-model="agentForm.temperature"
                      :min="0"
                      :max="2"
                      :step="0.1"
                      :controls="false"
                      size="small"
                      class="param-number"
                    />
                  </div>
                  <div class="param-hint">越高越发散，越低越确定</div>
                </el-form-item>
                <el-form-item label="Top P">
                  <div class="param-row">
                    <el-slider
                      v-model="agentForm.top_p"
                      :min="0"
                      :max="1"
                      :step="0.1"
                      class="param-slider"
                    />
                    <el-input-number
                      v-model="agentForm.top_p"
                      :min="0"
                      :max="1"
                      :step="0.1"
                      :controls="false"
                      size="small"
                      class="param-number"
                    />
                  </div>
                  <div class="param-hint">核采样阈值，与温度二选一</div>
                </el-form-item>
              </div>
              <div class="param-grid">
                <el-form-item label="最大生成 Token">
                  <el-input-number
                    v-model="agentForm.max_tokens"
                    :min="1"
                    :max="32768"
                    :step="256"
                    :controls="false"
                    class="param-input-number"
                  />
                </el-form-item>
                <el-form-item label="上下文窗口">
                  <el-input-number
                    v-model="agentForm.context_window"
                    :min="2048"
                    :max="1048576"
                    :step="4096"
                    :controls="false"
                    class="param-input-number"
                  />
                </el-form-item>
                <el-form-item label="工具调用上限">
                  <el-input-number
                    v-model="agentForm.max_tool_calls_per_turn"
                    :min="1"
                    :max="50"
                    :controls="false"
                    class="param-input-number"
                  />
                </el-form-item>
              </div>
            </div>

            <div class="form-section">
              <h4>能力扩展</h4>
              <el-form-item label="计划模式">
                <div class="plan-mode-switch">
                  <el-switch v-model="agentForm.plan_mode" />
                  <span class="plan-mode-tip"
                    >开启后按「计划 → 逐步执行 → 总结」的 Plan-and-Execute 流程工作</span
                  >
                </div>
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
                    <span class="option-inline-desc">{{ tool.description }}</span>
                  </el-option>
                </el-select>
              </el-form-item>
              <el-form-item v-if="showKnowledgeScopeConfig" label="知识范围">
                <div class="kb-scope-config">
                  <div class="kb-scope-config-hint">
                    新会话默认限定知识检索的空间范围；会话内仍可临时调整。不选则检索全部可见空间。
                  </div>
                  <div class="kb-scope-config-toolbar">
                    <el-checkbox
                      :model-value="kbScopeAllSelected"
                      :indeterminate="kbScopeIndeterminate"
                      @change="toggleAllKbScope"
                      >全选</el-checkbox
                    >
                    <span class="kb-scope-config-count"
                      >已选 {{ agentForm.knowledgeSpaceIds.length }}</span
                    >
                  </div>
                  <el-checkbox-group v-model="agentForm.knowledgeSpaceIds" class="kb-scope-config-list">
                    <el-checkbox v-for="sp in kbScopeSpaces" :key="sp.id" :value="sp.id">
                      <span class="kb-scope-config-name">{{ sp.name }}</span>
                    </el-checkbox>
                  </el-checkbox-group>
                  <div v-if="kbScopeSpaces.length === 0" class="kb-scope-config-empty">
                    暂无可见空间
                  </div>
                </div>
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
                    <span class="option-inline-desc">{{ server.status }}</span>
                  </el-option>
                </el-select>
              </el-form-item>
            </div>
          </div>
        </div>
      </el-form>
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitLoading" @click="handleSubmit">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * Agent 创建/编辑弹窗（原 WorkspaceLayout 内联段拆出）：880px 双列表单
 * （身份设定/模型参数/能力扩展/知识范围/MCP）。
 *
 * 传 agent = 编辑（列表接口不含 system_prompt，打开后拉详情补齐——否则必填校验
 * 卡死）；不传 = 创建。提交走 agentStore，extra_config 保留既有扩展键仅覆写
 * plan_mode 与 knowledge_bindings。
 */
import { reactive, ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useAgentStore } from '@/stores/agent'
import { agentApi } from '@/api/agent'
import { spaceApi } from '@/api/space'
import type { Agent, CreateAgentRequest, UpdateAgentRequest, Space } from '@/api/types'
import './formDialog.css'

const props = defineProps<{ modelValue: boolean; agent: Agent | null }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const agentStore = useAgentStore()

const agentFormRef = ref<FormInstance>()
const submitLoading = ref(false)

const agentForm = reactive<
  CreateAgentRequest & {
    temperature: number
    top_p: number
    max_tokens: number
    max_tool_calls_per_turn: number
    plan_mode: boolean
    knowledgeSpaceIds: number[]
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
  plan_mode: false,
  knowledgeSpaceIds: [],
  enabled_tools: [],
  enabled_mcp_servers: [],
})

const agentFormRules: FormRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  system_prompt: [{ required: true, message: '请输入系统提示词', trigger: 'blur' }],
}

function resetForm() {
  agentForm.name = ''
  agentForm.description = ''
  agentForm.system_prompt = ''
  agentForm.llm_model = ''
  agentForm.temperature = 0.7
  agentForm.top_p = 0.8
  agentForm.max_tokens = 4096
  agentForm.context_window = 32768
  agentForm.max_tool_calls_per_turn = 10
  agentForm.plan_mode = false
  agentForm.knowledgeSpaceIds = []
  agentForm.enabled_tools = []
  agentForm.enabled_mcp_servers = []
}

// —— Agent 级默认知识范围（extra_config.knowledge_bindings，新会话 seed 用）——
const kbScopeSpaces = ref<Space[]>([])
const kbScopeLoaded = ref(false)

// 只有勾选了 knowledge_search 工具才需要配置知识范围
const showKnowledgeScopeConfig = computed(() =>
  (agentForm.enabled_tools || []).includes('knowledge_search'),
)

// 弹窗打开且门控可见时才拉空间列表（复用会话页口径：可见空间前 50）
watch(showKnowledgeScopeConfig, (visible) => {
  if (visible && !kbScopeLoaded.value) {
    spaceApi
      .getSpaces({ skip: 0, limit: 50 })
      .then((res) => {
        kbScopeSpaces.value = res.items
      })
      .catch(() => {
        kbScopeSpaces.value = []
      })
      .finally(() => {
        kbScopeLoaded.value = true
      })
  }
})

const kbScopeIndeterminate = computed(
  () =>
    agentForm.knowledgeSpaceIds.length > 0 &&
    agentForm.knowledgeSpaceIds.length < kbScopeSpaces.value.length,
)
const kbScopeAllSelected = computed(
  () =>
    kbScopeSpaces.value.length > 0 &&
    agentForm.knowledgeSpaceIds.length === kbScopeSpaces.value.length,
)

function toggleAllKbScope(checked: boolean | string | number) {
  agentForm.knowledgeSpaceIds = checked ? kbScopeSpaces.value.map((s) => s.id) : []
}

// 编辑中的 Agent 原始 extra_config（提交时保留既有扩展键，仅覆写 plan_mode）
const editingExtra = ref<Record<string, unknown> | null>(null)

// 从 agent.extra_config.knowledge_bindings 读默认空间范围（结构异常时忽略）
function thisAgentKnowledgeSpaceIds(agent: Agent): number[] {
  const bindings = agent.extra_config?.knowledge_bindings as
    | { space_ids?: number[] | null }
    | undefined
  return Array.isArray(bindings?.space_ids) ? bindings.space_ids : []
}

// 弹窗打开即回填：agent 非空 = 编辑模式
watch(
  () => [props.modelValue, props.agent] as const,
  ([visible, agent]) => {
    if (!visible) return
    if (agent) {
      editingExtra.value = agent.extra_config || null
      agentForm.name = agent.name
      agentForm.description = agent.description || ''
      // 列表接口不含 system_prompt（AgentResponse 有意精简），先占位再拉详情补齐，
      // 否则必填校验卡死、确定发不出去
      agentForm.system_prompt = ''
      agentForm.llm_model = agent.llm_model || ''
      agentForm.temperature = agent.temperature
      agentForm.top_p = agent.top_p
      agentForm.max_tokens = agent.max_tokens
      agentForm.context_window = agent.context_window || 32768
      agentForm.max_tool_calls_per_turn = agent.max_tool_calls_per_turn
      agentForm.plan_mode = agent.extra_config?.plan_mode === true
      agentForm.knowledgeSpaceIds = thisAgentKnowledgeSpaceIds(agent)
      agentForm.enabled_tools = agent.enabled_tools || []
      agentForm.enabled_mcp_servers = agent.enabled_mcp_servers || []
      agentApi
        .getAgent(agent.id)
        .then((detail) => {
          agentForm.system_prompt = detail.system_prompt ?? ''
          editingExtra.value = detail.extra_config || editingExtra.value
        })
        .catch(() => {
          ElMessage.error('加载智能体详情失败')
        })
    } else {
      editingExtra.value = null
      resetForm()
    }
  },
)

async function handleSubmit() {
  const valid = await agentFormRef.value?.validate().catch(() => false)
  if (!valid) return

  submitLoading.value = true
  try {
    // extra_config 保留既有键（编辑时不丢其他扩展配置），仅覆写 plan_mode 与 knowledge_bindings
    const existingExtra = (props.agent ? editingExtra.value : null) || {}
    const extraConfig: Record<string, unknown> = { ...existingExtra, plan_mode: agentForm.plan_mode }
    // 勾选 knowledge_search 且选了空间才写 knowledge_bindings；
    // 未选工具时清掉残留绑定（工具都没了，配置无意义，也避免下次启用误以为已配置）
    if ((agentForm.enabled_tools || []).includes('knowledge_search')) {
      if (agentForm.knowledgeSpaceIds.length) {
        extraConfig.knowledge_bindings = { space_ids: agentForm.knowledgeSpaceIds }
      } else {
        delete extraConfig.knowledge_bindings
      }
    } else {
      delete extraConfig.knowledge_bindings
    }
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
      extra_config: extraConfig,
      enabled_tools: agentForm.enabled_tools?.length ? agentForm.enabled_tools : undefined,
      enabled_mcp_servers: agentForm.enabled_mcp_servers?.length
        ? agentForm.enabled_mcp_servers
        : undefined,
    }

    if (props.agent) {
      await agentStore.updateAgent(props.agent.id, data)
      ElMessage.success('智能体已更新')
    } else {
      await agentStore.createAgent(data as CreateAgentRequest)
      ElMessage.success('智能体已创建')
    }
    emit('update:modelValue', false)
  } catch {
    // Error already shown
  } finally {
    submitLoading.value = false
  }
}

// ===================== 模型可选项 =====================

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

onMounted(async () => {
  try {
    const data = await agentApi.getModels()
    availableModels.value = data.models
  } catch {
    // ignore
  }
})
</script>

<style>
/* append-to-body 弹窗内专属样式（全局）：计划模式开关行 + 知识范围配置卡 */
.plan-mode-switch {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  min-width: 0;
}

.plan-mode-tip {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  word-break: break-word;
}

/* 知识范围（默认）配置卡：勾选 knowledge_search 工具后出现 */
.kb-scope-config {
  width: 100%;
  min-width: 0;
}

.kb-scope-config-hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  word-break: break-word;
  margin-bottom: 6px;
}

.kb-scope-config-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: 4px;
}

.kb-scope-config-count {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}

.kb-scope-config-list {
  display: flex;
  flex-direction: column;
  max-height: 148px;
  overflow-y: auto;
  border: 1px solid var(--color-border-light);
  border-radius: 6px;
  padding: 4px 10px;
}

.kb-scope-config-list .el-checkbox {
  margin-right: 0;
  height: 26px;
}

.kb-scope-config-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-scope-config-empty {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  border: 1px dashed var(--color-border-light);
  border-radius: 6px;
  padding: 10px;
  text-align: center;
}

/* 下拉选项行内说明（原模板内联样式收编为 class） */
.option-inline-desc {
  color: var(--color-text-muted);
  font-size: 12px;
  margin-left: 8px;
}
</style>
