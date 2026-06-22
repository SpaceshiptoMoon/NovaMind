<template>
  <div v-for="msg in messages" :key="msg.id || msg._id" class="message-row" :class="msg.role">
    <div class="message-avatar">
      <el-avatar v-if="msg.role === 'assistant'" :size="28" icon="UserFilled" class="assistant-avatar" />
      <el-avatar v-else :size="28" class="user-avatar">我</el-avatar>
    </div>
    <div class="message-body">
      <div class="message-name">{{ msg.role === 'assistant' ? 'AI' : '我' }}</div>

      <template v-if="msg.role === 'assistant'">
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
  return expandedReasoning.value.has(msgId)
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
