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

      <!-- 取消流式按钮 -->
      <button v-if="disabled" class="cancel-btn" title="停止回答" @click="$emit('cancel-stream')">
        <el-icon :size="18"><VideoPause /></el-icon>
      </button>

      <!-- 发送按钮 -->
      <button
        v-else
        class="send-btn"
        :class="{ active: inputText.trim() || pendingAttachmentsCount > 0 }"
        :disabled="(!inputText.trim() && pendingAttachmentsCount === 0) || disabled"
        @click="handleSendClick"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M22 2L11 13" /><path d="M22 2L15 22L11 13L2 9L22 2Z" />
        </svg>
      </button>
    </div>

    <!-- 设置栏 -->
    <div class="input-footer">
      <button class="settings-toggle" @click="settingsExpanded = !settingsExpanded">
        <el-icon :size="12"><Setting /></el-icon>
        <span>{{ settingsSummary }}</span>
        <el-icon :size="8" class="toggle-arrow" :class="{ expanded: settingsExpanded }"><ArrowDown /></el-icon>
      </button>
      <div v-if="settingsExpanded" class="settings-bar">
        <div class="settings-bar-inner">
          <div class="setting-group">
            <span class="setting-label">深度思考</span>
            <el-switch v-model="enableThinking" size="small" />
          </div>
          <div class="setting-group">
            <span class="setting-label">流式输出</span>
            <el-switch v-model="useStream" size="small" />
          </div>
          <div class="setting-group">
            <span class="setting-label">🌐 联网</span>
            <el-switch v-model="enableWebSearch" size="small" />
          </div>
          <button class="setting-group clickable" @click="$emit('open-config')">
            <span class="setting-label">会话设置</span>
            <el-icon :size="12"><ArrowRight /></el-icon>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Paperclip, VideoPause, Setting, ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import { chatApi } from '@/api/chat'

const props = defineProps<{
  disabled: boolean
  pendingAttachmentsCount?: number
}>()

const emit = defineEmits<{
  send: [content: string, options: {
    useStream: boolean
    enableThinking: boolean
    enableWebSearch: boolean
    attachmentIds?: number[]
  }]
  'cancel-stream': []
  'attachment-added': []
  'open-config': []
}>()

const inputText = ref('')
const textareaRef = ref<HTMLTextAreaElement>()
const fileInputRef = ref<HTMLInputElement>()
const useStream = ref(true)
const enableThinking = ref(false)
const enableWebSearch = ref(false)
const settingsExpanded = ref(false)
const uploadingFiles = ref(false)
const settingsSummary = computed(() => {
  const parts: string[] = []
  if (enableThinking.value) parts.push('深度思考')
  if (useStream.value) parts.push('流式')
  if (enableWebSearch.value) parts.push('联网')
  return parts.join(' · ') || '能力设置'
})

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
    const ext = file.name.split('.').pop()?.toLowerCase()
    if (!ext || !['pdf', 'docx', 'txt', 'md', 'jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext)) {
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
    const formData = new FormData()
    for (const f of validFiles) {
      formData.append('files', f, f.name)
    }
    await chatApi.uploadAttachments(formData)
    emit('attachment-added')
  } catch {
    ElMessage.error(`上传失败`)
  } finally {
    uploadingFiles.value = false
    if (fileInputRef.value) fileInputRef.value.value = ''
  }
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
  padding: 0 var(--space-6) var(--space-5);
  background: var(--color-bg-card);
}

.input-pill {
  max-width: 860px;
  margin: 0 auto;
  display: flex;
  align-items: flex-end;
  padding: 8px 12px;
  gap: var(--space-2);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: 24px;
  transition: border-color var(--transition-base), box-shadow var(--transition-base);
}

.input-pill:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-muted);
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

.send-btn {
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

.send-btn.active {
  background: var(--color-primary);
  color: #FFFFFF;
  cursor: pointer;
}

.send-btn.active:hover {
  background: var(--color-primary-hover);
  transform: scale(1.05);
}

.stop-btn {
  background: var(--color-warning);
  color: #FFFFFF;
  cursor: pointer;
}

.stop-btn:hover {
  background: var(--color-accent);
}

.cancel-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-warning);
  color: #FFFFFF;
  cursor: pointer;
  transition: all var(--transition-base);
  flex-shrink: 0;
}

.cancel-btn:hover {
  background: var(--color-accent);
}

/* ========================================
   Input Footer — Settings Toggle
   ======================================== */
.input-footer {
  max-width: 860px;
  margin: 6px auto 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px;
}

.settings-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  font-family: var(--font-body);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  transition: all var(--transition-fast);
}

.settings-toggle:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}

.toggle-arrow {
  transition: transform var(--transition-fast);
}

.toggle-arrow.expanded {
  transform: rotate(180deg);
}

.input-hint-inline {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

/* ========================================
   Settings Bar (Collapsible)
   ======================================== */
.settings-slide-enter-active,
.settings-slide-leave-active {
  transition: all var(--transition-base);
  overflow: hidden;
}

.settings-slide-enter-from,
.settings-slide-leave-to {
  opacity: 0;
  max-height: 0;
  margin-top: 0;
}

.settings-slide-enter-to,
.settings-slide-leave-from {
  opacity: 1;
  max-height: 60px;
  margin-top: 6px;
}

.settings-bar {
  max-width: 860px;
  margin: 6px auto 0;
  padding: 8px 12px;
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.settings-bar-inner {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.setting-group {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.setting-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
}

.setting-group.clickable {
  border: none;
  background: transparent;
  font-family: var(--font-body);
  cursor: pointer;
  color: var(--color-text-secondary);
  padding: 2px 4px;
  border-radius: var(--radius-sm);
  transition: color var(--transition-fast);
}

.setting-group.clickable:hover {
  color: var(--color-primary);
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
  max-width: 860px;
  margin: 6px auto 0;
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
  max-width: 860px;
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
