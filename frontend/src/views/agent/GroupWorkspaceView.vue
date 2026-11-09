<template>
  <WorkspacePlaceholder
    icon="group"
    title="群聊"
    description="把多个智能体拉进一个群，从左侧列表选择群聊，或创建一个新的群聊"
    action-text="创建群聊"
    @action="openCreate"
  />
</template>

<script setup lang="ts">
/**
 * 群聊空态占位页（/home/workspace/groups）
 *
 * 对应路由 WorkspaceGroups，未选中群时展示引导占位；群列表由 WorkspaceLayout
 * 侧栏承载，建群弹窗逻辑收编在布局层，此处经 inject 调用。
 */
import { inject } from 'vue'
import WorkspacePlaceholder from '@/components/agent/chat/WorkspacePlaceholder.vue'

// 建群弹窗逻辑收编在 WorkspaceLayout，经 inject 调用
const openGroupDialog = inject<() => void>('openGroupDialog', () => {})

function openCreate() {
  openGroupDialog()
}
</script>
