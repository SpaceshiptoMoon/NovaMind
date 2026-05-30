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
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessageBox, ElMessage } from 'element-plus'
import {
  User,
  SwitchButton,
  Cpu,
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import UnicornIcon from '@/components/common/UnicornIcon.vue'
import NavIcon from '@/components/common/NavIcon.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

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
</style>
