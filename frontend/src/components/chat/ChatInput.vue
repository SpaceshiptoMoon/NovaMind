<template>
  <div class="input-area">
    <!-- 输入药丸 -->
    <div class="input-pill">
      <button
        class="attach-btn"
        :disabled="disabled || uploadingFiles"
        @click="triggerFileSelect"
        title="上传文档"
      >
        <el-icon :size="16"><Paperclip /></el-icon>
      </button>
      <input
        ref="fileInputRef"
        type="file"
        accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.gif,.webp"
        style="display: none"
        @change="handleFileSelected"
      />
      <textarea
        ref="textareaRef"
        v-model="inputText"
        class="chat-textarea"
        placeholder="输入你的问题..."
        :rows="1"
        :disabled="disabled"
        @keydown="handleKeydown"
        @input="autoResize"
      />

      <!-- 底部工具行（agent 输入卡对齐）：左 = 模式 chips；右 = 发送/停止 -->
      <div class="input-row">
        <div class="input-tools">
          <button
            class="mode-chip"
            :class="{ active: enableThinking }"
            @click="enableThinking = !enableThinking"
          >
            <el-icon :size="14" class="mode-chip-icon"><MagicStick /></el-icon>
            <span>深度思考</span>
          </button>
          <button
            class="mode-chip"
            :class="{ active: enableWebSearch }"
            @click="enableWebSearch = !enableWebSearch"
          >
            <el-icon :size="14" class="mode-chip-icon"><Search /></el-icon>
            <span>联网搜索</span>
          </button>
          <button
            class="mode-chip"
            :class="{ active: useStream }"
            @click="useStream = !useStream"
          >
            <el-icon :size="14" class="mode-chip-icon"><Lightning /></el-icon>
            <span>流式输出</span>
          </button>
        </div>
        <div class="input-trailing">
          <!-- 原右上发送/停止按钮移入工具行右端 -->
          <button v-if="disabled" class="send-primary stop-primary" title="停止" @click="$emit('cancel-stream')">
            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden>
              <rect x="3" y="3" width="10" height="10" rx="3" fill="currentColor" />
            </svg>
          </button>
          <button
            v-else
            class="send-primary"
            :class="{ active: inputText.trim() || (pendingAttachmentsCount ?? 0) > 0 }"
            :disabled="(!inputText.trim() && pendingAttachmentsCount === 0) || disabled"
            title="发送"
            @click="handleSendClick"
          >
            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden>
              <path
                d="M8.3125 0.980183C8.66767 1.0531 8.97902 1.20418 9.2627 1.43233C9.48724 1.61297 9.73029 1.85793 9.97949 2.10714L14.707 6.83468L13.293 8.24874L9 3.95577V15.0417H7V3.95577L2.70703 8.24874L1.29297 6.83468L6.02051 2.10714C6.26971 1.85793 6.51277 1.61297 6.7373 1.43233C6.97662 1.23986 7.28445 1.04402 7.6875 0.980183C7.8973 0.947006 8.1031 0.95516 8.3125 0.980183Z"
                fill="currentColor"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- 附件预览 -->
    <div v-if="uploadingFiles || (pendingAttachmentsCount ?? 0) > 0" class="attachment-preview-bar">
      <div v-for="att in chatStore.pendingAttachments" :key="att.id" class="attachment-chip">
        <span class="att-type-badge">{{ getFileExt(att.filename) }}</span>
        <span class="att-name">{{ att.filename }}</span>
        <span class="att-size">{{ formatFileSize(att.file_size) }}</span>
        <button class="att-remove" @click="removeUploadFile(att.id)">
          <el-icon :size="10"><Close /></el-icon>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Paperclip, Close, MagicStick, Search, Lightning } from '@element-plus/icons-vue'
import { useChatStore } from '@/stores/chat'
import { useChatAttachments } from '@/composables/useChatAttachments'

const props = defineProps<{
  disabled: boolean
  pendingAttachmentsCount?: number
}>()

const emit = defineEmits<{
  send: [
    content: string,
    options: {
      useStream: boolean
      enableThinking: boolean
      enableWebSearch: boolean
      attachmentIds?: number[]
    },
  ]
  'cancel-stream': []
}>()

const chatStore = useChatStore()
const inputText = ref('')
const textareaRef = ref<HTMLTextAreaElement>()
const fileInputRef = ref<HTMLInputElement>()
const useStream = ref(true)
const enableThinking = ref(false)
const enableWebSearch = ref(false)
const uploadingFiles = ref(false)
const { getFileExt, formatFileSize } = useChatAttachments()

function autoResize() {
  if (!textareaRef.value) return
  textareaRef.value.style.height = 'auto'
  textareaRef.value.style.height = textareaRef.value.scrollHeight + 'px'
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSendClick()
  }
}

function triggerFileSelect() {
  fileInputRef.value?.click()
}

async function handleFileSelected(e: Event) {
  const files = (e.target as HTMLInputElement).files
  if (!files || files.length === 0) return
  const validFiles: File[] = []
  for (let i = 0; i < files.length; i++) {
    const file = files[i]
    if (!file) continue
    const ext = file.name.split('.').pop()?.toLowerCase()
    // 与后端 ALLOWED_FILE_TYPES 对齐（无 doc：后端不支持 .doc 解析，不提供"自动转换"）
    if (
      !ext ||
      !['pdf', 'docx', 'txt', 'md', 'jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext)
    ) {
      ElMessage.warning(`不支持的文件类型: .${ext}`)
      continue
    }
    if (file.size > 20 * 1024 * 1024) {
      ElMessage.warning(`文件过大: ${file.name}（最大 20MB）`)
      continue
    }
    validFiles.push(file)
  }
  if (validFiles.length === 0) return
  uploadingFiles.value = true
  try {
    // 后端为单文件端点，逐个上传；store.uploadAttachment 会自动填充 pendingAttachments
    for (const f of validFiles) {
      await chatStore.uploadAttachment(f)
    }
  } catch {
    ElMessage.error('上传失败')
  } finally {
    uploadingFiles.value = false
    if (fileInputRef.value) fileInputRef.value.value = ''
  }
}

function removeUploadFile(attachmentId: number) {
  chatStore.removePendingAttachment(attachmentId)
}

function handleSendClick() {
  const content = inputText.value.trim()
  const hasAttachments = (props.pendingAttachmentsCount ?? 0) > 0
  if (!content && !hasAttachments) return

  const sendContent = content || (hasAttachments ? '请分析上传的文档' : '')
  inputText.value = ''
  autoResize()

  emit('send', sendContent, {
    useStream: useStream.value,
    enableThinking: enableThinking.value,
    enableWebSearch: enableWebSearch.value,
  })
}
</script>

<style scoped>
/* ========================================
   Input Area — Pill Shape
   ======================================== */
.input-area {
  flex-shrink: 0;
  padding: 0 48px 16px;
  background: var(--color-bg-card);
}

.input-pill {
  /* 与智能体/深度研究页输入卡同宽（--container-width-md = 816px），三页统一 */
  max-width: var(--container-width-md);
  margin: 0 auto;
  /* agent 输入卡对齐：纵向三段（附件 → 文本 → 工具行），18px 圆角卡片 */
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 12px 6px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: 18px;
  transition:
    border-color var(--transition-base),
    box-shadow var(--transition-base);
}

.input-pill:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-muted);
}

/* 底部工具行：左模式 chips + 右发送（agent 输入卡 .input-row 同构） */
.input-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 2px 4px 0;
}

.input-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.mode-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.mode-chip:hover {
  border-color: var(--color-border);
  color: var(--color-text-secondary);
}

.mode-chip.active {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
  color: var(--color-primary);
}

.mode-chip-icon {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}

.input-trailing {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* 发送/停止：36px 圆形实心按钮（agent .send-primary 同款） */
.send-primary {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-border);
  color: var(--color-text-faint);
  cursor: not-allowed;
  transition: all var(--transition-base);
  flex-shrink: 0;
}

.send-primary.active {
  background: var(--color-btn-primary);
  color: #ffffff;
  cursor: pointer;
}

.send-primary.active:hover {
  background: var(--color-btn-primary-hover);
  transform: scale(1.05);
}

.stop-primary {
  background: var(--color-warning);
  color: #ffffff;
  cursor: pointer;
}

.stop-primary:hover {
  background: var(--color-accent);
}

.chat-textarea {
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  font-family: var(--font-body);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  color: var(--color-text);
  background: transparent;
  padding: var(--space-2) var(--space-2);
  max-height: 160px;
  overflow-y: auto;
}

.chat-textarea::placeholder {
  color: var(--color-text-faint);
}

.chat-textarea:disabled {
  opacity: 0.5;
}

/* ========================================
   Attachment Button
   ======================================== */
.attach-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.attach-btn:hover:not(:disabled) {
  background: var(--color-bg-hover);
  color: var(--color-primary);
}

.attach-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ========================================
   Attachment Preview Bar
   ======================================== */
.attachment-preview-bar {
  margin: 6px 0 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 4px;
}

.attachment-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px 4px 4px;
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  font-size: var(--text-xs);
  max-width: 240px;
}

.att-type-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 5px;
  border-radius: var(--radius-sm);
  background: var(--color-primary-muted);
  color: var(--color-primary);
  font-size: 10px;
  font-weight: var(--weight-semibold);
  letter-spacing: 0.5px;
  flex-shrink: 0;
}

.att-name {
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.att-size {
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.att-remove {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

.att-remove:hover {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

/* ========================================
   Quick Prompts
   ======================================== */
.quick-prompts {
  max-width: var(--container-width-md);
  margin: 0 auto 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 4px;
}

.quick-prompt-btn {
  padding: 6px 14px;
  font-size: var(--text-xs);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
  font-family: var(--font-body);
}

.quick-prompt-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-muted);
}
</style>
