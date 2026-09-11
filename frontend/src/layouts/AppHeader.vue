<template>
  <header class="app-header">
    <nav class="header-nav">
      <div class="brand" @click="router.push('/home')">
        <UnicornIcon :size="36" />
        <span class="brand-name">NovaMind</span>
      </div>
      <div class="nav-links">
        <span
          v-for="item in navItems"
          :key="item.key"
          :class="['nav-item', { active: activeNav === item.key }]"
          @click="router.push(item.to)"
        >
          <NavIcon :name="item.icon" />
          {{ item.label }}
        </span>
        <el-dropdown trigger="hover" @command="handleNavCommand">
          <span :class="['nav-item', { active: isSystemActive }]">
            <NavIcon name="settings" />
            系统
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="settings/models">
                <el-icon><Cpu /></el-icon>
                模型配置
              </el-dropdown-item>
              <el-dropdown-item
                v-if="permStore.hasPermission('user.manage')"
                command="admin/users"
              >
                <el-icon><User /></el-icon>
                用户管理
              </el-dropdown-item>
              <el-dropdown-item
                v-if="permStore.hasPermission('role.manage')"
                command="admin/roles"
              >
                <el-icon><UserFilled /></el-icon>
                角色管理
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </nav>

    <div class="header-right">
      <!-- 侧栏折叠切换（仅工作台路由传入 sidebar-collapsed 时显示） -->
      <button
        v-if="sidebarCollapsed !== undefined"
        class="sidebar-collapse-btn"
        :aria-label="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
        :aria-expanded="!sidebarCollapsed"
        @click="emit('toggle-sidebar')"
      >
        <el-icon :size="16"><DArrowLeft v-if="!sidebarCollapsed" /><DArrowRight v-else /></el-icon>
      </button>

      <!-- 主题切换 -->
      <el-icon :size="20" class="theme-toggle" @click="toggleTheme">
        <Sunny v-if="theme === 'dark'" />
        <Moon v-else />
      </el-icon>

      <!-- 通知铃铛 -->
      <el-popover
        placement="bottom-end"
        :width="360"
        trigger="click"
        @show="loadNotifications"
      >
        <template #reference>
          <el-badge :value="unreadCount" :hidden="unreadCount === 0" :max="99" class="notification-badge">
            <el-icon :size="20" class="notification-bell"><Bell /></el-icon>
          </el-badge>
        </template>
        <div class="notification-panel">
          <div class="notification-header">
            <span class="notification-title">通知</span>
            <el-button v-if="unreadCount > 0" link type="primary" size="small" @click="handleMarkAllRead">全部已读</el-button>
          </div>
          <div v-if="notifications.length === 0" class="notification-empty">暂无通知</div>
          <div v-else class="notification-list">
            <div
              v-for="n in notifications"
              :key="n.id"
              :class="['notification-item', { unread: !n.is_read }]"
              @click="handleNotificationClick(n)"
            >
              <div class="notification-item-title">{{ n.title }}</div>
              <div class="notification-item-content">{{ n.content }}</div>
              <div class="notification-item-time">{{ formatTime(n.created_at) }}</div>
            </div>
          </div>
          <div v-if="notifications.length > 0" class="notification-footer">
            <el-button link type="primary" @click="router.push('/home/notifications')">查看全部</el-button>
          </div>
        </div>
      </el-popover>

      <el-dropdown trigger="click" @command="handleCommand">
        <div class="user-trigger">
          <el-avatar :size="32" class="user-avatar">
            <UnicornIcon :size="20" />
          </el-avatar>
          <span class="user-name">{{ userStore.user?.username || '用户' }}</span>
        </div>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="profile">
              <el-icon><User /></el-icon>
              个人信息
            </el-dropdown-item>
            <el-dropdown-item command="settings/models">
              <el-icon><Cpu /></el-icon>
              模型配置
            </el-dropdown-item>
            <el-dropdown-item
              v-if="permStore.hasPermission('user.manage')"
              command="admin/users"
            >
              <el-icon><User /></el-icon>
              用户管理
            </el-dropdown-item>
            <el-dropdown-item
              v-if="permStore.hasPermission('role.manage')"
              command="admin/roles"
            >
              <el-icon><UserFilled /></el-icon>
              角色管理
            </el-dropdown-item>
            <el-dropdown-item divided command="logout">
              <el-icon><SwitchButton /></el-icon>
              退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox, ElMessage } from 'element-plus'
import {
  User,
  SwitchButton,
  Cpu,
  Bell,
  UserFilled,
  Moon,
  Sunny,
  DArrowLeft,
  DArrowRight,
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { usePermissionStore } from '@/stores/permission'
import { notificationApi } from '@/api/notification'
import type { Notification } from '@/api/types'
import UnicornIcon from '@/components/common/UnicornIcon.vue'
import NavIcon from '@/components/common/NavIcon.vue'
import { useTheme } from '@/composables/useTheme'

const router = useRouter()
const userStore = useUserStore()
const permStore = usePermissionStore()
const { theme, toggleTheme } = useTheme()

// 工作台频道分段与侧栏折叠（父级 WorkspaceLayout 传入；channels 空 = 非工作台路由）
defineProps<{
  workspaceChannels?: Array<{ key: string; label: string; icon: string }>
  activeChannel?: string
  sidebarCollapsed?: boolean
}>()

const emit = defineEmits<{
  'channel-select': [key: string]
  'toggle-sidebar': []
}>()

// ==================== 顶部导航（全局） ====================
const allNavItems = [
  { key: 'home', label: '首页', icon: 'home', to: '/home', app: null },
  { key: 'spaces', label: '知识空间', icon: 'spaces', to: '/home/spaces', app: null },
  { key: 'workspace', label: '工作台', icon: 'chat', to: '/home/workspace', app: null },
  { key: 'apps', label: '应用', icon: 'apps', to: '/home/apps', app: 'app' },
] as const

const navItems = computed(() =>
  allNavItems.filter((item) => item.app === null || permStore.hasApp(item.app)),
)

const activeNav = computed(() => {
  const path = router.currentRoute.value.path
  if (path.startsWith('/home/workspace')) return 'workspace'
  if (path.startsWith('/home/spaces')) return 'spaces'
  if (path.startsWith('/home/apps')) return 'apps'
  if (path === '/home') return 'home'
  return ''
})

const isSystemActive = computed(() => {
  const path = router.currentRoute.value.path
  return path.startsWith('/home/settings') || path.startsWith('/home/admin')
})

function handleNavCommand(path: string) {
  router.push(`/home/${path}`)
}

// ==================== 通知相关 ====================
const unreadCount = ref(0)
const notifications = ref<Notification[]>([])
let pollTimer: ReturnType<typeof setInterval> | null = null

async function fetchUnreadCount() {
  try {
    const res = await notificationApi.getUnreadCount()
    unreadCount.value = res.unread_count
  } catch {
    // 静默处理
  }
}

async function loadNotifications() {
  try {
    const res = await notificationApi.getNotifications({ limit: 5, unread_only: false })
    notifications.value = res.items
    unreadCount.value = res.unread_count
  } catch {
    // 静默处理
  }
}

async function handleMarkAllRead() {
  try {
    await notificationApi.markAllRead()
    await loadNotifications()
  } catch {
    ElMessage.error('操作失败')
  }
}

async function handleNotificationClick(n: Notification) {
  if (!n.is_read) {
    try {
      await notificationApi.markRead(n.id)
      n.is_read = true
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    } catch {
      // 静默处理
    }
  }
  if (n.link) {
    router.push(n.link)
  }
}

function formatTime(dateStr: string): string {
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}天前`
  return d.toLocaleDateString()
}

onMounted(() => {
  fetchUnreadCount()
  pollTimer = setInterval(fetchUnreadCount, 30000)
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})

const handleCommand = async (command: string) => {
  switch (command) {
    case 'profile':
      router.push('/home/profile')
      break
    case 'settings/models':
      router.push('/home/settings/models')
      break
    case 'admin/users':
      router.push('/home/admin/users')
      break
    case 'admin/roles':
      router.push('/home/admin/roles')
      break
    case 'logout':
      try {
        await ElMessageBox.confirm('确定要退出登录吗？', '提示', {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'warning',
        })
        userStore.logout()
        router.push('/login')
      } catch {
        // 用户取消
      }
      break
  }
}
</script>

<style scoped>
.app-header {
  height: var(--header-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-6);
  background: var(--color-bg-card);
  border-bottom: 1px solid var(--color-border);
  position: relative;
  z-index: var(--z-sticky);
}

.header-nav {
  display: flex;
  align-items: center;
  gap: var(--space-6);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  cursor: pointer;
  user-select: none;
}

.brand-name {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  letter-spacing: var(--tracking-tight);
}

.nav-links {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.nav-item {
  position: relative;
  padding: var(--space-2) var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: color var(--transition-fast);
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  user-select: none;
  white-space: nowrap;
}

/* 米哈游招聘站语言：hover/active 底部短横线（从中间展开） */
.nav-item::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -2px;
  transform: translateX(-50%) scaleX(0);
  width: 24px;
  height: 2px;
  border-radius: var(--radius-full);
  background: var(--color-primary);
  transition: transform var(--transition-base);
}

.nav-item:hover {
  color: var(--color-text);
}

.nav-item:hover::after {
  transform: translateX(-50%) scaleX(1);
}

.nav-item.active {
  color: var(--color-text);
  font-weight: var(--weight-medium);
}

.nav-item.active::after {
  transform: translateX(-50%) scaleX(1);
}

/* ==================== 侧栏折叠按钮 ==================== */
.sidebar-collapse-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  margin-right: var(--space-2);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: color var(--transition-fast), background var(--transition-fast),
    border-color var(--transition-fast);
}

.sidebar-collapse-btn:hover {
  color: var(--color-text);
  background: var(--color-bg-hover);
  border-color: var(--color-border);
}

/* ==================== 主题切换 ==================== */
.theme-toggle {
  margin-right: var(--space-4);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: color var(--transition-fast);
  /* 米哈游语言：图标操作位胶囊化 hover（圆形浅底） */
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: color var(--transition-fast), background var(--transition-fast);
}

.theme-toggle:hover {
  color: var(--color-text);
  background: var(--color-bg-hover);
}

/* ==================== 通知铃铛 ==================== */
.notification-badge {
  margin-right: var(--space-4);
  cursor: pointer;
}

.notification-bell {
  color: var(--color-text-secondary);
  transition: color var(--transition-fast);
}

.notification-bell:hover {
  color: var(--color-text);
}

.notification-panel {
  margin: -12px;
}

.notification-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light);
}

.notification-title {
  font-size: var(--text-base);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.notification-empty {
  padding: 32px 16px;
  text-align: center;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

.notification-list {
  max-height: 360px;
  overflow-y: auto;
}

.notification-item {
  padding: 12px 16px;
  cursor: pointer;
  transition: background var(--transition-fast);
  border-bottom: 1px solid var(--color-border-lighter, #f5f5f5);
}

.notification-item:hover {
  background: var(--color-bg-hover);
}

.notification-item.unread {
  background: var(--color-primary-muted);
}

.notification-item-title {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  margin-bottom: 4px;
}

.notification-item-content {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.notification-item-time {
  font-size: var(--text-xs);
  color: var(--color-text-placeholder, #c0c4cc);
  margin-top: 4px;
}

.notification-footer {
  padding: 8px 16px;
  text-align: center;
  border-top: 1px solid var(--color-border-light);
}

/* ==================== 窄视口自适应（开发者工具/小窗） ==================== */
@media (max-width: 1200px) {
  .nav-item {
    padding: var(--space-2);
  }

}

@media (max-width: 992px) {
  .nav-links {
    gap: 0;
  }

  .nav-item span,
  .nav-item {
    font-size: var(--text-xs);
  }

  .header-nav {
    gap: var(--space-3);
  }
}

@media (max-width: 768px) {
  .app-header {
    padding: 0 var(--space-3);
  }

  .brand-name {
    display: none;
  }

  /* 极窄：导航文字隐藏只留图标 */
  .nav-item {
    padding: var(--space-2);
    font-size: 0;
    gap: 0;
  }

  .nav-item svg {
    width: 18px;
    height: 18px;
  }

  .theme-toggle,
  .notification-badge {
    margin-right: var(--space-2);
  }

  .user-trigger {
    gap: 0;
    padding: var(--space-2);
  }

  .user-name {
    display: none;
  }
}
</style>
