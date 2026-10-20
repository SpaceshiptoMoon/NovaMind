<template>
  <div class="group-workspace-view">
    <div class="placeholder-inner">
      <div class="placeholder-icon">
        <NavIcon name="group" :size="36" />
      </div>
      <h2 class="placeholder-title">群聊</h2>
      <p class="placeholder-desc">把多个智能体拉进一个群，从左侧列表选择群聊，或创建一个新的群聊</p>
      <button class="placeholder-action" @click="openCreate">
        <el-icon :size="14"><Plus /></el-icon>
        创建群聊
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 群聊空态占位页（/home/workspace/groups）
 *
 * 对应路由 WorkspaceGroups，未选中群时展示引导占位；群列表由 WorkspaceLayout
 * 侧栏承载，建群弹窗逻辑收编在布局层，此处经 inject 调用。
 */
import { inject } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import NavIcon from '@/components/common/NavIcon.vue'

// 建群弹窗逻辑收编在 WorkspaceLayout，经 inject 调用
const openGroupDialog = inject<() => void>('openGroupDialog', () => {})

function openCreate() {
  openGroupDialog()
}
</script>

<style scoped>
.group-workspace-view {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg);
  overflow: hidden;
}

.placeholder-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  max-width: 420px;
  padding: var(--space-6);
}

.placeholder-icon {
  width: 72px;
  height: 72px;
  border-radius: var(--radius-xl);
  background: var(--color-bg-hover);
  color: var(--color-text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-6);
  box-shadow: var(--shadow-md);
}

.placeholder-title {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin-bottom: var(--space-3);
}

.placeholder-desc {
  font-size: var(--text-base);
  color: var(--color-text-muted);
  text-align: center;
  margin-bottom: var(--space-6);
  line-height: var(--leading-relaxed);
}

.placeholder-action {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5);
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-btn-primary);
  color: var(--color-btn-primary-text);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-base);
}

.placeholder-action:hover {
  background: var(--color-btn-primary-hover);
}
</style>
