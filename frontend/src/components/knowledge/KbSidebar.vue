<template>
  <nav class="kb-sidebar">
    <router-link
      v-for="item in navItems"
      :key="item.route"
      :to="item.to"
      class="sidebar-item"
      :class="{ active: item.active }"
    >
      <el-icon class="sidebar-icon"><component :is="item.icon" /></el-icon>
      <span class="sidebar-label">{{ item.label }}</span>
    </router-link>
    <slot name="bottom" />
  </nav>
</template>

<script setup lang="ts">
import type { KbNavItem } from './navigation'

defineProps<{
  navItems: KbNavItem[]
}>()
</script>

<style scoped>
.kb-sidebar {
  width: 220px;
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
  color: var(--color-text-primary);
  background: var(--color-bg-hover);
}

.sidebar-item.active {
  color: var(--color-primary);
  background: var(--el-color-primary-light-9);
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

.sidebar-icon {
  font-size: var(--text-base);
  flex-shrink: 0;
}

.sidebar-label {
  white-space: nowrap;
}
</style>
