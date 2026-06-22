<template>
  <div class="chat-input-wrapper">
    <!-- 快速提示 -->
    <div v-if="!inputText && !disabled && quickPromptVisible" class="quick-prompts">
      <button
        v-for="(prompt, i) in quickPrompts"
        :key="i"
        class="quick-prompt-btn"
        @click="handleQuickPromptClick(prompt)"
      >
        {{ prompt }}
      </button>
    </div>

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
    <div class="settings-row">
      <button class="settings-toggle" @click="settingsExpanded = !settingsExpanded">
        <el-icon :size="14"><Setting /></el-icon>
        <span>{{ settingsSummary }}</span>
        <el-icon :size="10" class="toggle-arrow" :class="{ expanded: settingsExpanded }"><ArrowDown /></el-icon>
      </button>
      <div v-if="settingsExpanded" class="settings-bar">
        <div class="settings-bar-inner">
          <label class="settings-item">
            <span>深度思考</span>
            <el-switch v-model="enableThinking" size="small" />
          </label>
          <label class="settings-item">
            <span>流式回答</span>
            <el-switch v-model="useStream" size="small" />
          </label>
          <label class="settings-item">
            <span>🌐联网搜索</span>
            <el-switch v-model="enableWebSearch" size="small" />
          </label>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Paperclip, VideoPause, Setting, ArrowDown } from '@element-plus/icons-vue'
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
}>()

const inputText = ref('')
const textareaRef = ref<HTMLTextAreaElement>()
const fileInputRef = ref<HTMLInputElement>()
const useStream = ref(true)
const enableThinking = ref(false)
const enableWebSearch = ref(false)
const settingsExpanded = ref(false)
const uploadingFiles = ref(false)
const quickPromptVisible = ref(true)

const quickPrompts = [
  '帮我分析一下这段代码的逻辑',
  '写一篇关于人工智能发展趋势的摘要',
  '帮我从知识库中搜索相关资料',
  '如何优化数据库查询性能？',
]

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

function handleQuickPromptClick(text: string) {
  inputText.value = text
  quickPromptVisible.value = false
  autoResize()
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
  quickPromptVisible.value = true
  autoResize()

  emit('send', sendContent, {
    useStream: useStream.value,
    enableThinking: enableThinking.value,
    enableWebSearch: enableWebSearch.value,
  })
}
</script>
