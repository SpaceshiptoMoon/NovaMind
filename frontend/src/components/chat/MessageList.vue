<template>
  <div v-for="msg in messages" :key="msg.id || msg._id" class="message-row" :class="msg.role">
    <div class="message-body">      <template v-if="msg.role === 'assistant'">
        <div v-if="msg.reasoning" class="reasoning-section">
          <div class="reasoning-header" @click="toggleReasoning(msg.id)">
            <span class="reasoning-label">思考过程</span>
            <el-icon :size="12" class="expand-icon" :class="{ expanded: shouldShowReasoning(msg.id) }">
              <ArrowDown />
            </el-icon>
          </div>
          <div v-if="shouldShowReasoning(msg.id)" class="reasoning-body">
            <div class="reasoning-text">{{ msg.reasoning }}</div>
          </div>
        </div>
        <div v-if="getAnswerStatus(msg) === 'refused'" class="refused-banner">
          <el-icon :size="14"><WarningFilled /></el-icon>
          <span>未在知识库中找到相关资料，已拒答</span>
        </div>
        <div
          class="message-content"
          :class="{ 'low-confidence': getAnswerStatus(msg) === 'low_confidence' }"
          :data-msg-id="msg.id"
          @mouseover="handleCiteOver"
          @mouseout="handleCiteLeave"
        >
          <MarkdownRenderer :content="msg.content" class="message-text" />
          <div v-if="getAnswerStatus(msg) === 'low_confidence'" class="low-confidence-tip">
            ⚠️ 依据较弱（相关度 {{ formatScore(getConfidence(msg)) }}），请审慎参考
          </div>
        </div>
        <SourceList
          v-if="getSources(msg).length"
          :sources="getSources(msg)"
          :active-index="hoverCiteIndex"
          @hover="onSourceHover"
          @select="onSourceSelect"
        />
        <RetrievalTrace :traces="(msg.extra as Record<string, unknown> | null)?.traces as Record<string, unknown>[] | undefined" />
      </template>
      <template v-else>
        <div class="message-text">{{ msg.content }}</div>
        <div v-if="getMessageAttachments(msg).length" class="message-attachments">
          <template v-for="att in getMessageAttachments(msg)" :key="att.filename">
            <div v-if="isImageFile(att.file_type) && att.id" class="image-card" @click="handleDownloadAttachment(att)">
              <img v-if="getImagePreviewUrl(att)" :src="getImagePreviewUrl(att)" class="image-thumb" loading="lazy" />
              <div v-else class="image-thumb image-thumb-loading">加载中...</div>
              <div class="image-info">
                <span class="image-name">{{ att.filename }}</span>
                <span class="image-size">{{ formatFileSize(att.file_size) }}</span>
              </div>
            </div>
            <div v-else class="file-card" @click="handleDownloadAttachment(att)">
              <div class="file-icon-box" :class="getFileIconClass(att.file_type)">
                <span class="file-ext-label">{{ getFileExt(att.filename) }}</span>
              </div>
              <div class="file-info">
                <div class="file-name">{{ att.filename }}</div>
                <div class="file-meta">{{ getFileExt(att.filename) }} · {{ formatFileSize(att.file_size) }}</div>
              </div>
              <div class="file-download-btn" title="下载">
                <el-icon :size="16"><Download /></el-icon>
              </div>
            </div>
          </template>
        </div>
      </template>
      <div class="message-actions">
        <button class="msg-copy-btn" @click="handleCopyMessage(msg.content, $event)">
          <el-icon :size="13"><DocumentCopy /></el-icon>
          <span>复制</span>
        </button>
      </div>
    </div>
  </div>

  <!-- 加载指示器 -->
  <div v-if="loading && !isStreaming" class="typing-row">
    <div class="message-body">
      <div class="typing-bubble">
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
      </div>
    </div>
  </div>

  <!-- 引用角标悬浮卡 -->
  <el-popover
    :visible="citePopoverVisible"
    :virtual-ref="citeTriggerEl"
    virtual-triggering
    trigger="click"
    :width="320"
    placement="bottom-start"
    @visible-change="handleCiteVisibleChange"
  >
    <template #reference>
      <span />
    </template>
    <div v-if="activeCiteSource" class="cite-popover-content">
      <div class="cite-title">{{ activeCiteSource.title || activeCiteSource.filename }}</div>
      <div class="cite-snippet">{{ activeCiteSource.snippet || activeCiteSource.content }}</div>
      <div class="cite-score" v-if="activeCiteSource.score !== undefined">
        相关度: {{ formatScore(activeCiteSource.score) }}
      </div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ArrowDown, WarningFilled, Download, DocumentCopy } from '@element-plus/icons-vue'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import SourceList from '@/components/chat/SourceList.vue'
import RetrievalTrace from '@/components/chat/RetrievalTrace.vue'
import type { ChatMessage, ChatSource } from '@/api/types'
import { useChatAttachments } from '@/composables/useChatAttachments'

const props = defineProps<{
  messages: ChatMessage[]
  isStreaming: boolean
  loading: boolean
}>()

const emit = defineEmits<{
  'copy-message': [content: string, event: MouseEvent]
}>()

const {
  isImageFile,
  getImagePreviewUrl,
  getFileExt,
  handleDownloadAttachment,
  formatFileSize,
} = useChatAttachments()

// 推理展开
const expandedReasoning = ref(new Set<number>())

function toggleReasoning(msgId: number) {
  const s = new Set(expandedReasoning.value)
  if (s.has(msgId)) s.delete(msgId)
  else s.add(msgId)
  expandedReasoning.value = s
}

function shouldShowReasoning(msgId: number): boolean {
  if (expandedReasoning.value.has(msgId)) return true
  // 流式中最后一条消息自动展开推理（思考模型先输出 reasoning 再输出 content）
  if (props.isStreaming) {
    const last = props.messages[props.messages.length - 1]
    return !!last && (last.id === msgId || (last as any)._id === msgId)
  }
  return false
}

// 消息辅助函数
function getMessageAttachments(msg: ChatMessage): Array<{ id?: number; filename: string; file_type?: string; file_size?: number; storage_path?: string }> {
  return (msg as any).extra?.attachments || []
}

function getSources(msg: ChatMessage): ChatSource[] {
  return ((msg as any).extra?.sources || [])
}

function getAnswerStatus(msg: ChatMessage): string {
  return ((msg as any).extra?.answer_status || 'answered')
}

function getConfidence(msg: ChatMessage): number | null {
  return ((msg as any).extra?.confidence ?? null)
}

function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined) return ''
  return (score * 100).toFixed(0) + '%'
}

function getSourceDisplayName(s: ChatSource): string {
  return s.title || s.filename || s.content?.slice(0, 30) || '来源'
}

function getFileIconClass(type?: string): string {
  if (!type) return 'file-unknown'
  const t = type.toLowerCase()
  if (['pdf'].includes(t)) return 'file-pdf'
  if (['doc', 'docx'].includes(t)) return 'file-word'
  if (['xls', 'xlsx'].includes(t)) return 'file-excel'
  if (['md', 'txt'].includes(t)) return 'file-text'
  if (['json', 'csv'].includes(t)) return 'file-data'
  return 'file-unknown'
}

// 引用 popover
const citePopoverVisible = ref(false)
const citeTriggerEl = ref<HTMLElement>()
const activeCiteSource = ref<ChatSource | null>(null)
const hoverCiteIndex = ref<number | null>(null)

function handleCiteOver(e: MouseEvent) {
  const target = e.target as HTMLElement
  const cite = target.closest('[data-cite]') as HTMLElement | null
  if (!cite) return
  citeTriggerEl.value = cite
  const index = parseInt(cite.dataset.cite || '0', 10)
  const msgEl = target.closest('[data-msg-id]') as HTMLElement | null
  if (!msgEl) return
  const msgId = parseInt(msgEl.dataset.msgId || '0', 10)
  const msg = props.messages.find(m => m.id === msgId)
  if (!msg) return
  const sources = getSources(msg)
  activeCiteSource.value = sources[index] || null
  if (activeCiteSource.value) citePopoverVisible.value = true
}

function handleCiteLeave() {
  citePopoverVisible.value = false
  citeTriggerEl.value = undefined
  activeCiteSource.value = null
}

function handleCiteVisibleChange(visible: boolean) {
  if (!visible) {
    citeTriggerEl.value = undefined
    activeCiteSource.value = null
  }
}

function onSourceHover(index: number | null) {
  hoverCiteIndex.value = index
}

function onSourceSelect(_s: ChatSource) {
  // 来源选择处理
}

function handleCopyMessage(content: string, e: MouseEvent) {
  e.stopPropagation()
  emit('copy-message', content, e)
}
</script>

<style scoped>
/* ========================================
   Messages
   ======================================== */
.messages-inner {
  max-width: 100%;
  padding: var(--space-6) var(--space-6) var(--space-4);
  padding: var(--space-6) var(--space-6) var(--space-4);
}

.message-row {
  display: flex;
  gap: var(--space-4);
  margin-bottom: 32px;
  padding: 0 var(--space-2);
  animation: messageIn 0.3s ease forwards;
}

@keyframes messageIn {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

.message-row.user { justify-content: flex-end; }

.message-body { max-width: 75%; min-width: 0; }

.message-text {
  font-size: var(--text-base);
  line-height: var(--leading-relaxed);
  word-break: break-word;
}

/* User message */
.message-row.user .message-text {
  padding: var(--space-3) var(--space-4);
  border-radius: 18px 18px 4px 18px;
  background: var(--color-primary-subtle);
  color: var(--color-primary-hover);
  white-space: pre-wrap;
}

/* AI message */
.message-row.assistant .message-text {
  padding: var(--space-4) var(--space-5);
  border-radius: 18px 18px 18px 4px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
}

/* Reasoning */
.reasoning-section {
  margin-bottom: 8px;
  border-radius: 10px;
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border);
  overflow: hidden;
}
.reasoning-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; cursor: pointer; user-select: none;
  font-size: 13px; color: var(--color-text-secondary);
}
.reasoning-header:hover { background: var(--color-bg-hover); }
.reasoning-label { font-weight: 500; }

.expand-icon { transition: transform 0.2s; }
.expand-icon.expanded { transform: rotate(180deg); }
.reasoning-body {
  padding: 8px 12px 12px;
  border-top: 1px solid var(--color-border);
  font-size: 13px; color: var(--color-text-secondary);
  line-height: 1.6; max-height: 400px; overflow-y: auto;
}
.reasoning-text { white-space: pre-wrap; word-break: break-word; }

/* Message actions */
.message-actions {
  display: flex; gap: var(--space-2);
  padding: 2px 2px 0; opacity: 0;
  transition: opacity var(--transition-fast);
}
.message-row:hover .message-actions { opacity: 1; }

.msg-copy-btn {
  display: inline-flex; align-items: center; gap: 4px;
  border: none; background: transparent;
  font-family: var(--font-body); font-size: var(--text-xs);
  color: var(--color-text-muted); cursor: pointer;
  padding: 3px 8px; border-radius: var(--radius-sm);
  transition: all var(--transition-fast);
}
.msg-copy-btn:hover { background: var(--color-bg-hover); color: var(--color-text-secondary); }
.msg-copy-btn.copied { color: var(--color-success); }

/* Typing indicator */
.typing-row {
  display: flex; gap: var(--space-4); margin-bottom: 28px;
  animation: messageIn 0.35s ease forwards;
}
.typing-bubble {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 10px 16px;
  background: var(--color-bg-card); border: 1px solid var(--color-border);
  border-radius: 18px 18px 18px 4px;
}
.typing-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--color-text-muted);
  animation: dotBounce 1.2s ease-in-out infinite both;
}
.typing-dot:nth-child(2) { animation-delay: 0.15s; }
.typing-dot:nth-child(3) { animation-delay: 0.30s; }

@keyframes dotBounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-6px); opacity: 1; }
}

/* Attachments */
.message-attachments {
  display: flex; flex-direction: column; gap: 6px; margin-top: 6px;
}
.file-card {
  display: flex; align-items: center; width: 260px;
  padding: 10px 12px; border-radius: 10px;
  background: rgba(255,255,255,0.55); cursor: pointer;
  transition: background 0.15s;
}
.file-card:hover { background: rgba(255,255,255,0.7); }
.file-card .file-icon-box {
  width: 40px; height: 40px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  margin-right: 10px; flex-shrink: 0;
}
.file-icon-box .file-ext-label {
  font-size: 11px; font-weight: 700; color: #fff; letter-spacing: 0.3px;
}
.file-icon-box.file-pdf  { background: #ef4444; }
.file-icon-box.file-doc  { background: #6366f1; }
.file-icon-box.file-txt  { background: #8b5cf6; }
.file-icon-box.file-md   { background: #06b6d4; }
.file-icon-box.file-default { background: #6b7280; }
.file-card .file-info { flex: 1; overflow: hidden; }
.file-card .file-name {
  font-size: 13px; color: var(--color-text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.file-card .file-meta { font-size: 11px; color: var(--color-text-muted); margin-top: 2px; }
.file-card .file-download-btn {
  width: 28px; height: 28px; display: flex;
  align-items: center; justify-content: center; border-radius: 6px;
  color: var(--color-text-muted); flex-shrink: 0; margin-left: 4px;
  transition: all 0.15s;
}
.file-card:hover .file-download-btn {
  color: var(--color-text); background: var(--color-bg-hover);
}

/* Image card */
.image-card {
  display: inline-flex; flex-direction: column; cursor: pointer;
  border-radius: 8px; overflow: hidden;
  border: 1px solid var(--color-border); max-width: 200px;
  transition: border-color 0.15s;
}
.image-card:hover { border-color: var(--color-primary); }
.image-thumb { width: 100%; max-height: 150px; object-fit: cover; display: block; }
.image-thumb-loading {
  height: 80px; display: flex; align-items: center; justify-content: center;
  background: var(--color-bg-hover); color: var(--color-text-muted); font-size: var(--text-xs);
}
.image-info { padding: 4px 8px; display: flex; gap: 6px; align-items: center; background: var(--color-bg-card); }
.image-name { font-size: var(--text-xs); color: var(--color-text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.image-size { font-size: 10px; color: var(--color-text-muted); flex-shrink: 0; }

/* Refused / Low-confidence */
.refused-banner {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 12px; margin-bottom: 8px; border-radius: 10px;
  background: rgba(239,68,68,0.1); color: #ef4444;
  font-size: 13px; border: 1px solid #ef4444;
}
.message-content { position: relative; }
.message-content.low-confidence { border-left: 3px solid #f59e0b; }
.low-confidence-tip {
  margin-top: 8px; padding: 6px 10px; border-radius: 6px;
  background: rgba(245,158,11,0.1); color: #f59e0b; font-size: 12px;
}
</style>
