<template>
  <div class="form-section">
    <div class="form-section-header">
      <h3 class="form-section-title">{{ title }}</h3>
      <p v-if="description" class="form-section-desc">{{ description }}</p>
    </div>
    <div class="form-section-body">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<style scoped>
.form-section {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
}

.form-section-header {
  margin-bottom: var(--space-5);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
}

.form-section-title {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  margin: 0 0 var(--space-1) 0;
}

.form-section-desc {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin: 0;
}

.form-section-body {
  /* content slot */
}
</style>
