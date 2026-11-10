<template>
  <el-dialog
    :model-value="modelValue"
    :title="isGroupPreset ? '新建协作对话' : autoBind ? '连接本地项目' : '选择助手'"
    width="560px"
    top="10vh"
    class="agent-form-dialog"
    destroy-on-close
    append-to-body
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <div class="agent-form-scroll">
      <div class="agent-form">
        <!-- 助手直达层（助手对话/本地项目 +）：点卡片即走，无配置无确认按钮 -->
        <template v-if="!isGroupPreset">
          <div class="form-section">
            <h4>{{ autoBind ? '选择助手连接本地项目' : '选择助手开始对话' }}</h4>
            <div class="field-hint">
              {{
                autoBind
                  ? '选定后将创建会话并选择本地文件夹作为工作目录'
                  : '点击即进入对话，发送第一条消息开始'
              }}
            </div>
            <div class="agent-grid">
              <button
                v-for="agent in agentStore.agents"
                :key="agent.id"
                type="button"
                class="agent-card"
                :disabled="picking"
                @click="handlePickAgent(agent)"
              >
                <span class="agent-card-avatar">{{ agent.name.charAt(0) }}</span>
                <span class="agent-card-info">
                  <span class="agent-card-name">{{ agent.name }}</span>
                  <span class="agent-card-desc">{{ agent.description || '暂无描述' }}</span>
                </span>
              </button>
            </div>
            <div v-if="agentStore.agents.length === 0" class="agent-grid-empty">
              暂无助手，请先在「助手」中创建
            </div>
          </div>
        </template>

        <!-- 协作形态：成员多选 + 模式卡（默认头脑风暴，不阻塞）；主持人/轮数/名称后置到群内设置 -->
        <template v-else>
          <div class="form-section">
            <h4>选择成员（至少 2 人）</h4>
            <GroupMemberPicker v-model="form.member_ids" :agents="agentStore.agents" :host-agent-id="null" />
          </div>
          <div class="form-section">
            <h4>讨论模式</h4>
            <div class="mode-cards">
              <button
                type="button"
                class="mode-card"
                :class="{ selected: form.mode === 'brainstorm' }"
                @click="form.mode = 'brainstorm'"
              >
                <span class="mode-card-title">头脑风暴</span>
                <span class="mode-card-desc">全员依次发言讨论</span>
              </button>
              <button
                type="button"
                class="mode-card"
                :class="{ selected: form.mode === 'consult' }"
                @click="form.mode = 'consult'"
              >
                <span class="mode-card-title">专家咨询</span>
                <span class="mode-card-desc">主持人按需问成员</span>
              </button>
            </div>
            <div class="field-hint">
              {{
                form.mode === 'consult'
                  ? '主持人默认为第一位选中成员，进入后可在群设置中调整'
                  : '创建后可在群设置中调整轮数与成员'
              }}
            </div>
          </div>
        </template>
      </div>
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">
        {{ isGroupPreset ? '取消' : '关闭' }}
      </el-button>
      <el-button v-if="isGroupPreset" type="primary" :loading="submitLoading" @click="handleSubmit">
        创建协作对话
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * 统一创建对话弹窗（两形态）：
 *
 * - agent 形态（助手对话/本地项目 +）＝选择助手直达层：卡片网格点选即走，
 *   无配置无确认——助手对话直接进空输入框（lazy，发首条消息才落库）；
 *   本地项目（autoBind）显式建会话（后端幂等）后经直达路由 + bind=1
 *   自动弹工作目录绑定。对齐业界「新建对话零配置」范式。
 * - group 形态（协作对话 +）＝成员多选 + 模式卡（默认头脑风暴不阻塞）；
 *   群名自动「A × B」、consult 主持人默认首位成员、轮数默认 1——全部
 *   后置到群内设置（GroupFormDialog 经 PUT /groups 修改）。
 */
import { reactive, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAgentStore } from '@/stores/agent'
import { useAgentGroupStore } from '@/stores/agentGroup'
import { agentApi } from '@/api/agent'
import { agentGroupApi } from '@/api/agentGroup'
import type { Agent, GroupMode } from '@/api/types'
import GroupMemberPicker from '@/components/agent/group/GroupMemberPicker.vue'
import './formDialog.css'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    /** 创建形态：agent=选择助手直达层；group=协作配置 */
    preset?: 'agent' | 'group'
    /** agent 形态下：选定助手后显式建会话并自动弹目录绑定（本地项目 + 专用） */
    autoBind?: boolean
  }>(),
  { preset: 'agent', autoBind: false },
)
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  /** 协作对话创建成功（已刷新群列表），供宿主刷新会话中心 */
  (e: 'created'): void
}>()

const router = useRouter()
const agentStore = useAgentStore()
const groupStore = useAgentGroupStore()

const isGroupPreset = computed(() => props.preset === 'group')

// ==================== agent 形态：点卡片即走 ====================

const picking = ref(false)

async function handlePickAgent(agent: Agent) {
  if (picking.value) return
  // 助手对话：直接进空输入框（lazy——首条消息时后端建会话）
  if (!props.autoBind) {
    emit('update:modelValue', false)
    router.push({ name: 'WorkspaceAgentChat', params: { agentId: agent.id } })
    return
  }
  // 本地项目：显式建会话（幂等）→ 直达路由 + bind=1 自动弹目录绑定
  picking.value = true
  try {
    const session = await agentApi.createSession(agent.id)
    emit('update:modelValue', false)
    router.push({
      name: 'WorkspaceSessionChat',
      params: { sessionId: session.session_id },
      query: { bind: '1' },
    })
  } catch {
    // 错误 toast 由请求拦截器统一弹，弹窗保持开启可重试
  } finally {
    picking.value = false
  }
}

// ==================== group 形态：成员 + 模式 ====================

const submitLoading = ref(false)

const form = reactive<{ mode: GroupMode; member_ids: number[] }>({
  mode: 'brainstorm',
  member_ids: [],
})

// 选中成员（按勾选顺序）——群名生成与 consult 默认主持人都依赖此序
const selectedAgents = computed(() =>
  agentStore.agents.filter((a) => form.member_ids.includes(a.id)),
)

/** 群名自动生成「A × B」（前 3 位，超出加「等 N 人」）；不可改——后置到群内设置 */
function autoGroupName(): string {
  const names = selectedAgents.value.map((a) => a.name)
  if (names.length <= 3) return names.join(' × ')
  return `${names.slice(0, 3).join(' × ')} 等${names.length}人`
}

// 每次打开重置（destroy-on-close 只销毁 DOM，组件状态需手动复位）
watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      form.mode = 'brainstorm'
      form.member_ids = []
    }
  },
)

async function handleSubmit() {
  const selected = form.member_ids
  if (selected.length < 2) {
    ElMessage.warning('协作对话需要至少 2 名成员')
    return
  }
  submitLoading.value = true
  try {
    const detail = await agentGroupApi.createGroup({
      name: autoGroupName(),
      description: undefined,
      mode: form.mode,
      member_ids: selected,
      // consult 默认主持人＝第一位选中成员（后置可在群设置改）；brainstorm 轮数默认 1
      host_agent_id: form.mode === 'consult' ? selected[0] : null,
      rounds_per_turn: form.mode === 'brainstorm' ? 1 : undefined,
    })
    ElMessage.success('协作对话已创建')
    await groupStore.fetchGroups()
    emit('created')
    emit('update:modelValue', false)
    router.push({ name: 'WorkspaceGroupChat', params: { groupId: detail.id } })
  } catch {
    // 失败保持弹窗开启可改配置重试；错误 toast 由请求拦截器弹出
  } finally {
    submitLoading.value = false
  }
}
</script>

<style scoped>
/* 助手直达层：卡片网格（点选即走） */
.agent-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.agent-card {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
  cursor: pointer;
  text-align: left;
  font-family: var(--font-body);
  transition: all var(--transition-fast);
  min-width: 0;
}

.agent-card:hover:not(:disabled) {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
}

.agent-card:disabled {
  opacity: 0.5;
  cursor: wait;
}

.agent-card-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  flex-shrink: 0;
}

.agent-card-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.agent-card-name {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-card-desc {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-grid-empty {
  padding: var(--space-6) 0;
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

/* 模式卡：同 GroupFormDialog 的全局样式，此处 scoped 自持一份
   （弹窗自包含，不依赖另一组件恰好被加载） */
.mode-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

.mode-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
  cursor: pointer;
  text-align: left;
  font-family: var(--font-body);
  transition: all var(--transition-fast);
  min-width: 0;
}

.mode-card:hover {
  border-color: var(--color-border);
  background: var(--color-bg-hover);
}

.mode-card.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
}

.mode-card-title {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.mode-card-desc {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

@media (max-width: 560px) {
  .agent-grid,
  .mode-cards {
    grid-template-columns: 1fr;
  }
}
</style>
