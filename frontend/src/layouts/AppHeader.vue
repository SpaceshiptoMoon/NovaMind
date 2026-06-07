<template>
  <header class="app-header">
    <nav class="header-nav">
      <div class="brand" @click="router.push('/home')">
        <UnicornIcon :size="36" />
        <span class="brand-name">NovaMind</span>
      </div>
      <div class="nav-links">
        <span
          :class="['nav-item', { active: isNavActive('/home') }]"
          @click="router.push('/home')"
        >
          <NavIcon name="home" />
          首页
        </span>
        <span
          :class="['nav-item', { active: isNavActive('/home/spaces') }]"
          @click="router.push('/home/spaces')"
        >
          <NavIcon name="spaces" />
          知识空间
        </span>
        <span
          :class="['nav-item', { active: route.path.startsWith('/home/workspace') || isNavActive('/home/chat') || isNavActive('/home/agents') || route.path.startsWith('/home/research') }]"
          @click="router.push('/home/workspace')"
        >
          <NavIcon name="chat" />
          工作台
        </span>
        <span
          :class="['nav-item', { active: isNavActive('/home/apps') }]"
          @click="router.push('/home/apps')"
        >
          <NavIcon name="apps" />
          应用
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
                v-if="userStore.isAdmin"
                command="admin/users"
              >
                <el-icon><User /></el-icon>
                用户管理
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </nav>

    <div class="header-right">
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
import { useRouter, useRoute } from 'vue-router'
import { ElMessageBox, ElMessage } from 'element-plus'
import {
  User,
  SwitchButton,
  Cpu,
  Bell,
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { notificationApi } from '@/api/notification'
import type { Notification } from '@/api/types'
import UnicornIcon from '@/components/common/UnicornIcon.vue'
import NavIcon from '@/components/common/NavIcon.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

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

function isNavActive(path: string): boolean {
  if (path === '/home') return route.path === '/home'
  return route.path.startsWith(path)
}

const isSystemActive = computed(() => {
  return route.path.startsWith('/home/settings') || route.path.startsWith('/home/admin')
})

function handleNavCommand(path: string) {
  router.push(`/home/${path}`)
}

const handleCommand = async (command: string) => {
  switch (command) {
    case 'profile':
      router.push('/home/profile')
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
  background: var(--color-bg-header);
  backdrop-filter: blur(var(--blur-header));
  -webkit-backdrop-filter: blur(var(--blur-header));
  border-bottom: 1px solid var(--color-border-light);
  box-shadow: var(--shadow-xs);
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
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  border-radius: var(--radius-md);
  transition: color var(--transition-fast), background var(--transition-fast);
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  user-select: none;
  position: relative;
}

.nav-item:hover {
  color: var(--color-text);
  background: var(--color-bg-hover);
}

.nav-item.active {
  color: var(--color-primary);
  background: var(--color-primary-muted);
  font-weight: var(--weight-medium);
}

.header-right {
  display: flex;
  align-items: center;
}

.user-trigger {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.user-trigger:hover {
  background: var(--color-bg-hover);
}

.user-avatar {
  background: var(--color-primary);
  color: var(--color-user-bubble-text);
  font-size: var(--text-sm);
}

.user-name {
  font-size: var(--text-sm);
  color: var(--color-text);
  font-weight: var(--weight-medium);
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
  background: var(--color-primary-muted, rgba(64, 158, 255, 0.06));
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
</style>
