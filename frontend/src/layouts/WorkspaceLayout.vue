<template>
  <div class="workspace-layout">
    <a href="#workspace-main" class="skip-link">跳到主内容</a>

    <!-- 顶栏：全局导航 + 全局项 -->
    <AppHeader />

    <!-- 主内容区（知识空间/首页/系统页共用；页内滚动由 is-page 承接） -->
    <div class="workspace-body">
      <main class="workspace-main" id="workspace-main" role="main">
        <div class="workspace-content is-page">
          <router-view v-slot="{ Component }">
            <transition name="fade" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 主布局：全宽顶栏 + 主内容区
 *
 * 工作台（agent 对话）已剥离，布局只剩顶栏与内容容器；skip-link 供键盘导航。
 */
import AppHeader from './AppHeader.vue'
</script>

<style scoped>
.workspace-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  min-height: 0;
  background: var(--color-bg);
  overflow: hidden;
  position: relative;
}

/* ========================================
   Body — 顶栏下方：主内容
   ======================================== */
.workspace-body {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
  position: relative;
}

/* ========================================
   Main Content
   ======================================== */
.workspace-main {
  flex: 1;
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: flex;
}

.workspace-content {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  /* 定位包含块必须闭合在本层：内层视图用 absolute+inset:0 铺满时
     以本层为定位祖先，避免越级命中 .workspace-main */
  position: relative;
}

/* 页面自管 padding，本层只负责页内滚动 */
.workspace-content.is-page {
  overflow-y: auto;
}

.fade-enter-active {
  transition:
    opacity var(--transition-base),
    transform var(--transition-base);
}

.fade-leave-active {
  transition: opacity var(--transition-fast);
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.fade-leave-to {
  opacity: 0;
}

/* Skip link */
.skip-link {
  position: absolute;
  top: -100%;
  left: var(--space-4);
  padding: var(--space-2) var(--space-4);
  background: var(--color-btn-primary);
  color: var(--color-btn-primary-text);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  z-index: var(--z-toast);
  text-decoration: none;
  transition: top var(--transition-fast);
}

.skip-link:focus {
  top: var(--space-2);
}
</style>
