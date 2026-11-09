<template>
  <!-- 极简页（广场已删）：主管理面在侧栏列表，此处承载「添加智能体」入口 -->
  <WorkspacePlaceholder
    icon="agents"
    title="智能体"
    description="从左侧列表选择智能体开始对话，或创建一个新的智能体"
    action-text="添加智能体"
    @action="openCreate"
  />
</template>

<script setup lang="ts">
/**
 * 智能体工作台空态页（/home/workspace/agents）
 *
 * 对应路由 WorkspaceAgents，未选中智能体时展示引导占位；主列表由 WorkspaceLayout 侧栏承载。
 * 创建弹窗逻辑收编在布局层，此处经 inject 调用。
 */
import { inject } from 'vue'
import WorkspacePlaceholder from '@/components/agent/chat/WorkspacePlaceholder.vue'
import type { Agent } from '@/api/types'

// 创建弹窗逻辑收编在 WorkspaceLayout，经 inject 调用
const openAgentDialog = inject<(agent?: Agent) => void>('openAgentDialog', () => {})

function openCreate() {
  openAgentDialog()
}
</script>
