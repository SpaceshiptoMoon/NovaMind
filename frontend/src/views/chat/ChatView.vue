<template>
  <div class="chat-view">
    <!-- 侧边栏：会话列表（仅在非工作台模式显示） -->
    <div v-if="!isInWorkspace" class="chat-sidebar">
      <div class="sidebar-top">
        <button class="new-chat-btn" @click="handleNewSession">
          <el-icon :size="16"><Plus /></el-icon>
          <span>开启新对话</span>
        </button>
      </div>
      <div class="session-list">
        <div
          v-for="session in chatStore.sessions"
          :key="session.session_id"
          class="session-item"
          :class="{ active: chatStore.currentSessionId === session.session_id }"
          @click="handleSelectSession(session.session_id)"
        >
          <span class="session-title">{{ session.preview || '新对话' }}</span>
          <button
            class="session-delete"
            @click.stop="handleDeleteSession(session.session_id)"
          >
            <el-icon :size="12"><Delete /></el-icon>
          </button>
        </div>
        <div v-if="chatStore.sessions.length === 0" class="sidebar-empty">
          <span>暂无对话记录</span>
        </div>
      </div>
    </div>

    <!-- 主聊天区域 -->
    <div class="chat-main">
      <!-- 空状态：欢迎屏幕 -->
      <div v-if="chatStore.messages.length === 0 && !chatStore.loading" class="welcome-screen">
        <div class="welcome-inner">
          <h2 class="welcome-title">今天想聊点什么？</h2>
          <p class="welcome-subtitle">我可以帮你回答问题、分析文档、编写代码，或从知识库中搜索资料</p>
          <div class="welcome-prompts">
            <button
              v-for="(prompt, i) in quickPrompts"
              :key="i"
              class="prompt-card"
              @click="handleQuickPrompt(prompt.text)"
            >
              <span class="prompt-icon">{{ prompt.icon }}</span>
              <span class="prompt-text">{{ prompt.text }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- 消息列表 -->
      <div v-else ref="messagesRef" class="messages-container">
        <div class="messages-inner">
          <div
            v-for="msg in chatStore.messages"
            :key="msg.id"
            class="message-row"
            :class="msg.role"
          >
            <div class="message-body">
              <template v-if="msg.role === 'assistant'">
                <div v-if="msg.reasoning" class="reasoning-section">
                  <div class="reasoning-header" @click="toggleReasoning(msg.id)">
                    <span class="reasoning-label">思考过程</span>
                    <el-icon :size="12" class="expand-icon" :class="{ expanded: expandedReasoning.has(msg.id) }">
                      <ArrowDown />
                    </el-icon>
                  </div>
                  <div v-if="expandedReasoning.has(msg.id)" class="reasoning-body">
                    <MarkdownRenderer :content="msg.reasoning" />
                  </div>
                </div>
                <MarkdownRenderer :content="msg.content" class="message-text" />
              </template>
              <template v-else>
                <div class="message-text">{{ msg.content }}</div>
                <div v-if="getMessageAttachments(msg).length" class="message-attachments">
                  <template v-for="att in getMessageAttachments(msg)" :key="att.filename">
                    <div v-if="isImageFile(att.file_type) && att.id" class="image-card" @click="handleDownloadAttachment(att)">
                      <img
                        v-if="getImagePreviewUrl(att)"
                        :src="getImagePreviewUrl(att)"
                        class="image-thumb"
                        loading="lazy"
                      />
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
          <div v-if="chatStore.loading && !chatStore.isStreaming" class="typing-row">
            <div class="message-body">
              <div class="typing-bubble">
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区域：药丸形 -->
      <div class="input-area">
        <div class="input-pill">
          <button
            class="attach-btn"
            :disabled="chatStore.isStreaming || chatStore.loading || uploadingFiles"
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
            :disabled="chatStore.isStreaming || chatStore.loading"
            @keydown="handleKeydown"
            @input="autoResize"
          />
          <ModelFanSelector
            v-model="selectedModel"
            :models="availableModels"
            :default-model-name="defaultModelName"
          />
          <button
            v-if="chatStore.isStreaming"
            class="send-btn stop-btn"
            @click="handleCancelStream"
          >
            <el-icon :size="16"><VideoPause /></el-icon>
          </button>
          <button
            v-else
            class="send-btn"
            :class="{ active: inputText.trim() || chatStore.pendingAttachments.length > 0 }"
            :disabled="(!inputText.trim() && chatStore.pendingAttachments.length === 0) || chatStore.loading"
            @click="handleSend"
          >
            <el-icon :size="16"><Promotion /></el-icon>
          </button>
        </div>
        <!-- 文件预览 -->
        <div v-if="chatStore.pendingAttachments.length > 0" class="attachment-preview-bar">
          <div
            v-for="att in chatStore.pendingAttachments"
            :key="att.id"
            class="attachment-chip"
          >
            <img v-if="isImageFile(att.file_type) && getImagePreviewUrl(att)" :src="getImagePreviewUrl(att)" class="att-thumb-img" />
            <span v-else class="att-type-badge">{{ getFileIcon(att.file_type) }}</span>
            <span class="att-name">{{ att.filename }}</span>
            <span class="att-size">{{ formatFileSize(att.file_size) }}</span>
            <button class="att-remove" @click="chatStore.removePendingAttachment(att.id)">
              <el-icon :size="10"><Close /></el-icon>
            </button>
          </div>
        </div>
        <!-- 折叠设置栏 -->
        <div class="input-footer">
          <button class="settings-toggle" @click="settingsExpanded = !settingsExpanded">
            <el-icon :size="12"><Setting /></el-icon>
            <span>{{ settingsSummary }}</span>
            <el-icon :size="10" class="toggle-arrow" :class="{ expanded: settingsExpanded }"><ArrowDown /></el-icon>
          </button>
          <div class="input-hint-inline">Enter 发送 · Shift+Enter 换行</div>
        </div>
        <transition name="settings-slide">
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
              <button
                v-if="chatStore.currentSessionId"
                class="setting-group clickable"
                @click="handleOpenConfig(chatStore.currentSessionId)"
              >
                <span class="setting-label">会话设置</span>
                <el-icon :size="12"><ArrowRight /></el-icon>
              </button>
            </div>
          </div>
        </transition>
      </div>
    </div>

    <!-- 会话配置弹窗 -->
    <el-dialog v-model="configDialogVisible" title="会话配置" width="520px" append-to-body destroy-on-close>
      <el-form :model="configForm" label-width="120px">
        <el-form-item label="自动压缩长对话">
          <el-switch v-model="configForm.enable_compression" />
        </el-form-item>

        <el-form-item label="压缩策略">
          <el-select v-model="configForm.strategy" style="width: 100%" :disabled="!configForm.enable_compression">
            <el-option label="摘要压缩（需要 LLM）" value="summary" />
            <el-option label="滑动窗口" value="sliding_window" />
            <el-option label="保留最近" value="keep_recent" />
            <el-option label="截断" value="truncate" />
          </el-select>
        </el-form-item>

        <el-form-item label="压缩阈值">
          <el-input-number
            v-model="configForm.threshold"
            :min="500"
            :max="10000"
            :step="500"
            style="width: 100%"
            :disabled="!configForm.enable_compression"
          />
        </el-form-item>

        <el-form-item label="保留消息数">
          <el-input-number
            v-model="configForm.keep_recent"
            :min="0"
            :max="10"
            style="width: 100%"
            :disabled="!configForm.enable_compression"
          />
        </el-form-item>

        <el-form-item label="压缩后目标长度">
          <el-input-number
            v-model="configForm.target_tokens"
            :min="100"
            :max="2000"
            :step="100"
            style="width: 100%"
            :disabled="!configForm.enable_compression"
          />
        </el-form-item>

        <el-form-item label="摘要提示词">
          <el-input
            v-model="configForm.custom_prompt"
            type="textarea"
            :rows="3"
            placeholder="自定义摘要生成提示词（可选）"
            maxlength="2000"
            :disabled="!configForm.enable_compression || configForm.strategy !== 'summary'"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="configDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="configSaving" @click="handleSaveConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, nextTick, onMounted, onBeforeUnmount, watch, inject } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Setting, Promotion, VideoPause, DocumentCopy, ArrowRight, ArrowDown, Paperclip, Close, Document, Download } from '@element-plus/icons-vue'
// Note: Setting is still used in settings toggle button
import { useChatStore } from '@/stores/chat'
import { chatApi } from '@/api/chat'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import ModelFanSelector from '@/components/common/ModelFanSelector.vue'

const chatStore = useChatStore()
const isInWorkspace = inject('isInWorkspace', false)

const inputText = ref('')
const useStream = ref(true)
const enableThinking = ref(false)
const settingsExpanded = ref(false)
const expandedReasoning = ref(new Set<number>())
const messagesRef = ref<HTMLElement>()
const textareaRef = ref<HTMLTextAreaElement>()
const fileInputRef = ref<HTMLInputElement>()
const uploadingFiles = ref(false)

const quickPrompts = [
  { icon: '💡', text: '帮我分析一下这段代码的逻辑' },
  { icon: '📝', text: '写一篇关于人工智能发展趋势的摘要' },
  { icon: '🔍', text: '帮我从知识库中搜索相关资料' },
  { icon: '🛠️', text: '如何优化数据库查询性能？' },
]

function toggleReasoning(msgId: number) {
  if (expandedReasoning.value.has(msgId)) {
    expandedReasoning.value.delete(msgId)
  } else {
    expandedReasoning.value.add(msgId)
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

function autoResize() {
  nextTick(() => {
    const el = textareaRef.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  })
}

watch(() => chatStore.messages.length, () => {
  scrollToBottom()
})
watch(() => chatStore.streamingContent, () => scrollToBottom())
watch(() => chatStore.loading, () => scrollToBottom())
watch(() => chatStore.pendingAttachments.length, () => {
  for (const att of chatStore.pendingAttachments) {
    if (isImageFile(att.file_type) && att.id && !imageBlobCache.has(att.id)) {
      loadAttachmentImage(att.id)
    }
  }
})

function handleQuickPrompt(text: string) {
  inputText.value = text
  handleSend()
}

async function handleNewSession() {
  chatStore.clearMessages()
}

async function handleSelectSession(sessionId: string) {
  if (chatStore.currentSessionId === sessionId) return
  await chatStore.fetchMessages(sessionId)
  chatStore.fetchSessionConfig(sessionId)
  scrollToBottom()
}

async function handleDeleteSession(sessionId: string) {
  try {
    await ElMessageBox.confirm('确定删除此对话？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await chatStore.deleteSession(sessionId)
    ElMessage.success('对话已删除')
  } catch {
    // cancelled
  }
}

async function handleSend() {
  const content = inputText.value.trim()
  const hasAttachments = chatStore.pendingAttachments.length > 0
  if (!content && !hasAttachments) return

  const sendContent = content || (hasAttachments ? '请分析上传的文档' : '')
  inputText.value = ''
  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.style.height = 'auto'
    }
  })

  const attachmentIds = chatStore.pendingAttachments.map(a => a.id)
  const opts = {
    llm_model: selectedModel.value || undefined,
    enable_thinking: enableThinking.value,
    attachmentIds: attachmentIds.length > 0 ? attachmentIds : undefined,
  }

  try {
    if (useStream.value) {
      await chatStore.sendMessageStream(sendContent, opts)
    } else {
      await chatStore.sendMessage(sendContent, opts)
    }
  } catch {
    ElMessage.error('发送失败，请重试')
  }
}

function handleCancelStream() {
  chatStore.cancelStream()
}

function handleCopyMessage(content: string, e: MouseEvent) {
  navigator.clipboard.writeText(content).then(() => {
    const btn = (e.currentTarget as HTMLElement)
    btn.classList.add('copied')
    const label = btn.querySelector('span')!
    label.textContent = '已复制'
    setTimeout(() => {
      btn.classList.remove('copied')
      label.textContent = '复制'
    }, 2000)
  })
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

// 模型选择
const selectedModel = ref('')
const availableModels = ref<Record<string, { max_tokens: number; temperature: number; top_p: number; model_type: string }>>({})
const defaultModelName = computed(() => Object.keys(availableModels.value)[0] || '')

const llmModelNames = computed(() =>
  Object.entries(availableModels.value)
    .filter(([, v]) => v.model_type !== 'vlm')
    .map(([name]) => name),
)
const vlmModelNames = computed(() =>
  Object.entries(availableModels.value)
    .filter(([, v]) => v.model_type === 'vlm')
    .map(([name]) => name),
)

const settingsSummary = computed(() => {
  const model = selectedModel.value || defaultModelName.value || '默认'
  const parts = [model]
  if (enableThinking.value) parts.push('深度思考')
  return parts.join(' · ')
})

function triggerFileSelect() {
  fileInputRef.value?.click()
}

async function handleFileSelected(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files?.length) return

  const maxSize = 20 * 1024 * 1024
  const allowedTypes = ['pdf', 'docx', 'txt', 'md', 'jpg', 'jpeg', 'png', 'gif', 'webp']

  const validFiles: File[] = []
  for (const file of Array.from(input.files)) {
    const ext = file.name.split('.').pop()?.toLowerCase() || ''
    if (!allowedTypes.includes(ext)) {
      ElMessage.warning(`不支持的文件类型: .${ext}`)
      continue
    }
    if (file.size > maxSize) {
      ElMessage.warning(`文件过大: ${file.name}（最大 20MB）`)
      continue
    }
    validFiles.push(file)
  }

  if (validFiles.length) {
    uploadingFiles.value = true
    const results = await Promise.allSettled(validFiles.map(f => chatStore.uploadAttachment(f)))
    for (let i = 0; i < results.length; i++) {
      if (results[i].status === 'rejected') {
        ElMessage.error(`上传失败: ${validFiles[i].name}`)
      }
    }
    uploadingFiles.value = false
  }
  input.value = ''
}

function getFileIcon(type: string): string {
  const map: Record<string, string> = { pdf: 'PDF', docx: 'DOC', txt: 'TXT', md: 'MD', jpg: 'IMG', jpeg: 'IMG', png: 'IMG', gif: 'IMG', webp: 'IMG' }
  return map[type] || 'FILE'
}

function getMessageAttachments(msg: ChatMessage): Array<{ id?: number; filename: string; file_type?: string; file_size?: number; storage_path?: string }> {
  if (msg.attachments?.length) return msg.attachments
  return (msg.extra as Record<string, any>)?.attachments ?? []
}

function getFileIconClass(type?: string): string {
  if (!type) return 'file-default'
  const t = type.toLowerCase()
  if (t === 'pdf') return 'file-pdf'
  if (t === 'docx' || t === 'doc') return 'file-doc'
  if (t === 'txt') return 'file-txt'
  if (t === 'md') return 'file-md'
  if (isImageFile(t)) return 'file-image'
  return 'file-default'
}

const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'gif', 'webp'])
function isImageFile(type?: string): boolean {
  return !!type && IMAGE_EXTENSIONS.has(type.toLowerCase())
}

// 图片 blob URL 缓存
const imageBlobCache = new Map<number, string>()
const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

async function loadAttachmentImage(attId: number) {
  if (imageBlobCache.has(attId)) return
  try {
    const token = localStorage.getItem('access_token')
    const res = await fetch(`${baseURL}/ai-chat/chat-attachments/${attId}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) return
    const blob = await res.blob()
    imageBlobCache.set(attId, URL.createObjectURL(blob))
  } catch {
    // ignore
  }
}

function getImagePreviewUrl(att: { id?: number; preview_url?: string }): string {
  if (att.preview_url) return att.preview_url
  if (att.id) return imageBlobCache.get(att.id) || ''
  return ''
}

function getFileExt(filename?: string): string {
  if (!filename) return 'FILE'
  const ext = filename.split('.').pop()?.toUpperCase() || 'FILE'
  return ext
}

async function handleDownloadAttachment(att: { id?: number; filename: string }) {
  if (!att.id) return
  try {
    await chatApi.downloadAttachmentFile(att.id, att.filename)
  } catch {
    ElMessage.error('下载失败')
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

async function fetchModels() {
  try {
    const data = await chatApi.getModels()
    availableModels.value = data.models
  } catch {
    // ignore
  }
}

// ===================== 会话配置 =====================
const configDialogVisible = ref(false)
const configSaving = ref(false)
const configSessionId = ref('')
const configForm = reactive({
  enable_compression: true,
  strategy: 'summary' as 'summary' | 'sliding_window' | 'keep_recent' | 'truncate',
  threshold: 3000,
  keep_recent: 2,
  target_tokens: 500,
  custom_prompt: '',
})

async function handleOpenConfig(sessionId: string) {
  configSessionId.value = sessionId
  configDialogVisible.value = true
  try {
    await chatStore.fetchSessionConfig(sessionId)
    const cfg = chatStore.sessionConfig?.compression_config
    if (cfg) {
      configForm.enable_compression = cfg.enable_compression ?? true
      configForm.strategy = cfg.strategy || 'summary'
      configForm.threshold = cfg.threshold || 3000
      configForm.keep_recent = cfg.keep_recent ?? 2
      configForm.target_tokens = cfg.target_tokens || 500
      configForm.custom_prompt = cfg.custom_prompt || ''
    }
  } catch {
    // use defaults
  }
}

async function handleSaveConfig() {
  configSaving.value = true
  try {
    if (chatStore.sessionConfig) {
      await chatStore.deleteSessionConfig(configSessionId.value)
    }
    await chatStore.saveSessionConfig(configSessionId.value, {
      enable_compression: configForm.enable_compression,
      strategy: configForm.strategy,
      threshold: configForm.threshold,
      keep_recent: configForm.keep_recent,
      target_tokens: configForm.target_tokens,
      custom_prompt: configForm.custom_prompt || undefined,
    })
    ElMessage.success('配置已保存')
    configDialogVisible.value = false
  } catch {
    ElMessage.error('保存配置失败')
  } finally {
    configSaving.value = false
  }
}

onMounted(() => {
  chatStore.fetchSessions()
  fetchModels()
})

onBeforeUnmount(() => {
  for (const url of imageBlobCache.values()) {
    URL.revokeObjectURL(url)
  }
  imageBlobCache.clear()
})
</script>

<style scoped>
/* ========================================
   Layout
   ======================================== */
.chat-view {
  position: absolute;
  inset: 0;
  display: flex;
  background: var(--color-bg-card);
  overflow: hidden;
}

/* ========================================
   Sidebar
   ======================================== */
.chat-sidebar {
  width: 260px;
  border-right: 1px solid var(--color-border-light);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  background: var(--color-bg-card);
}

.sidebar-top {
  padding: var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
  display: flex;
  align-items: center;
}

.new-chat-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-lg);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-base);
}

.new-chat-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-muted);
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

.session-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
  margin-bottom: 2px;
  position: relative;
}

.session-item:hover {
  background: var(--color-bg-hover);
}

.session-item.active {
  background: var(--color-primary-muted);
}

.session-item.active .session-title {
  color: var(--color-primary);
  font-weight: var(--weight-medium);
}

.session-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  border-radius: 2px;
  background: var(--color-primary);
}

.session-title {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: var(--leading-normal);
}

.session-delete {
  opacity: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.session-item:hover .session-delete {
  opacity: 1;
}

.session-delete:hover {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

.sidebar-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-faint);
}

/* ========================================
   Main Chat Area
   ======================================== */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--color-bg-card);
}

/* ========================================
   Welcome Screen (Empty State)
   ======================================== */
.welcome-screen {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8);
}

.welcome-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  max-width: 720px;
  width: 100%;
}

.welcome-title {
  font-family: var(--font-display);
  font-size: 32px;
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin-bottom: var(--space-3);
  letter-spacing: var(--tracking-tight);
  text-align: center;
}

.welcome-subtitle {
  font-size: var(--text-base);
  color: var(--color-text-muted);
  margin-bottom: var(--space-8);
  text-align: center;
  line-height: var(--leading-relaxed);
}

.welcome-prompts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
  width: 100%;
}

.prompt-card {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border: 1px solid transparent;
  border-radius: var(--radius-lg);
  background: transparent;
  cursor: pointer;
  transition: all var(--transition-base);
  text-align: left;
  font-family: var(--font-body);
}

.prompt-card:hover {
  border-color: var(--color-border);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-sm);
}

.prompt-card:hover .prompt-text {
  color: var(--color-text);
}

.prompt-icon {
  font-size: 18px;
  flex-shrink: 0;
  margin-top: 1px;
}

.prompt-text {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  line-height: var(--leading-normal);
  transition: color var(--transition-fast);
}

/* ========================================
   Messages
   ======================================== */
.messages-container {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scroll-behavior: smooth;
}

.messages-inner {
  max-width: 860px;
  margin: 0 auto;
  padding: var(--space-6) var(--space-6) var(--space-4);
}

.message-row {
  display: flex;
  gap: var(--space-4);
  margin-bottom: 28px;
  animation: messageIn 0.35s ease forwards;
}

@keyframes messageIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

.message-row.user {
  justify-content: flex-end;
}

.message-body {
  max-width: 75%;
  min-width: 0;
}

.message-text {
  font-size: var(--text-base);
  line-height: var(--leading-relaxed);
  word-break: break-word;
}

/* User message */
.message-row.user .message-text {
  padding: var(--space-3) var(--space-4);
  border-radius: 18px 18px 4px 18px;
  background: #dbeafe;
  color: #1e3a5f;
  white-space: pre-wrap;
}

/* AI message */
.message-row.assistant .message-text {
  padding: var(--space-4) var(--space-5);
  border-radius: 18px 18px 18px 4px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
}

/* Reasoning section */
.reasoning-section {
  margin-bottom: 8px;
  border-radius: 10px;
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border-light);
  overflow: hidden;
}
.reasoning-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
  color: var(--color-text-secondary);
}
.reasoning-header:hover {
  background: var(--color-bg-hover);
}
.reasoning-label {
  font-weight: 500;
}
.expand-icon {
  transition: transform 0.2s;
}
.expand-icon.expanded {
  transform: rotate(180deg);
}
.reasoning-body {
  padding: 8px 12px 12px;
  border-top: 1px solid var(--color-border-light);
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  max-height: 400px;
  overflow-y: auto;
}

/* Message actions bar */
.message-actions {
  display: flex;
  gap: var(--space-2);
  padding: 2px 2px 0;
  opacity: 0;
  transition: opacity var(--transition-fast);
}

.message-row:hover .message-actions {
  opacity: 1;
}

.msg-copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  font-family: var(--font-body);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  transition: all var(--transition-fast);
}

.msg-copy-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}

.msg-copy-btn.copied {
  color: var(--color-success);
}

/* Typing indicator */
.typing-row {
  display: flex;
  gap: var(--space-4);
  margin-bottom: 28px;
  animation: messageIn 0.35s ease forwards;
}

.typing-bubble {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: 18px 18px 18px 4px;
}

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
  border: 1px solid var(--color-border-light);
  border-radius: 24px;
  box-shadow: var(--shadow-sm);
  transition: border-color var(--transition-base), box-shadow var(--transition-base);
}

.input-pill:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-muted), var(--shadow-sm);
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
  background: var(--color-border-light);
  color: var(--color-text-faint);
  cursor: not-allowed;
  transition: all var(--transition-base);
  flex-shrink: 0;
}

.send-btn.active {
  background: var(--color-primary);
  color: #FFFFFF;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.25);
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
  border: 1px solid var(--color-border-light);
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
  border: 1px solid var(--color-border-light);
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
   Message Attachments — File Card
   ======================================== */
.message-attachments {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 6px;
}

.file-card {
  display: flex;
  align-items: center;
  width: 260px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.55);
  box-sizing: border-box;
  cursor: pointer;
  transition: background 0.15s;
}

.file-card:hover {
  background: rgba(255, 255, 255, 0.7);
}

.file-card .file-icon-box {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 10px;
  flex-shrink: 0;
}

.file-icon-box .file-ext-label {
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 0.3px;
}

.file-icon-box.file-pdf  { background: #ef4444; }
.file-icon-box.file-doc  { background: #3b82f6; }
.file-icon-box.file-txt  { background: #8b5cf6; }
.file-icon-box.file-md   { background: #06b6d4; }
.file-icon-box.file-default { background: #6b7280; }

.file-card .file-info {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.file-card .file-name {
  font-size: 13px;
  color: #1e3a5f;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-card .file-meta {
  font-size: 11px;
  color: #5b7a9d;
  margin-top: 2px;
}

.file-card .file-download-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: #5b7a9d;
  flex-shrink: 0;
  margin-left: 4px;
  transition: all 0.15s;
}

.file-card:hover .file-download-btn {
  color: #1e3a5f;
  background: rgba(0, 0, 0, 0.06);
}

/* ===== Image card in messages ===== */
.image-card {
  display: inline-flex;
  flex-direction: column;
  cursor: pointer;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--color-border-light);
  max-width: 200px;
  transition: border-color 0.15s;
}
.image-card:hover {
  border-color: var(--color-primary);
}
.image-thumb {
  width: 100%;
  max-height: 150px;
  object-fit: cover;
  display: block;
}
.image-thumb-loading {
  height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-hover);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}
.image-info {
  padding: 4px 8px;
  display: flex;
  gap: 6px;
  align-items: center;
  background: var(--color-bg-card);
}
.image-name {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.image-size {
  font-size: 10px;
  color: var(--color-text-muted);
  flex-shrink: 0;
}

/* ===== Pending attachment image thumb ===== */
.att-thumb-img {
  width: 28px;
  height: 28px;
  object-fit: cover;
  border-radius: 4px;
  flex-shrink: 0;
}

/* ===== Image file icon ===== */
.file-image {
  background: linear-gradient(135deg, #43e97b, #38f9d7);
  color: #fff;
}
</style>
