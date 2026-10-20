<template>
  <div class="group-avatar" :title="title">
    <span v-for="(m, i) in displayMembers" :key="i" class="ga-cell">{{ m.charAt(0) }}</span>
    <span v-if="overflow > 0" class="ga-cell ga-more">+{{ overflow }}</span>
  </div>
</template>

<script setup lang="ts">
/**
 * 群组头像：2×2 迷你成员首字点阵，超出 4 人显示 +N
 *
 * 侧栏群条目与群聊头部徽标双处复用；中性配色（accent 不浸染），
 * 成员名列表由调用方传入（侧栏可从 member_names 传，头部从详情 members 传）。
 */
import { computed } from 'vue'

const props = withDefaults(defineProps<{ members: string[]; title?: string }>(), {
  title: '',
})

const displayMembers = computed(() => props.members.slice(0, 4))
const overflow = computed(() => Math.max(0, props.members.length - 4))
</script>

<style scoped>
.group-avatar {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  width: 28px;
  height: 28px;
  padding: 2px;
  border-radius: var(--radius-md);
  background: var(--color-bg-hover);
  flex-shrink: 0;
}

.ga-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 2px;
  font-size: 9px;
  font-weight: var(--weight-semibold);
  color: var(--color-text-secondary);
  background: var(--color-bg-card);
  overflow: hidden;
  line-height: 1;
}

.ga-more {
  background: transparent;
  color: var(--color-text-muted);
}
</style>
