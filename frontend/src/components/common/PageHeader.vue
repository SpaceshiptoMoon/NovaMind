<template>
  <div class="page-header">
    <div class="page-header-left">
      <button v-if="showBack" class="back-btn" @click="handleBack">
        <el-icon><ArrowLeft /></el-icon>
        <span>返回</span>
      </button>
      <h2 v-if="title" class="page-title">{{ title }}</h2>
      <slot name="title-suffix" />
    </div>
    <div class="page-header-right">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ArrowLeft } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

const props = withDefaults(defineProps<{
  title?: string
  showBack?: boolean
  backTo?: string
}>(), {
  title: '',
  showBack: false,
  backTo: '',
})

const router = useRouter()

function handleBack() {
  if (props.backTo) {
    router.push(props.backTo)
  } else {
    router.back()
  }
}
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-6);
  padding-bottom: var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
}

.page-header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.page-header-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: var(--text-sm);
  padding: 6px 10px;
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
  font-family: var(--font-body);
}

.back-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.page-title {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  margin: 0;
}
</style>
