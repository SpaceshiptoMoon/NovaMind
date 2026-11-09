<template>
  <div class="workspace-placeholder">
    <div class="placeholder-inner">
      <div class="placeholder-icon">
        <NavIcon :name="icon" :size="36" />
      </div>
      <h2 class="placeholder-title">{{ title }}</h2>
      <p class="placeholder-desc">{{ description }}</p>
      <button class="placeholder-action" @click="emit('action')">
        <el-icon :size="14"><Plus /></el-icon>
        {{ actionText }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 工作台空态占位（智能体页/群聊页共用）：图标 + 标题 + 引导文案 + 创建动作。
 *
 * 纯展示件；创建动作上抛（智能体建/编弹窗在 WorkspaceLayout，经 inject 调用）。
 */
import { Plus } from '@element-plus/icons-vue'
import NavIcon from '@/components/common/NavIcon.vue'

defineProps<{
  icon: 'agents' | 'group'
  title: string
  description: string
  actionText: string
}>()

const emit = defineEmits<{ (e: 'action'): void }>()
</script>

<style scoped>
.workspace-placeholder {
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
