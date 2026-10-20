<template>
  <div ref="scrollRef" class="group-timeline" @scroll="handleScroll">
    <div class="timeline-inner">
      <!-- 空态：时间线无消息 -->
      <div v-if="entries.length === 0" class="timeline-empty">发送第一条消息，开始群聊讨论</div>

      <template v-for="(entry, i) in entries" :key="i">
        <!-- 用户消息：右对齐浅底气泡（与单聊同款制度） -->
        <div v-if="entry.kind === 'user'" class="message-row user">
          <div class="message-body">
            <div class="message-text">{{ entry.content }}</div>
          </div>
        </div>

        <!-- notice：居中弱信息行（consult 徽标/系统提示/错误同制度，错误用 danger 文字） -->
        <div
          v-else-if="entry.kind === 'notice'"
          class="notice-line"
          :class="{ 'is-error': entry.isError }"
        >
          {{ entry.content }}
        </div>

        <!-- 成员发言：左通栏气泡，同人连续发言不重复名字头 -->
        <GroupMemberBubble
          v-else
          :entry="entry"
          :show-name-head="!isSameAsPrevMember(entry, i)"
        />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 群时间线消息流：用户右气泡 / 成员左通栏气泡 / notice 居中弱行
 *
 * 不复用单聊按轮分组——群按消息流平铺（成员发言间有名字头天然分隔）；
 * 滚动跟随制度与单聊一致：仅当用户本就在底部（±80px）才自动跟随。
 */
import { ref, watch, nextTick } from 'vue'
import GroupMemberBubble from './GroupMemberBubble.vue'
import type { GroupTimelineEntry } from '@/api/types'

const props = defineProps<{ entries: GroupTimelineEntry[] }>()

const scrollRef = ref<HTMLElement>()
const stickToBottom = ref(true)

function isSameAsPrevMember(entry: GroupTimelineEntry, index: number): boolean {
  if (entry.kind !== 'member') return false
  const prev = props.entries[index - 1]
  return (
    !!prev &&
    prev.kind === 'member' &&
    prev.member_agent_id === entry.member_agent_id
  )
}

function scrollToBottom() {
  nextTick(() => {
    if (scrollRef.value) {
      scrollRef.value.style.scrollBehavior = 'auto'
      scrollRef.value.scrollTop = scrollRef.value.scrollHeight
      scrollRef.value.style.scrollBehavior = ''
    }
  })
}

function handleScroll() {
  const el = scrollRef.value
  if (!el) return
  stickToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

watch(
  () => props.entries.map((e) => e.content.length).join(','),
  () => {
    if (stickToBottom.value) scrollToBottom()
  },
)

watch(
  () => props.entries.length,
  () => {
    if (stickToBottom.value) scrollToBottom()
  },
)

defineExpose({ scrollToBottom })
</script>

<style scoped>
.group-timeline {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scroll-behavior: smooth;
  padding-top: 48px;
}

.timeline-inner {
  max-width: var(--container-width-md);
  margin: 0 auto;
  padding: var(--space-6) var(--space-6) var(--space-4);
}

.timeline-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-10) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-faint);
  text-align: center;
}

/* 用户消息：右对齐浅底气泡（制度同单聊 .message-row.user） */
.message-row {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 24px;
  animation: tlIn 0.3s ease forwards;
}

.message-body {
  max-width: 78%;
  min-width: 0;
}

.message-text {
  padding: var(--space-3) var(--space-4);
  border-radius: 18px 18px 4px 18px;
  background: var(--color-chip-active);
  color: var(--color-chip-active-text);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
}

/* notice：居中弱信息行（consult 徽标/系统提示），错误级 danger 文字，无底色块 */
.notice-line {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  margin: var(--space-3) auto;
  padding: 0 var(--space-4);
  font-size: var(--text-xs);
  color: var(--color-text-faint);
  text-align: center;
  word-break: break-word;
  overflow-wrap: anywhere;
  animation: tlIn 0.3s ease forwards;
}

.notice-line.is-error {
  color: var(--color-danger);
}

/* 成员发言间距：不同 agent 之间留白拉大（32px），阅读节奏分明 */
.timeline-inner > :nth-child(n + 2) {
  margin-top: 0;
}

.member-bubble {
  margin-bottom: 32px;
}

@keyframes tlIn {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 720px) {
  .timeline-inner {
    padding: var(--space-4) var(--space-3) var(--space-2);
  }

  .message-body {
    max-width: 88%;
  }
}
</style>
