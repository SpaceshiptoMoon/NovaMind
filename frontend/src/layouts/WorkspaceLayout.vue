<template>
  <div class="workspace-layout">
    <a href="#workspace-main" class="skip-link">跳到主内容</a>

    <!-- 登记簿式全局侧栏（全高）：品牌/空间切换/KB 登记/系统区 -->
    <WorkbenchSidebar />

    <!-- 右列：瘦身顶栏（面包屑 + 全局项）+ 主内容区 -->
    <div class="workspace-right">
      <AppHeader />

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
  </div>
</template>

<script setup lang="ts">
/**
 * 主布局：全局侧栏 + 右列（顶栏 + 主内容区）。
 *
 * 产品已收敛为知识空间单模块——侧栏即工作台（品牌/空间切换器/KB 登记
 * 册/系统区），顶栏承载页面面包屑（breadcrumbStore）与主题/通知/用户；skip-link 供键盘导航。
 */
import AppHeader from './AppHeader.vue'
import { WorkbenchSidebar } from '@/components/workbench'
</script>

<style scoped>
.workspace-layout {
  display: flex;
  height: 100vh;
  min-height: 0;
  background: var(--color-bg);
  overflow: hidden;
  position: relative;
}

.workspace-right {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
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
