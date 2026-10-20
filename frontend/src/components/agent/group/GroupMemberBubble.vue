<template>
  <div class="member-bubble" :class="{ 'is-thinking': thinkingOnly, 'no-head': !showNameHead }">
    <!-- 头像独立左列（经典 IM 布局）：同人连续发言留空占位对齐 -->
    <div class="avatar-col">
      <div v-if="showNameHead" class="name-avatar" :style="avatarStyle" :title="entry.name">
        {{ (entry.name || '成').charAt(0) }}
      </div>
    </div>

    <div class="content-col">
      <div v-if="showNameHead" class="name-head">
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

      <!-- 工作过程折叠条（制度同单聊 fold-line）：默认折叠，轨迹不抢正文视觉焦点；
           进行中由 spinner+主题色表达，展开后看思考流与工具卡（工具卡仍逐个展开看参数与结果） -->
      <button
        v-if="hasTrail"
        class="fold-line"
        :class="{ running: entry.streaming }"
        @click="trailOpen = !trailOpen"
      >
        <span v-if="entry.streaming" class="fold-spinner" aria-hidden="true"></span>
        <span class="fold-status">{{ trailLabel }}</span>
        <span class="expand-chevron" :class="{ expanded: trailOpen }" aria-hidden="true">
          <svg viewBox="0 0 12 12" width="10" height="10">
            <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
        </span>
      </button>

      <div v-if="hasTrail" v-show="trailOpen" class="work-trail">
        <!-- 思考流（时间序在工具调用之前） -->
        <div v-if="entry.reasoning" class="reasoning-block">
          <MarkdownRenderer :content="entry.reasoning" />
        </div>
        <!-- 工具卡列表（执行状态实时翻转；点开看参数与结果） -->
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

      <div v-if="entry.content" class="bubble-body" :class="{ 'is-streaming': entry.streaming }">
        <MarkdownRenderer :content="entry.content" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 成员发言气泡：成员色头像/名字 + 工作过程折叠条 + 正文
 *
 * 区分度制度（参考 Muse 的多 Agent 身份感）：成员名散列色相，头像底/名字
 * 文字全程同色，不同成员一眼可分。工作过程制度同单聊 fold-line：思考流+
 * 工具卡收进一条折叠条默认收起（轨迹不抢正文焦点），进行中状态由
 * spinner+主题色表达，展开才见轨迹（工具卡仍逐个展开看参数与结果）。
 */
import { computed, ref } from 'vue'
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
const trailOpen = ref(false)

function toggleTool(callId: string) {
  const next = new Set(expandedTools.value)
  if (next.has(callId)) next.delete(callId)
  else next.add(callId)
  expandedTools.value = next
}

/** 还没有任何正文 = 纯思考阶段（名字头提示文案区分） */
const thinkingOnly = computed(() => !props.entry.content.trim())

/** 有思考流或工具轨迹即显示折叠条 */
const hasTrail = computed(() => Boolean(props.entry.reasoning?.trim()) || Boolean(props.entry.toolCalls?.length))

// 折叠条状态标签：定长两段式「思考中/思考完成」（无秒数——群聊条目无单轮耗时数据，
// 可变数字段禁入折叠除外），状态差异由 spinner+主题色+「中/完成」一词之差表达
const trailLabel = computed(() => (props.entry.streaming ? '思考中' : '思考完成'))

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
  align-items: flex-start;
  gap: var(--space-3);
  min-width: 0;
  animation: memberIn 0.3s ease forwards;
}

/* 头像独立左列：同人连续发言时留空占位，内容列仍对齐 */
.avatar-col {
  width: 30px;
  flex-shrink: 0;
}

.content-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
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
  min-height: 30px;
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

/* 工作过程折叠条（制度同单聊 fold-line：胶囊行 + spinner + 主题色） */
.fold-line {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  padding: 3px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.fold-line:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-text);
}

/* 进行中折叠条：主题色 + spinner，与已完成态区分 */
.fold-line.running {
  color: var(--color-primary, var(--color-text));
  border-color: var(--color-border);
}

.fold-spinner {
  width: 10px;
  height: 10px;
  flex-shrink: 0;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: fold-spin 0.8s linear infinite;
}

@keyframes fold-spin {
  to {
    transform: rotate(360deg);
  }
}

/* 展开后的轨迹容器：左竖线时间线视觉（同单聊 work-trail），思考流+工具卡顺排 */
.work-trail {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: var(--space-1) 0 var(--space-1) var(--space-2);
  padding: var(--space-2) 0 var(--space-2) var(--space-4);
  border-left: 2px solid var(--color-border-light);
  min-width: 0;
}

.reasoning-block {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  border-left: 2px solid var(--color-border-light);
  padding-left: var(--space-2);
  font-style: italic;
  word-break: break-word;
  overflow-wrap: anywhere;
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
