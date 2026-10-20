<template>
  <div class="group-avatar" :title="title">
    <span
      v-for="(m, i) in displayMembers"
      :key="i"
      class="ga-cell"
      :style="cellStyle(m)"
    >{{ m.charAt(0) }}</span>
    <span v-if="overflow > 0" class="ga-cell ga-more">+{{ overflow }}</span>
  </div>
</template>

<script setup lang="ts">
/**
 * 群组头像：2×2 成员首字点阵（每格成员标识色），超出 4 人显示 +N
 *
 * 侧栏群条目与群聊头部徽标双处复用；成员色与时间线气泡头像同源
 * （memberColor 散列），同一名成员在群头像格与发言气泡中颜色一致。
 */
import { computed } from 'vue'
import { memberAvatarStyle } from '@/utils/memberColor'

const props = withDefaults(defineProps<{ members: string[]; title?: string }>(), {
  title: '',
})

const displayMembers = computed(() => props.members.slice(0, 4))
const overflow = computed(() => Math.max(0, props.members.length - 4))

function cellStyle(name: string) {
  return memberAvatarStyle(name)
}
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
  overflow: hidden;
  line-height: 1;
}

.ga-more {
  background: var(--color-bg-card);
  color: var(--color-text-muted);
}
</style>
