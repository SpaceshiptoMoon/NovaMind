<template>
  <div class="clawmate-view">
    <ChatPanel />
  </div>
</template>

<script setup lang="ts">
import ChatPanel from './ChatPanel.vue'
</script>

<style scoped>
.clawmate-view {
  position: absolute;
  inset: 0;
  display: flex;
  background: var(--color-bg);
  overflow: hidden;
}
</style>
