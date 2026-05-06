<template>
  <div class="stat-card" :style="accentStyle">
    <div v-if="icon" class="stat-icon" :style="{ color: color || 'var(--color-primary)' }">
      <el-icon :size="20"><component :is="icon" /></el-icon>
    </div>
    <div class="stat-content">
      <span class="stat-value">{{ value }}</span>
      <span class="stat-label">{{ label }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  value: string | number
  label: string
  icon?: any
  color?: string
}>(), {
  color: '',
})

const accentStyle = computed(() => {
  if (!props.color) return {}
  return {
    borderLeft: `3px solid ${props.color}`,
  }
})
</script>

<style scoped>
.stat-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  background: var(--color-bg-card-elevated);
  border-radius: var(--radius-lg);
  border-left: 3px solid transparent;
}

.stat-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  flex-shrink: 0;
}

.stat-content {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  line-height: 1.2;
}

.stat-label {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-top: 2px;
}
</style>
