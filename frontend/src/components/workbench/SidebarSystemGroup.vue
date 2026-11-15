<template>
  <div class="system-group">
    <div class="group-label">系统</div>
    <router-link
      v-for="item in items"
      :key="item.key"
      :to="item.to"
      class="system-item"
      :class="{ active: isActive(item) }"
      :title="collapsed ? item.label : undefined"
    >
      <el-icon :size="14"><component :is="item.icon" /></el-icon>
      <span v-if="!collapsed" class="item-text">{{ item.label }}</span>
    </router-link>
  </div>
</template>

<script setup lang="ts">
/**
 * 侧栏系统组：模型配置 / API 密钥 /（权限）用户·角色管理。
 *
 * 权限过滤与 AppHeader 原系统下拉同口径（admin 短路全过）；active 沿用
 * 登记簿墨线语法（3px 左缘线 + primary 色），路由前缀判定。
 */
import { computed, type Component } from 'vue'
import { useRoute } from 'vue-router'
import { Cpu, Key, User, UserFilled } from '@element-plus/icons-vue'
import { usePermissionStore } from '@/stores/permission'

defineProps<{ collapsed?: boolean }>()

const route = useRoute()
const permStore = usePermissionStore()

interface SystemItem {
  key: string
  label: string
  to: string
  icon: Component
  prefix: string
  permission?: string
}

const allItems: SystemItem[] = [
  { key: 'models', label: '模型配置', to: '/home/settings/models', icon: Cpu, prefix: '/home/settings/models' },
  { key: 'api-keys', label: 'API 密钥', to: '/home/settings/api-keys', icon: Key, prefix: '/home/settings/api-keys' },
  {
    key: 'users',
    label: '用户管理',
    to: '/home/admin/users',
    icon: User,
    prefix: '/home/admin/users',
    permission: 'user.manage',
  },
  {
    key: 'roles',
    label: '角色管理',
    to: '/home/admin/roles',
    icon: UserFilled,
    prefix: '/home/admin/roles',
    permission: 'role.manage',
  },
]

const items = computed(() =>
  allItems.filter((item) => !item.permission || permStore.hasPermission(item.permission)),
)

function isActive(item: SystemItem): boolean {
  return route.path.startsWith(item.prefix)
}
</script>

<style scoped>
.system-group {
  border-top: 1px solid var(--color-border-light);
  padding: var(--space-2) 0 var(--space-1);
}

.group-label {
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

.system-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 30px;
  padding: 0 var(--space-3);
  color: var(--color-text-secondary);
  text-decoration: none;
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.system-item:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

/* 登记簿墨线：当前位置 = 3px 墨水左缘线（与 KbSidebar 同一语法），无底色 pill */
.system-item.active {
  color: var(--color-primary);
  font-weight: var(--weight-semibold);
}

.system-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--color-primary);
}

.item-text {
  font-size: var(--text-sm);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
