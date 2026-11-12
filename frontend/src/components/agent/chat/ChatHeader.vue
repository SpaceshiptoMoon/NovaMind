<template>
  <header class="chat-header" :class="{ 'is-welcome': isWelcomeMode }">
    <div class="header-left">
      <div v-if="!isWelcomeMode" class="header-agent-badge">
        <div class="badge-avatar">{{ agentName.charAt(0) }}</div>
        <span class="header-title">{{ agentName }}</span>
      </div>
      <!-- 对话/轨迹互斥切换 + 工作模式入口：轨迹保持全屏视图（列表+内置详情栏） -->
      <div v-if="!isWelcomeMode" class="header-tabs" role="tablist">
        <button
          class="view-pill"
          :class="{ active: viewMode === 'chat' }"
          role="tab"
          :aria-selected="viewMode === 'chat'"
          @click="emit('update:viewMode', 'chat')"
        >
          对话
        </button>
        <button
          class="view-pill"
          :class="{ active: viewMode === 'trajectory' }"
          role="tab"
          :aria-selected="viewMode === 'trajectory'"
          @click="emit('update:viewMode', 'trajectory')"
        >
          <el-icon :size="12"><Clock /></el-icon>
          轨迹
        </button>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
/**
 * 单聊对话页浮动头部：agent 徽标 + 「对话/轨迹」互斥切换。
 *
 * 纯展示件：视图模式经 v-model:viewMode 托管。工作目录绑定入口不在头部
 * （由会话中心「本地项目」分类的新建流程与右面板目录视图承担）。
 */
import { Clock } from '@element-plus/icons-vue'

defineProps<{
  agentName: string
  isWelcomeMode: boolean
  viewMode: 'chat' | 'trajectory'
}>()

const emit = defineEmits<{
  (e: 'update:viewMode', v: 'chat' | 'trajectory'): void
}>()
</script>

<style scoped>
.chat-header {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  z-index: 3;
  height: 48px;
  display: flex;
  align-items: center;
  padding: 0 var(--space-5);
  background: var(--color-bg-header);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: var(--shadow-xs);
  transition: all var(--transition-base);
}

.chat-header.is-welcome {
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  box-shadow: none;
}

.header-agent-badge {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.header-left {
  display: flex;
  align-items: center;
  min-width: 0;
}

.badge-avatar {
  width: 24px;
  height: 24px;
  border-radius: var(--radius-md);
  background: var(--color-primary-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: var(--weight-bold);
  color: var(--color-primary);
  flex-shrink: 0;
}

.header-title {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 视图切换组（对话/轨迹）：分段控件，与左侧助手徽标分组留白 */
.header-tabs {
  display: flex;
  gap: 2px;
  margin-left: var(--space-4);
  padding: 2px;
  background: var(--color-bg-hover);
  border-radius: var(--radius-full);
}

.view-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 12px;
  border: none;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
}

.view-pill:hover {
  color: var(--color-text);
}

.view-pill.active {
  background: var(--color-bg-card);
  box-shadow: var(--shadow-xs);
  color: var(--color-text);
  font-weight: var(--weight-medium);
}
</style>
