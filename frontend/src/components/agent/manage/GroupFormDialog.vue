<template>
  <el-dialog
    :model-value="modelValue"
    :title="groupId ? '编辑群聊' : '创建群聊'"
    width="880px"
    top="7vh"
    class="agent-form-dialog"
    destroy-on-close
    append-to-body
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <div class="agent-form-scroll">
      <el-form
        :model="groupForm"
        :rules="groupFormRules"
        ref="groupFormRef"
        label-position="top"
        class="agent-form"
      >
        <div class="agent-form-columns">
          <!-- 左列：基本信息 -->
          <div class="agent-form-col">
            <div class="form-section">
              <h4>基本信息</h4>
              <el-form-item label="名称" prop="name">
                <el-input
                  v-model="groupForm.name"
                  placeholder="为群聊起个名字"
                  maxlength="50"
                />
              </el-form-item>
              <el-form-item label="描述">
                <el-input
                  v-model="groupForm.description"
                  type="textarea"
                  :rows="3"
                  placeholder="这个群用来讨论什么"
                  maxlength="200"
                />
              </el-form-item>
              <div v-if="groupForm.mode === 'brainstorm'" class="field-hint">
                每次发送消息，成员按顺序依次发言，沉默者后续轮自动跳过
              </div>
              <div v-else class="field-hint">
                主持人接管回答，按需咨询其他成员后汇总答复
              </div>
            </div>
          </div>

          <!-- 右列：模式 + 成员 -->
          <div class="agent-form-col">
            <div class="form-section">
              <h4>讨论模式</h4>
              <div class="mode-cards">
                <button
                  type="button"
                  class="mode-card"
                  :class="{ selected: groupForm.mode === 'brainstorm' }"
                  @click="groupForm.mode = 'brainstorm'"
                >
                  <span class="mode-card-title">头脑风暴</span>
                  <span class="mode-card-desc">全员依次发言讨论</span>
                </button>
                <button
                  type="button"
                  class="mode-card"
                  :class="{ selected: groupForm.mode === 'consult' }"
                  @click="groupForm.mode = 'consult'"
                >
                  <span class="mode-card-title">专家咨询</span>
                  <span class="mode-card-desc">主持人按需问成员</span>
                </button>
              </div>
            </div>

            <div class="form-section">
              <h4>成员（至少 2 人）</h4>
              <el-form-item prop="member_ids">
                <GroupMemberPicker
                  v-model="groupForm.member_ids"
                  :agents="agentStore.agents"
                  :host-agent-id="groupForm.mode === 'consult' ? groupForm.host_agent_id : null"
                />
              </el-form-item>
              <el-form-item v-if="groupForm.mode === 'consult'" label="主持人">
                <el-select
                  v-model="groupForm.host_agent_id"
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
              <el-form-item v-if="groupForm.mode === 'brainstorm'" label="讨论轮数">
                <el-input-number
                  v-model="groupForm.rounds_per_turn"
                  :min="1"
                  :max="3"
                  :step="1"
                  :controls="false"
                  class="param-input-number"
                />
                <span class="rounds-hint">成员依次发言的轮数（1~3）</span>
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
 * 群聊创建/编辑弹窗（原 WorkspaceLayout 内联段拆出）：880px 双列
 * （基本信息/讨论模式 radio 卡/成员选择/主持人/轮数）。
 *
 * 传 groupId = 编辑（先拉详情回填）；不传 = 创建，创建成功直接进群聊页
 * （与单聊「创建后进对话」同体验）。列表刷新走 groupStore.fetchGroups。
 */
import { reactive, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useAgentStore } from '@/stores/agent'
import { useAgentGroupStore } from '@/stores/agentGroup'
import { agentGroupApi } from '@/api/agentGroup'
import type { GroupMode } from '@/api/types'
import GroupMemberPicker from '@/components/agent/group/GroupMemberPicker.vue'
import './formDialog.css'

const props = defineProps<{ modelValue: boolean; groupId: number | null }>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  /** 编辑保存成功（详情已更新）——宿主（群页）借此刷新 currentGroup 展示 */
  (e: 'updated'): void
}>()

const router = useRouter()
const agentStore = useAgentStore()
const groupStore = useAgentGroupStore()

const groupFormRef = ref<FormInstance>()
const submitLoading = ref(false)

const groupForm = reactive<{
  name: string
  description: string
  mode: GroupMode
  member_ids: number[]
  host_agent_id: number | null
  rounds_per_turn: number
}>({
  name: '',
  description: '',
  mode: 'brainstorm',
  member_ids: [],
  host_agent_id: null,
  rounds_per_turn: 1,
})

const groupFormRules: FormRules = {
  name: [{ required: true, message: '请输入群名称', trigger: 'blur' }],
  member_ids: [
    {
      required: true,
      validator: (_rule, value: number[] | undefined, callback) => {
        if (!value || value.length < 2) callback(new Error('请至少选择 2 名成员'))
        else callback()
      },
      trigger: 'change',
    },
  ],
}

// consult 模式主持人下拉选项 = 已选成员
const selectedAgents = computed(() =>
  agentStore.agents.filter((a) => groupForm.member_ids.includes(a.id)),
)

function resetForm() {
  groupForm.name = ''
  groupForm.description = ''
  groupForm.mode = 'brainstorm'
  groupForm.member_ids = []
  groupForm.host_agent_id = null
  groupForm.rounds_per_turn = 1
}

async function loadGroupForEdit(groupId: number) {
  try {
    const detail = await agentGroupApi.getGroup(groupId)
    groupForm.name = detail.name
    groupForm.description = detail.description || ''
    groupForm.mode = detail.mode
    groupForm.member_ids = detail.members.map((m) => m.agent_id)
    groupForm.host_agent_id = detail.host_agent_id
    groupForm.rounds_per_turn = detail.extra_config?.rounds_per_turn ?? 1
  } catch {
    ElMessage.error('加载群详情失败')
  }
}

// 弹窗打开即回填：groupId 非空 = 编辑模式
watch(
  () => [props.modelValue, props.groupId] as const,
  ([visible, groupId]) => {
    if (!visible) return
    resetForm()
    if (groupId) {
      loadGroupForEdit(groupId)
    }
  },
)

async function handleSubmit() {
  const valid = await groupFormRef.value?.validate().catch(() => false)
  if (!valid) return

  submitLoading.value = true
  try {
    if (groupForm.mode === 'consult' && (!groupForm.host_agent_id || !groupForm.member_ids.includes(groupForm.host_agent_id))) {
      ElMessage.error('请为专家咨询模式选择主持人（须为已选成员）')
      return
    }
    if (props.groupId) {
      await agentGroupApi.updateGroup(props.groupId, {
        name: groupForm.name,
        description: groupForm.description || undefined,
        mode: groupForm.mode,
        member_ids: groupForm.member_ids,
        host_agent_id: groupForm.mode === 'consult' ? groupForm.host_agent_id : null,
        rounds_per_turn: groupForm.mode === 'brainstorm' ? groupForm.rounds_per_turn : undefined,
      })
      ElMessage.success('群聊已更新')
      emit('updated')
    } else {
      const detail = await agentGroupApi.createGroup({
        name: groupForm.name,
        description: groupForm.description || undefined,
        mode: groupForm.mode,
        member_ids: groupForm.member_ids,
        host_agent_id: groupForm.mode === 'consult' ? groupForm.host_agent_id : null,
        rounds_per_turn: groupForm.mode === 'brainstorm' ? groupForm.rounds_per_turn : undefined,
      })
      ElMessage.success('群聊已创建')
      // 建完即进群（与单聊「创建后进对话」同体验）
      router.push({ name: 'WorkspaceGroupChat', params: { groupId: detail.id } })
    }
    await groupStore.fetchGroups()
    emit('update:modelValue', false)
  } catch {
    // Error already shown
  } finally {
    submitLoading.value = false
  }
}
</script>

<style>
/* append-to-body 弹窗内专属样式（全局）：模式 radio 卡片 + 轮数提示 */
/* 模式是群的核心语义，radio 卡片占视觉权重（选中态 primary-muted 底 + primary 边） */
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
