<template>
  <header class="app-header">
    <!-- 左区：空间切换器（原侧栏上移，内联 chip 形态）+ 分隔线 + 面包屑 +
         页头动作（如空间设置）。面包屑链路自 KB 级起——空间名由切换器承载 -->
    <div class="header-left">
      <SpaceSwitcher variant="header" />
      <template v-if="crumbStore.items.length > 0">
        <div class="header-divider" />
        <BreadcrumbNav
          :items="crumbStore.items"
          :back-label="crumbStore.back?.label"
          @back="handleCrumbBack"
          @navigate="(to: string) => router.push(to)"
        />
      </template>
      <button
        v-if="crumbStore.action"
        type="button"
        class="crumb-action"
        :title="crumbStore.action.label"
        :aria-label="crumbStore.action.label"
        @click="router.push(crumbStore.action.to)"
      >
        <el-icon :size="14"><component :is="crumbStore.action.icon" /></el-icon>
      </button>
    </div>

    <div class="header-right">
      <!-- 主题切换 -->
      <el-icon :size="20" class="theme-toggle" @click="toggleTheme">
        <Sunny v-if="theme === 'dark'" />
        <Moon v-else />
      </el-icon>

      <!-- 通知铃铛 -->
      <el-popover
        ref="notificationPopoverRef"
        placement="bottom-end"
        :width="360"
        trigger="click"
        @show="notifStore.loadRecent()"
      >
        <template #reference>
          <el-badge
            :value="notifStore.unreadCount"
            :hidden="notifStore.unreadCount === 0"
            :max="99"
            class="notification-badge"
          >
            <el-icon :size="20" class="notification-bell"><Bell /></el-icon>
          </el-badge>
        </template>
        <div class="notification-panel">
          <div class="notification-header">
            <span class="notification-title">通知</span>
            <el-button
              v-if="notifStore.unreadCount > 0"
              link
              type="primary"
              size="small"
              @click="notifStore.markAllRead()"
              >全部已读</el-button
            >
          </div>
          <div v-if="notifStore.items.length === 0" class="notification-empty">暂无通知</div>
          <div v-else class="notification-list">
            <div
              v-for="n in notifStore.items"
              :key="n.id"
              :class="['notification-item', { unread: !n.is_read }]"
              @click="handleNotificationClick(n)"
            >
              <div class="notification-item-title">{{ n.title }}</div>
              <div class="notification-item-content">{{ n.content }}</div>
              <div class="notification-item-time">{{ formatRelativeTime(n.created_at) }}</div>
            </div>
          </div>
          <div v-if="notifStore.items.length > 0" class="notification-footer">
            <el-button link type="primary" @click="handleViewAll">查看全部</el-button>
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
/**
 * 全局顶栏：空间切换器 + 面包屑（页面发布）+ 主题/通知/用户。
 *
 * 品牌与主导航已下沉到 WorkbenchSidebar（登记簿式工作台），系统管理入口
 * 在侧栏系统组；空间切换器自侧栏上移至左区首位（2026-11），全局检索入口
 * 在检索页——顶栏不再内嵌搜索。
 */
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { User, SwitchButton, Bell, Moon, Sunny } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useBreadcrumbStore } from '@/stores/breadcrumb'
import { useNotificationStore } from '@/stores/notification'
import { formatRelativeTime } from '@/utils/format'
import type { Notification } from '@/api/types'
import UnicornIcon from '@/components/common/UnicornIcon.vue'
import BreadcrumbNav from '@/components/common/BreadcrumbNav.vue'
import SpaceSwitcher from '@/components/workbench/SpaceSwitcher.vue'
import { useTheme } from '@/composables/useTheme'

const router = useRouter()
const userStore = useUserStore()
const { theme, toggleTheme } = useTheme()

// ==================== 面包屑位 ====================
const crumbStore = useBreadcrumbStore()

function handleCrumbBack() {
  if (crumbStore.back) void router.push(crumbStore.back.to)
}

// ==================== 通知相关（经 notifStore：WS 实时 + 30s 轮询兜底） ====================
const notifStore = useNotificationStore()

// 点击「查看全部」跳转后须显式收起面板：目标页已是通知列表，弹层停留只会双份并存
const notificationPopoverRef = ref<{ hide: () => void } | null>(null)

function handleViewAll() {
  notificationPopoverRef.value?.hide()
  router.push('/home/notifications')
}

// 登录态驱动：登录后初始化订阅与轮询，登出后清理
watch(
  () => userStore.isLoggedIn,
  (loggedIn) => {
    if (loggedIn) {
      notifStore.init()
    } else {
      notifStore.stop()
    }
  },
  { immediate: true },
)

function handleNotificationClick(n: Notification) {
  if (!n.is_read) {
    notifStore.markRead(n.id)
  }
  if (n.link) {
    router.push(n.link)
  }
}

const handleCommand = async (command: string) => {
  if (command === 'profile') {
    router.push('/home/profile')
    return
  }
  if (command === 'logout') {
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
  }
}
</script>

<style scoped>
.app-header {
  height: var(--header-height);
  /* 左列面包屑（页面发布）+ 右列全局操作，空面包屑时右列仍靠右 */
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 var(--space-6);
  /* 顶栏磨砂玻璃（悬浮于内容之上，滚动时透出下方内容） */
  background: var(--glass-bg-strong);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(1.35);
  backdrop-filter: blur(var(--glass-blur)) saturate(1.35);
  border-bottom: 1px solid var(--glass-border-hairline);
  box-shadow: var(--glass-highlight);
  position: relative;
  z-index: var(--z-sticky);
}

@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .app-header { background: var(--color-bg-card); }
}

/* ==================== Header Left（左区：切换器 + 面包屑列） ==================== */
.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
  min-width: 0;
  /* 窄屏放不下时整体截断（crumb-item 自带 ellipsis） */
  overflow: hidden;
}

/* 切换器与面包屑之间的细分隔线 */
.header-divider {
  width: 1px;
  height: 20px;
  flex-shrink: 0;
  background: var(--color-border);
  margin: 0 var(--space-1);
}

/* 面包屑尾随动作（如空间设置）：28px 圆形操作位，与 crumb-back 同形态 */
.crumb-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border: none;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast),
    box-shadow var(--transition-base);
}

.crumb-action:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
  box-shadow: var(--shadow-xs);
}

/* ==================== Header Right（右列） ==================== */
.header-right {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-1);
  /* 顶栏右侧操作键统一 hover 浮起阴影（就近定义便于整体调档） */
  --header-hover-shadow: 0 2px 8px rgba(0, 0, 0, 0.12), 0 1px 2px rgba(0, 0, 0, 0.08);
}

/* ==================== 主题切换 ==================== */
.theme-toggle {
  color: var(--color-text-secondary);
  cursor: pointer;
  /* 与折叠按钮/铃铛同规格 32px 圆形操作位 */
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    color var(--transition-fast),
    background var(--transition-fast),
    box-shadow var(--transition-base);
}

.theme-toggle:hover {
  color: var(--color-text);
  background: var(--color-bg-hover);
  box-shadow: var(--header-hover-shadow);
}

/* ==================== 通知铃铛 ==================== */
.notification-badge {
  cursor: pointer;
}

.notification-bell {
  color: var(--color-text-secondary);
  cursor: pointer;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    color var(--transition-fast),
    background var(--transition-fast),
    box-shadow var(--transition-base);
}

.notification-bell:hover {
  color: var(--color-text);
  background: var(--color-bg-hover);
  box-shadow: var(--header-hover-shadow);
}

.notification-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.notification-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.notification-title {
  font-size: var(--text-base);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.notification-empty {
  padding: var(--space-6) 0;
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-faint);
}

.notification-list {
  max-height: 360px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.notification-item {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
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
}

.notification-item-content {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-top: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.notification-item-time {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
  margin-top: 4px;
}

.notification-footer {
  display: flex;
  justify-content: center;
  padding-top: var(--space-1);
  border-top: 1px solid var(--color-border-light);
}

/* ==================== 用户菜单 ==================== */
.user-trigger {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
  padding: var(--space-1);
  border-radius: var(--radius-full);
  transition:
    background var(--transition-fast),
    box-shadow var(--transition-base);
}

.user-trigger:hover {
  background: var(--color-bg-hover);
  box-shadow: var(--header-hover-shadow);
}

.user-avatar {
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}

.user-name {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

/* ==================== Responsive ==================== */
@media (max-width: 768px) {
  .app-header {
    padding: 0 var(--space-3);
  }

  .user-name {
    display: none;
  }
}

@media (max-width: 420px) {
  .app-header {
    gap: var(--space-1);
    padding: 0 var(--space-2);
  }
}
</style>
