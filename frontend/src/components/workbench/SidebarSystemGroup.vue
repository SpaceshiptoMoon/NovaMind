<template>
  <div class="system-group">
    <router-link
      v-for="item in items"
      :key="item.key"
      :to="item.to"
      class="system-item"
      :class="{ active: isActive(item) }"
    >
      <el-icon :size="14"><component :is="item.icon" /></el-icon>
      <span class="item-text">{{ item.label }}</span>
    </router-link>
  </div>
</template>

<script setup lang="ts">
/**
 * 系统菜单项组（沉底系统行的弹层内容）：模型配置 / API 密钥 /（权限）用户·角色管理。
 *
 * 权限过滤与原 AppHeader 系统下拉同口径（admin 短路全过）；active 沿用
 * 登记簿墨线语法（3px 左缘线 + primary 色），路由前缀判定。
 */
import { computed, type Component } from 'vue'
import { useRoute } from 'vue-router'
import { Cpu, Key, User, UserFilled } from '@element-plus/icons-vue'
import { usePermissionStore } from '@/stores/permission'

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
/* 弹层内容：无分隔线、无组标签——触发行已表明「系统」语境 */
.system-group {
  display: flex;
  flex-direction: column;
  padding: var(--space-1) 0;
}

.system-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 32px;
  padding: 0 var(--space-3);
  color: var(--color-text-secondary);
  text-decoration: none;
  border-radius: var(--radius-md);
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

/* 字形列统一 18px 宽：与 KB 行/系统行的文字起点同一竖线 */
.system-item .el-icon {
  flex-shrink: 0;
  width: 18px;
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
