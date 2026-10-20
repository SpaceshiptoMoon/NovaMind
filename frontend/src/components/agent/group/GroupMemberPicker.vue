<template>
  <div class="member-picker">
    <div class="picker-toolbar">
      <el-checkbox
        :model-value="allSelected"
        :indeterminate="indeterminate"
        :disabled="disabled"
        @change="toggleAll"
        >全选</el-checkbox
      >
      <span class="picker-count">已选 {{ modelValue.length }}（至少 2 人）</span>
    </div>
    <el-checkbox-group :model-value="modelValue" :disabled="disabled" @update:model-value="onChange">
      <div class="picker-grid">
        <el-checkbox v-for="agent in agents" :key="agent.id" :value="agent.id" class="picker-item">
          <span class="picker-name">{{ agent.name }}</span>
          <span v-if="agent.id === hostAgentId" class="picker-host-tag">主持人</span>
        </el-checkbox>
      </div>
    </el-checkbox-group>
    <div v-if="agents.length === 0" class="picker-empty">暂无可用智能体，请先创建智能体</div>
  </div>
</template>

<script setup lang="ts">
/**
 * 建群/编辑群弹窗的成员多选：现有 agents 的 checkbox 网格 + 主持人标记
 *
 * 选中 ≥2 才可建群（后端兜底 + 弹窗提交前校验）；consult 模式下主持人
 * 下拉在弹窗层（选项=已选成员），此处只在列表项上标记主持人徽标。
 */
import { computed } from 'vue'
import type { Agent } from '@/api/types'

const props = defineProps<{
  modelValue: number[]
  agents: Agent[]
  hostAgentId: number | null
  disabled?: boolean
}>()

const emit = defineEmits<{ 'update:modelValue': [ids: number[]] }>()

const allSelected = computed(
  () => props.agents.length > 0 && props.modelValue.length === props.agents.length,
)
const indeterminate = computed(
  () => props.modelValue.length > 0 && props.modelValue.length < props.agents.length,
)

function toggleAll(checked: boolean | string | number) {
  emit('update:modelValue', checked ? props.agents.map((a) => a.id) : [])
}

function onChange(ids: (number | string | boolean)[] | number[] | string[] | boolean[]) {
  emit('update:modelValue', (ids as number[]) ?? [])
}
</script>

<style scoped>
.member-picker {
  width: 100%;
  min-width: 0;
}

.picker-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: 4px;
}

.picker-count {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}

/* checkbox 网格：窄容器两列，极窄一列（抗压缩降级） */
.picker-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 var(--space-3);
  max-height: 168px;
  overflow-y: auto;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  padding: 6px 12px;
}

.picker-item {
  margin-right: 0;
  height: 28px;
  min-width: 0;
}

.picker-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
  display: inline-block;
  vertical-align: middle;
}

.picker-host-tag {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  border-radius: var(--radius-full);
  background: var(--color-primary-muted);
  color: var(--color-primary);
  font-size: 10px;
  white-space: nowrap;
  flex-shrink: 0;
}

.picker-empty {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  border: 1px dashed var(--color-border-light);
  border-radius: var(--radius-md);
  padding: 10px;
  text-align: center;
}

@media (max-width: 480px) {
  .picker-grid {
    grid-template-columns: 1fr;
  }
}
</style>
