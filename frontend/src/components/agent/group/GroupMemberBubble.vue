<template>
  <div class="member-bubble" :class="{ 'is-thinking': thinkingOnly }">
    <div v-if="showNameHead" class="name-head">
      <div class="name-avatar" :style="avatarStyle" :title="entry.name">
        {{ (entry.name || '成').charAt(0) }}
      </div>
      <span class="name-text" :style="{ color: nameColor }">{{ entry.name }}</span>
      <span v-if="entry.streaming && thinkingOnly" class="speaking-hint">
        <span class="speaking-spinner" aria-hidden="true"></span>
        思考中…
      </span>
      <span v-else-if="entry.streaming" class="speaking-hint">
        <span class="speaking-spinner" aria-hidden="true"></span>
        正在发言…
      </span>
    </div>

    <!-- 工作过程：工具卡列表（执行状态实时翻转；点开看参数与结果） -->
    <div v-if="entry.toolCalls?.length" class="work-trail">
      <div
        v-for="tool in entry.toolCalls"
        :key="tool.callId"
        class="tool-card"
      >
        <button class="tool-header" @click="toggleTool(tool.callId)">
          <span class="tool-icon" aria-hidden>
            <svg viewBox="0 0 16 16" width="12" height="12">
              <path
                d="M9.6 1.6a4 4 0 0 0-4.4 5.2L1.4 10.6a1.6 1.6 0 1 0 2.3 2.3l3.8-3.8A4 4 0 0 0 12.7 4.7l-2 2-1.4-1.4 2-2a4 4 0 0 0-1.7-1.7z"
                fill="none"
                stroke="currentColor"
                stroke-width="1.4"
                stroke-linejoin="round"
              />
            </svg>
          </span>
          <span class="tool-name">{{ tool.name || '工具' }}</span>
          <span class="tool-status" :class="tool.status">{{ toolStatusLabel(tool.status) }}</span>
          <span class="expand-chevron" :class="{ expanded: expandedTools.has(tool.callId) }" aria-hidden>
            <svg viewBox="0 0 12 12" width="10" height="10">
              <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
            </svg>
          </span>
        </button>
        <div v-if="expandedTools.has(tool.callId)" class="tool-body">
          <div v-if="tool.arguments && Object.keys(tool.arguments).length" class="tool-section">
            <div class="tool-section-label">参数</div>
            <pre class="tool-json">{{ formatJson(tool.arguments) }}</pre>
          </div>
          <div v-if="tool.result" class="tool-section">
            <div class="tool-section-label">结果</div>
            <pre class="tool-json">{{ truncate(tool.result, 2000) }}</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- 思考过程：默认折叠（发言中自动展开跟随，出正文后自动收起） -->
    <div v-if="entry.reasoning" class="reasoning-section">
      <button class="reasoning-header" @click="reasoningOpen = !reasoningOpen">
        <span class="reasoning-label">{{ reasoningLabel }}</span>
        <span class="expand-chevron" :class="{ expanded: reasoningOpen }" aria-hidden>
          <svg viewBox="0 0 12 12" width="10" height="10">
            <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
        </span>
      </button>
      <div v-show="reasoningOpen" class="reasoning-body">
        <MarkdownRenderer :content="entry.reasoning" />
      </div>
    </div>

    <div v-if="entry.content" class="bubble-body" :class="{ 'is-streaming': entry.streaming }">
      <MarkdownRenderer :content="entry.content" />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 成员发言气泡：成员色头像/名字 + 工具卡 + 思考折叠区 + 正文
 *
 * 区分度制度（参考 Muse 的多 Agent 身份感）：成员名散列色相，头像底/名字
 * 文字全程同色，不同成员一眼可分。工作过程借鉴单聊 work-trail 的
 * 「overview first, details on demand」：工具卡摘要行默认收起，思考区
 * 发言中自动展开、出正文后收起——过程可见但不抢正文的视觉焦点。
 */
import { computed, ref, watch } from 'vue'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import type { GroupTimelineEntry } from '@/api/types'
import { memberAvatarStyle, memberNameColor } from '@/utils/memberColor'

const props = defineProps<{
  entry: GroupTimelineEntry
  /** 与上一条成员发言是否同人（同人不重复名字头） */
  showNameHead: boolean
}>()

const avatarStyle = computed(() => memberAvatarStyle(props.entry.name || ''))
const nameColor = computed(() => memberNameColor(props.entry.name || ''))

const expandedTools = ref(new Set<string>())
const reasoningOpen = ref(false)

function toggleTool(callId: string) {
  const next = new Set(expandedTools.value)
  if (next.has(callId)) next.delete(callId)
  else next.add(callId)
  expandedTools.value = next
}

/** 还没有任何正文 = 纯思考阶段（自动展开思考区） */
const thinkingOnly = computed(() => !props.entry.content.trim())

const reasoningLabel = computed(() =>
  props.entry.streaming && thinkingOnly.value ? '思考中' : '思考过程',
)

// 发言中的纯思考阶段（有思考流、无正文）：自动展开跟随；出正文后自动收起
// （用户手动开合过则尊重，不再自动翻转）
const expandedManually = ref(false)
watch(
  () => [props.entry.streaming, (props.entry.reasoning || '').length > 0, props.entry.content.trim().length > 0] as const,
  ([streaming, hasReasoning, hasContent]) => {
    if (expandedManually.value) return
    if (streaming && hasReasoning && !hasContent) reasoningOpen.value = true
    if (hasContent) reasoningOpen.value = false
  },
)
watch(reasoningOpen, (open) => {
  // 自动翻转的稳态（正文后收起 / 发言中展开）之外的开合视为手动
  const autoState = props.entry.content.trim().length > 0 ? false : props.entry.streaming && (props.entry.reasoning || '').length > 0
  if (open !== autoState) expandedManually.value = true
})

function toolStatusLabel(status: string) {
  if (status === 'running') return '执行中'
  if (status === 'failed') return '失败'
  return '完成'
}

function formatJson(v: unknown) {
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

function truncate(text: string, max: number) {
  return text.length > max ? `${text.slice(0, max)}\n…（已截断）` : text
}
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
  width: 30px;
  height: 30px;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  flex-shrink: 0;
  user-select: none;
  box-shadow: 0 1px 3px rgb(0 0 0 / 0.12);
}

.name-text {
  font-size: var(--text-base);
  font-weight: var(--weight-semibold);
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

/* 工作过程：工具卡（制度同单聊 tool-card，宽度随内容收敛） */
.work-trail {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-width: 0;
}

.tool-card {
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card-elevated);
  overflow: hidden;
  width: fit-content;
  max-width: 100%;
}

.tool-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: 5px 10px;
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  font-family: var(--font-body);
  font-size: var(--text-xs);
  cursor: pointer;
  text-align: left;
  transition: background var(--transition-fast);
  min-width: 0;
}

.tool-header:hover {
  background: var(--color-bg-hover);
}

.tool-icon {
  display: inline-flex;
  flex-shrink: 0;
  color: var(--color-text-muted);
}

.tool-name {
  font-family: var(--font-mono);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-status {
  flex-shrink: 0;
  font-size: var(--text-xs);
  padding: 1px 6px;
  border-radius: var(--radius-full);
}

.tool-status.running {
  background: var(--color-warning-subtle);
  color: var(--color-warning);
}

.tool-status.completed {
  background: var(--color-primary-muted);
  color: var(--color-text-secondary);
}

.tool-status.failed {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

.expand-chevron {
  flex-shrink: 0;
  margin-left: auto;
  display: inline-flex;
  color: var(--color-text-muted);
  transition: transform var(--transition-fast);
}

.expand-chevron.expanded {
  transform: rotate(180deg);
}

.tool-body {
  padding: var(--space-2) var(--space-3) var(--space-3);
  border-top: 1px solid var(--color-border-light);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-width: 600px;
}

.tool-section-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-bottom: 2px;
}

.tool-json {
  margin: 0;
  padding: var(--space-2);
  background: var(--color-bg-card);
  border-radius: var(--radius-md);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
  max-height: 220px;
  overflow-y: auto;
}

/* 思考折叠区（制度同单聊 reasoning-section） */
.reasoning-section {
  border-radius: var(--radius-lg);
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border-light);
  overflow: hidden;
  width: fit-content;
  max-width: 100%;
  min-width: 260px;
}

.reasoning-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  cursor: pointer;
  user-select: none;
  font-family: var(--font-body);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.reasoning-header:hover {
  background: var(--color-bg-hover);
}

.reasoning-label {
  font-weight: var(--weight-medium);
}

.reasoning-body {
  padding: var(--space-2) var(--space-3) var(--space-3);
  border-top: 1px solid var(--color-border-light);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  max-height: 320px;
  overflow-y: auto;
  word-break: break-word;
  overflow-wrap: anywhere;
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
