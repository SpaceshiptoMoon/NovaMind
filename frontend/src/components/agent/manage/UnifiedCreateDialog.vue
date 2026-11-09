<template>
  <el-dialog
    :model-value="modelValue"
    title="新建对话"
    width="560px"
    top="10vh"
    class="agent-form-dialog"
    destroy-on-close
    append-to-body
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <div class="agent-form-scroll">
      <div class="agent-form">
        <div class="form-section">
          <h4>选择成员</h4>
          <GroupMemberPicker
            v-model="form.member_ids"
            :agents="agentStore.agents"
            :host-agent-id="form.mode === 'consult' ? form.host_agent_id : null"
          />
          <!-- 单聊/协作分岔提示：满 2 人那一刻出现（行内 hint，不打断） -->
          <div v-if="form.member_ids.length >= 2" class="collab-hint">将开启协作讨论</div>
          <div v-else-if="form.member_ids.length === 1" class="field-hint">
            只选 1 人：确定后直接进入与该智能体的单聊，不创建群聊
          </div>
        </div>

        <!-- 协作配置区：仅 ≥2 人时展开 -->
        <template v-if="form.member_ids.length >= 2">
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
          </div>

          <div class="form-section">
            <h4>群聊配置</h4>
            <el-form-item v-if="form.mode === 'consult'" label="主持人">
              <el-select
                v-model="form.host_agent_id"
                placeholder="选择主持人（须为已选成员）"
                style="width: 100%"
              >
                <el-option
                  v-for="agent in selectedAgents"
                  :key="agent.id"
                  :label="agent.name"
                  :value="agent.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item v-if="form.mode === 'brainstorm'" label="讨论轮数">
              <el-input-number
                v-model="form.rounds_per_turn"
                :min="1"
                :max="3"
                :step="1"
                :controls="false"
                class="rounds-input"
              />
              <span class="rounds-hint">成员依次发言的轮数（1~3）</span>
            </el-form-item>
            <el-form-item label="群名称">
              <el-input
                v-model="form.name"
                placeholder="为群聊起个名字"
                maxlength="50"
                @input="nameEdited = true"
              />
            </el-form-item>
          </div>
        </template>
      </div>
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitLoading" @click="handleSubmit">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * 统一创建对话弹窗：成员多选一个入口分岔单聊与群聊。
 *
 * 选 1 人 = 不创建任何实体，直接进该 agent 的单聊页；≥2 人 = 协作配置
 * （brainstorm/consult 两模式卡 + 主持人/轮数 + 群名自动预填「A × B」）
 * 后建群进群聊页。失败不关弹窗（错误 toast 由请求拦截器统一弹，
 * 与 GroupFormDialog 同约定，此处不重复弹）。agent 条目/群条目的
 * 「编辑」不走此弹窗，仍各走 AgentFormDialog/GroupFormDialog。
 */
import { reactive, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAgentStore } from '@/stores/agent'
import { useAgentGroupStore } from '@/stores/agentGroup'
import { agentGroupApi } from '@/api/agentGroup'
import type { GroupMode } from '@/api/types'
import GroupMemberPicker from '@/components/agent/group/GroupMemberPicker.vue'
import './formDialog.css'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const router = useRouter()
const agentStore = useAgentStore()
const groupStore = useAgentGroupStore()

const submitLoading = ref(false)
// 用户是否手动改过群名：改过后自动预填不再覆盖（「可改」语义）
const nameEdited = ref(false)

const form = reactive<{
  name: string
  mode: GroupMode
  member_ids: number[]
  host_agent_id: number | null
  rounds_per_turn: number
}>({
  name: '',
  mode: 'brainstorm',
  member_ids: [],
  host_agent_id: null,
  rounds_per_turn: 1,
})

// consult 主持人下拉选项 = 已选成员（按选中顺序）
const selectedAgents = computed(() =>
  agentStore.agents.filter((a) => form.member_ids.includes(a.id)),
)

// 群名自动预填「A × B」：按选中顺序拼接（checkbox 选中序），选满 2 人起生效；
// 不足 2 人清空（协作区隐藏，名字无意义）；用户手动改过即不再覆盖
watch(
  () => form.member_ids,
  (ids) => {
    if (nameEdited.value) return
    if (ids.length >= 2) {
      form.name = ids
        .map((id) => agentStore.agents.find((a) => a.id === id)?.name)
        .filter((name): name is string => !!name)
        .join(' × ')
    } else {
      form.name = ''
    }
  },
)

function resetForm() {
  nameEdited.value = false
  form.name = ''
  form.mode = 'brainstorm'
  form.member_ids = []
  form.host_agent_id = null
  form.rounds_per_turn = 1
}

// 每次打开重置（destroy-on-close 只销毁 DOM，组件状态需手动复位）
watch(
  () => props.modelValue,
  (visible) => {
    if (visible) resetForm()
  },
)

async function handleSubmit() {
  const selected = form.member_ids
  if (selected.length === 0) {
    ElMessage.warning('请先选择成员')
    return
  }

  // 单聊分岔：恰好 1 人不创建任何实体，直接进对话页
  if (selected.length === 1) {
    const agentId = selected[0]
    if (agentId === undefined) return
    await router.push({ name: 'WorkspaceAgentChat', params: { agentId } })
    emit('update:modelValue', false)
    return
  }

  // 协作分岔：≥2 人建群（提交前校验与 GroupFormDialog 对齐）
  if (form.mode === 'consult' && (!form.host_agent_id || !selected.includes(form.host_agent_id))) {
    ElMessage.error('请为专家咨询模式选择主持人（须为已选成员）')
    return
  }
  if (!form.name.trim()) {
    ElMessage.error('请输入群名称')
    return
  }

  submitLoading.value = true
  try {
    const detail = await agentGroupApi.createGroup({
      name: form.name.trim(),
      description: undefined,
      mode: form.mode,
      member_ids: selected,
      host_agent_id: form.mode === 'consult' ? form.host_agent_id : null,
      rounds_per_turn: form.mode === 'brainstorm' ? form.rounds_per_turn : undefined,
    })
    ElMessage.success('群聊已创建')
    // 刷新侧栏列表后建完即进群（与 GroupFormDialog 同体验）
    await groupStore.fetchGroups()
    emit('update:modelValue', false)
    router.push({ name: 'WorkspaceGroupChat', params: { groupId: detail.id } })
  } catch {
    // 失败保持弹窗开启可改配置重试；错误 toast 已由请求拦截器弹出
  } finally {
    submitLoading.value = false
  }
}
</script>

<style scoped>
/* 单聊/协作分岔提示：满 2 人那一刻出现，primary 弱底行内 hint（不用 ElMessage 打断） */
.collab-hint {
  margin-top: var(--space-2);
  padding: 4px var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-primary-muted);
  color: var(--color-primary);
  font-size: var(--text-xs);
  line-height: 1.4;
}

/* 模式卡与轮数提示：同 GroupFormDialog 的全局样式，此处 scoped 自持一份
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

.rounds-input {
  width: 80px;
}

.rounds-input :deep(.el-input__inner) {
  text-align: center;
}

.rounds-hint {
  margin-left: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
}

@media (max-width: 480px) {
  .mode-cards {
    grid-template-columns: 1fr;
  }

  .rounds-hint {
    display: block;
    margin-left: 0;
    margin-top: 4px;
    white-space: normal;
  }
}
</style>
