<template>
  <div class="auth-layout">
    <div class="auth-container">
      <div v-if="showHeader" class="auth-header">
        <div class="auth-logo">
          <UnicornIcon :size="72" />
        </div>
        <h1 class="auth-title"><span>NovaMind</span></h1>
        <p class="auth-subtitle">智能知识管理平台</p>
      </div>
      <div class="auth-content" :class="{ 'auth-content--minimal': !showHeader }">
        <router-view />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import UnicornIcon from '@/components/common/UnicornIcon.vue'

const route = useRoute()

// 忘记密码 / 重置密码等页面隐藏 header，使用紧凑卡片
const showHeader = computed(() => {
  const minimalRoutes = ['/forgot-password', '/reset-password']
  return !minimalRoutes.includes(route.path)
})
</script>

<style scoped>
.auth-layout {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(160deg, var(--color-bg) 0%, var(--color-bg-card-elevated) 50%, var(--color-bg) 100%);
  padding: var(--space-6);
}

.auth-container {
  width: 100%;
  max-width: 400px;
}

.auth-header {
  text-align: center;
  margin-bottom: var(--space-8);
}

.auth-logo {
  display: flex;
  justify-content: center;
  margin-bottom: var(--space-4);
}

.auth-title {
  font-family: var(--font-display);
  font-size: var(--text-3xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin: 0 0 var(--space-2) 0;
  letter-spacing: var(--tracking-tight);
}

.auth-title span {
  background: linear-gradient(135deg, var(--color-gradient-start), var(--color-gradient-end));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.auth-subtitle {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin: 0;
}

.auth-content {
  background: var(--color-bg-card);
  border-radius: var(--radius-xl);
  padding: var(--space-8);
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--color-border-light);
}

.auth-content--minimal {
  padding: var(--space-6);
  box-shadow: none;
}
</style>
