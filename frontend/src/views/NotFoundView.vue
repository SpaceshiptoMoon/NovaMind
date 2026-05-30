<template>
  <div class="not-found">
    <h1>404</h1>
    <p>页面未找到</p>
    <el-button type="primary" @click="router.push('/home')">返回首页</el-button>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<style scoped>
.not-found {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  text-align: center;
}

.not-found h1 {
  font-size: 7.5rem;
  margin: 0;
  color: var(--color-primary);
}

.not-found p {
  font-size: var(--text-2xl);
  color: var(--color-text-muted);
  margin: var(--space-5) 0 var(--space-8);
}
</style>
