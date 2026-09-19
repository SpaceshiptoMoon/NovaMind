<template>
  <div class="agent-workspace-view">
    <!-- 极简页（广场已删）：主管理面在侧栏列表，此处承载「添加智能体」入口 -->
    <div class="placeholder-inner">
      <div class="placeholder-icon">
        <NavIcon name="agents" :size="36" />
      </div>
      <h2 class="placeholder-title">智能体</h2>
      <p class="placeholder-desc">从左侧列表选择智能体开始对话，或创建一个新的智能体</p>
      <button class="placeholder-action" @click="openCreate">
        <el-icon :size="14"><Plus /></el-icon>
        添加智能体
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { inject } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import NavIcon from '@/components/common/NavIcon.vue'
import type { Agent } from '@/api/types'

// 创建弹窗逻辑收编在 WorkspaceLayout，经 inject 调用
const openAgentDialog = inject<(agent?: Agent) => void>('openAgentDialog', () => {})

function openCreate() {
  openAgentDialog()
}
</script>

<style scoped>
.agent-workspace-view {
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
  background: var(--color-primary-subtle);
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
  color: #ffffff;
  font-family: var(--font-body);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-base);
}

.placeholder-action:hover {
  background: var(--color-btn-primary-hover);
}
</style>
