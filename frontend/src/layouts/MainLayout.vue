<template>
  <div class="main-layout">
    <!-- Main Container -->
    <div class="main-container">
      <AppHeader />
      <main class="main-content" :class="{ 'workspace-mode': isInWorkspace }">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppHeader from './AppHeader.vue'

const route = useRoute()

const isInWorkspace = computed(() => route.path.startsWith('/home/workspace'))
</script>

<style scoped>
.main-layout {
  display: flex;
  min-height: 100vh;
}

.main-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.main-content {
  flex: 1;
  padding: var(--space-5);
  background: var(--color-bg);
  overflow-y: auto;
}

.main-content.workspace-mode {
  padding: 0;
  overflow: hidden;
}

.fade-enter-active {
  transition: opacity var(--transition-base), transform var(--transition-base);
}

.fade-leave-active {
  transition: opacity var(--transition-fast);
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(4px);
}

.fade-leave-to {
  opacity: 0;
}
</style>
