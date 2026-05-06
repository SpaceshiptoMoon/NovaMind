<template>
  <div class="auth-layout">
    <div class="auth-container">
      <div class="auth-header">
        <div class="auth-logo">
          <UnicornIcon :size="72" />
        </div>
        <h1 class="auth-title"><span>Intelligent</span></h1>
        <p class="auth-subtitle">智能知识管理平台</p>
      </div>
      <div class="auth-content">
        <router-view />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import UnicornIcon from '@/components/common/UnicornIcon.vue'
</script>

<style scoped>
.auth-layout {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(160deg, #F5F3F0 0%, #E8ECF4 50%, #FAF0ED 100%);
  padding: 24px;
}

.auth-container {
  width: 100%;
  max-width: 400px;
}

.auth-header {
  text-align: center;
  margin-bottom: 32px;
}

.auth-logo {
  display: flex;
  justify-content: center;
  margin-bottom: 16px;
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
  background: linear-gradient(135deg, #4285F4, #EA4335);
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
</style>
