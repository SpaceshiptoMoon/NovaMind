<template>
  <div v-if="speaker" class="run-status">
    <div class="rs-avatar" :style="avatarStyle">{{ speaker.name.charAt(0) }}</div>
    <span class="rs-name" :style="{ color: nameColor }">{{ speaker.name }}</span>
    <span class="rs-text">正在发言</span>
    <span v-if="waveLabel" class="rs-wave">{{ waveLabel }}</span>
    <button class="rs-stop" title="停止讨论" @click="$emit('stop')">
      <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden>
        <rect x="3" y="3" width="10" height="10" rx="2" fill="currentColor" />
      </svg>
      <span>停止</span>
    </button>
  </div>
</template>

<script setup lang="ts">
/**
 * 群 run 进行中状态条：当前发言人（成员色身份）+ 波次进度 + 停止按钮
 *
 * 吸在输入区上方的细条（36px）；wave 取自 group.speaker 事件（头脑风暴
 * 显示「第 N 轮」，consult 恒 1 不显示）；停止 = abort WS，服务端收尾
 * run=cancelled。
 */
import { computed } from 'vue'
import type { GroupSpeakerData } from '@/api/types'
import { memberAvatarStyle, memberNameColor } from '@/utils/memberColor'

const props = defineProps<{ speaker: GroupSpeakerData | null }>()
defineEmits<{ stop: [] }>()

const avatarStyle = computed(() => memberAvatarStyle(props.speaker?.name || ''))
const nameColor = computed(() => memberNameColor(props.speaker?.name || ''))

const waveLabel = computed(() => {
  const wave = props.speaker?.wave
  if (!wave || wave <= 1) return ''
  return `第 ${wave} 轮`
})
</script>

<style scoped>
.run-status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 36px;
  padding: 0 var(--space-3);
  margin: 0 auto;
  max-width: var(--container-width-md);
  width: 100%;
  box-sizing: border-box;
  border-top: 1px solid var(--color-border-light);
  background: var(--color-bg-card);
  min-width: 0;
}

.rs-avatar {
  width: 20px;
  height: 20px;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: var(--weight-semibold);
  flex-shrink: 0;
  user-select: none;
}

.rs-name {
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rs-text {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
  flex-shrink: 0;
}

.rs-wave {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.rs-stop {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  padding: 3px 10px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-text-muted);
  font-family: var(--font-body);
  font-size: var(--text-xs);
  cursor: pointer;
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

.rs-stop:hover {
  border-color: var(--color-danger);
  color: var(--color-danger);
  background: var(--color-danger-subtle);
}
</style>
