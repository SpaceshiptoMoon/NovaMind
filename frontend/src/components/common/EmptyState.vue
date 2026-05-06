<template>
  <div class="empty-state">
    <div class="empty-illustration">
      <!-- Variant-specific simple SVG illustrations -->
      <svg v-if="variant === 'search'" width="64" height="64" viewBox="0 0 64 64" fill="none">
        <circle cx="28" cy="28" r="16" stroke="var(--color-border)" stroke-width="2.5" />
        <line x1="40" y1="40" x2="54" y2="54" stroke="var(--color-border)" stroke-width="2.5" stroke-linecap="round" />
        <line x1="22" y1="28" x2="34" y2="28" stroke="var(--color-border-light)" stroke-width="2" stroke-linecap="round" />
      </svg>
      <svg v-else-if="variant === 'chat'" width="64" height="64" viewBox="0 0 64 64" fill="none">
        <rect x="8" y="12" width="48" height="32" rx="8" stroke="var(--color-border)" stroke-width="2.5" />
        <path d="M20 44L16 54L28 44" stroke="var(--color-border)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
        <line x1="18" y1="26" x2="38" y2="26" stroke="var(--color-border-light)" stroke-width="2" stroke-linecap="round" />
        <line x1="18" y1="34" x2="30" y2="34" stroke="var(--color-border-light)" stroke-width="2" stroke-linecap="round" />
      </svg>
      <svg v-else width="64" height="64" viewBox="0 0 64 64" fill="none">
        <rect x="12" y="8" width="40" height="48" rx="6" stroke="var(--color-border)" stroke-width="2.5" />
        <line x1="20" y1="20" x2="44" y2="20" stroke="var(--color-border-light)" stroke-width="2" stroke-linecap="round" />
        <line x1="20" y1="28" x2="38" y2="28" stroke="var(--color-border-light)" stroke-width="2" stroke-linecap="round" />
        <line x1="20" y1="36" x2="42" y2="36" stroke="var(--color-border-light)" stroke-width="2" stroke-linecap="round" />
        <line x1="20" y1="44" x2="32" y2="44" stroke="var(--color-border-light)" stroke-width="2" stroke-linecap="round" />
      </svg>
    </div>
    <h3 v-if="headline" class="empty-headline">{{ headline }}</h3>
    <p class="empty-desc">{{ description }}</p>
    <div v-if="$slots.default" class="empty-actions">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  headline?: string
  description?: string
  variant?: 'default' | 'search' | 'chat' | 'data'
}>(), {
  headline: '',
  description: '暂无数据',
  variant: 'default',
})
</script>

<style scoped>
.empty-state {
  padding: var(--space-10) 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.empty-illustration {
  margin-bottom: var(--space-5);
  opacity: 0.8;
}

.empty-headline {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  margin: 0 0 var(--space-2) 0;
}

.empty-desc {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin: 0;
  max-width: 320px;
}

.empty-actions {
  margin-top: var(--space-5);
}
</style>
