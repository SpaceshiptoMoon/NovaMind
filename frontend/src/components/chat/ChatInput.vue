<template>
  <div class="input-area">
    <!-- 输入卡（agent .input-card 逐字同构）：附件栏 → 文本区 → 底部工具行 -->
    <div class="input-card">
      <!-- 附件缩略图栏（卡内顶部，有附件才渲染） -->
      <div v-if="chatStore.pendingAttachments.length > 0" class="input-attachments">
        <div v-for="att in chatStore.pendingAttachments" :key="att.id" class="attachment-chip">
          <span class="att-type-badge">{{ getFileExt(att.filename) }}</span>
          <span class="att-name">{{ att.filename }}</span>
          <span class="att-size">{{ formatFileSize(att.file_size) }}</span>
          <button class="att-remove" @click="removeUploadFile(att.id)">
            <el-icon :size="10"><Close /></el-icon>
          </button>
        </div>
      </div>

      <!-- 文本框区 -->
      <div class="input-scroll">
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
      </div>

      <!-- 底部工具行：左 = + 附件 + 模式 chip；右 = 模型 + 发送/停止 -->
      <div class="input-row">
        <div class="input-tools">
          <button
            class="input-add-btn"
            :disabled="disabled || uploadingFiles"
            @click="triggerFileSelect"
            title="上传文档"
          >
            <el-icon :size="14"><Plus /></el-icon>
          </button>
          <input
            ref="fileInputRef"
            type="file"
            accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.gif,.webp"
            style="display: none"
            @change="handleFileSelected"
          />
          <div class="input-modes">
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
        </div>
        <div class="input-trailing">
          <ModelTrigger
            v-if="Object.keys(models).length"
            v-model="selectedModel"
            :models="models"
          />
          <button
            v-if="disabled"
            class="send-primary stop-primary"
            title="停止"
            @click="$emit('cancel-stream')"
          >
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Close, MagicStick, Search, Lightning } from '@element-plus/icons-vue'
import { useChatStore } from '@/stores/chat'
import { useChatAttachments } from '@/composables/useChatAttachments'
import ModelTrigger from '@/components/common/ModelTrigger.vue'

type ModelMeta = { max_tokens: number; temperature: number; top_p: number; model_type: string }

const props = defineProps<{
  disabled: boolean
  pendingAttachmentsCount?: number
  /** 可选模型表（qa 侧由 ChatView 传入；空表隐藏模型选择器） */
  models?: Record<string, ModelMeta>
  /** 页头模型选择初值（可选，卡内选择独立） */
  selectedModel?: string
}>()

const emit = defineEmits<{
  send: [
    content: string,
    options: {
      useStream: boolean
      enableThinking: boolean
      enableWebSearch: boolean
      llmModel?: string
      attachmentIds?: number[]
    },
  ]
  'cancel-stream': []
  'update:selectedModel': [value: string]
}>()

const chatStore = useChatStore()
const inputText = ref('')
const textareaRef = ref<HTMLTextAreaElement>()
const fileInputRef = ref<HTMLInputElement>()
const useStream = ref(true)
const enableThinking = ref(false)
const enableWebSearch = ref(false)
const uploadingFiles = ref(false)
// 卡内模型选择（'' = Auto；初值取页头选择），变化经 update:selectedModel 通知父级
const selectedModel = ref(props.selectedModel ?? '')
const { getFileExt, formatFileSize } = useChatAttachments()

const models = computed<Record<string, ModelMeta>>(() => props.models ?? {})

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
    llmModel: selectedModel.value || undefined,
  })
}
</script>

<style scoped>
/* ========================================
   Input Area（agent 卡同款外层）
   ======================================== */
.input-area {
  flex-shrink: 0;
  padding: var(--space-2) 48px 16px;
  background: transparent;
}

/* ========================================
   输入卡（agent .input-card 逐字复刻）：附件栏 → 文本区 → 底部工具行
   ======================================== */
.input-card {
  /* 与智能体/深度研究页输入卡同宽（--container-width-md = 816px），三页统一 */
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  max-width: var(--container-width-md);
  margin: 0 auto;
  padding: 10px 12px 6px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-md);
  transition:
    border-color var(--transition-base),
    box-shadow var(--transition-base);
}

.input-card:focus-within {
  border-color: var(--color-primary);
  box-shadow:
    0 0 0 3px var(--color-primary-muted),
    var(--shadow-sm);
}

/* 附件缩略图栏（卡内顶部，有附件才渲染） */
.input-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 4px 4px 0;
}

/* 文本框区 */
.input-scroll {
  max-height: 160px;
  overflow-y: auto;
}

.chat-textarea {
  display: block;
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  font-family: var(--font-body);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  color: var(--color-text);
  background: transparent;
  padding: 4px 8px 0 12px;
}

.chat-textarea::placeholder {
  color: var(--color-text-faint);
}

.chat-textarea:disabled {
  opacity: 0.5;
}

/* 底部工具行：左 = + 附件 + 模式 chips；右 = 模型 + 发送/停止（agent .input-row 同构） */
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
  min-width: 0;
}

.input-add-btn {
  display: grid;
  place-items: center;
  flex: none;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-bg-hover);
  color: var(--color-text);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.input-add-btn:hover:not(:disabled) {
  background: var(--color-bg-sidebar);
}

.input-add-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.input-modes {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.mode-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.mode-chip:hover {
  border-color: var(--color-border);
}

.mode-chip.active {
  background: var(--color-btn-primary);
  border-color: var(--color-btn-primary);
  color: #ffffff;
  font-weight: var(--weight-medium);
}

.mode-chip-icon {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}

.input-trailing {
  display: flex;
  align-items: center;
  flex: none;
  gap: 12px;
  min-width: 0;
}

/* 发送/停止：34px 圆形（agent .send-primary 逐字复刻） */
.send-primary {
  display: grid;
  place-items: center;
  flex: none;
  width: 34px;
  height: 34px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-bg-hover);
  color: var(--color-text-faint);
  cursor: not-allowed;
  transition: all var(--transition-base);
}

.send-primary.active {
  background: var(--color-gradient-accent);
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(90, 80, 255, 0.28);
}

.send-primary.active:hover {
  background: var(--color-gradient-accent-hover);
}

.stop-primary {
  background: var(--color-warning);
  cursor: pointer;
}

.stop-primary:hover {
  background: var(--color-accent);
}

/* 附件 chip（agent .attachment-chip 同构） */
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
</style>
