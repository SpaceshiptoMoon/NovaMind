<template>
  <nav class="kb-sidebar">
    <router-link
      v-for="item in navItems"
      :key="item.route"
      :to="item.to"
      class="sidebar-item"
      :class="{ active: item.active }"
    >
      <span class="sidebar-label">{{ item.label }}</span>
      <span v-if="item.badge" class="sidebar-badge">{{ item.badge }}</span>
    </router-link>
    <slot name="bottom" />
  </nav>
</template>

<script setup lang="ts">
/** 知识库设置页左侧导航栏：渲染 navItems 路由项，底部留 bottom 插槽 */
import type { KbNavItem } from './navigation'

defineProps<{
  navItems: KbNavItem[]
}>()
</script>

<style scoped>
.kb-sidebar {
  width: 148px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-4) var(--space-3);
  border-right: 1px solid var(--color-border-light);
  background: var(--color-bg-sidebar);
}

.sidebar-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-3);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  text-decoration: none;
  transition: all 0.2s ease;
  cursor: pointer;
  position: relative;
}

.sidebar-item:hover {
  color: var(--color-text);
  background: var(--color-bg-hover);
}

.sidebar-item.active {
  color: var(--color-primary);
  background: var(--color-primary-subtle);
  font-weight: var(--weight-semibold);
}

.sidebar-item.active::before {
  content: '';
  position: absolute;
  left: -12px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 20px;
  background: var(--color-primary);
  border-radius: 0 3px 3px 0;
}

.sidebar-label {
  white-space: nowrap;
}

/* 导航徽标：黄点数字（待处理问题）/符号（生成中），跟随主题语义色 */
.sidebar-badge {
  margin-left: auto;
  padding: 0 6px;
  border-radius: 999px;
  font-size: var(--text-xs);
  line-height: 18px;
  background: var(--color-warning-subtle);
  color: var(--color-warning);
}
</style>
