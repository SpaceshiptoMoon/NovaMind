<template>
  <div class="member-bubble">
    <div v-if="showNameHead" class="name-head">
      <div class="name-avatar">{{ (entry.name || '成').charAt(0) }}</div>
      <span class="name-text">{{ entry.name }}</span>
      <span v-if="entry.streaming" class="speaking-hint">
        <span class="speaking-spinner" aria-hidden="true"></span>
        正在发言…
      </span>
    </div>
    <div class="bubble-body" :class="{ 'is-streaming': entry.streaming }">
      <MarkdownRenderer :content="entry.content" />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 成员发言气泡：名字头（12px muted + 迷你首字头像）+ 左通栏 markdown 内容
 *
 * 同一成员连续发言不重复名字头（showNameHead 由父级按前一条发言者判定，
 * Discord 式分组降噪）；发言中态名字头右侧 spinner + 气泡随流式内容生长。
 */
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import type { GroupTimelineEntry } from '@/api/types'

defineProps<{
  entry: GroupTimelineEntry
  /** 与上一条成员发言是否同人（同人不重复名字头） */
  showNameHead: boolean
}>()
</script>

<style scoped>
.member-bubble {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  animation: memberIn 0.3s ease forwards;
}

@keyframes memberIn {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.name-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.name-avatar {
  width: 22px;
  height: 22px;
  border-radius: var(--radius-full);
  background: var(--color-chip-active);
  color: var(--color-chip-active-text);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  flex-shrink: 0;
  user-select: none;
}

.name-text {
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.speaking-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--color-text-faint);
  flex-shrink: 0;
}

.speaking-spinner {
  width: 10px;
  height: 10px;
  flex-shrink: 0;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: speak-spin 0.8s linear infinite;
}

@keyframes speak-spin {
  to {
    transform: rotate(360deg);
  }
}

.bubble-body {
  min-width: 0;
  font-size: var(--text-sm);
  color: var(--color-text);
  line-height: var(--leading-relaxed);
  word-break: break-word;
  overflow-wrap: anywhere;
}

.bubble-body.is-streaming {
  min-height: 1.4em;
}
</style>
