<template>
  <div class="agent-chat-view">
    <!-- 左侧：会话列表 -->
    <div class="chat-sidebar" :class="{ compact: isInWorkspace }">
      <div class="sidebar-top">
        <button class="back-btn" @click="goBack">
          <el-icon :size="14"><ArrowLeft /></el-icon>
          <span>返回</span>
        </button>
        <button class="new-chat-btn" @click="handleNewChat">
          <el-icon :size="16"><Plus /></el-icon>
          <span>新对话</span>
        </button>
      </div>
      <div class="conversation-list">
        <div
          v-for="conv in agentStore.conversations"
          :key="conv.session_id"
          class="conv-item"
          :class="{ active: agentStore.currentSessionId === conv.session_id }"
          @click="handleSelectConversation(conv.session_id)"
        >
          <span class="conv-title">{{ conv.title || '新对话' }}</span>
          <button class="conv-delete" @click.stop="handleDeleteConversation(conv.session_id)">
            <el-icon :size="12"><Delete /></el-icon>
          </button>
        </div>
        <div v-if="agentStore.conversations.length === 0 && !agentStore.conversationsLoading" class="sidebar-empty">
          <span>暂无对话</span>
        </div>
      </div>
    </div>

    <!-- 右侧：对话区域 -->
    <div class="chat-main">
      <!-- 浮动头部 -->
      <header class="chat-header" :class="{ 'is-welcome': isWelcomeMode }">
        <div class="header-left">
          <div v-if="!isWelcomeMode" class="header-agent-badge">
            <div class="badge-avatar">{{ agentName.charAt(0) }}</div>
            <span class="header-title">{{ agentName }}</span>
          </div>
        </div>
      </header>

      <!-- 消息列表 (仅对话模式) -->
      <div v-if="!isWelcomeMode" ref="messagesRef" class="messages-container">
        <div class="messages-inner">
          <template v-for="msg in agentStore.messages" :key="msg.id">
            <!-- tool 消息：显示为工具调用卡片 -->
            <div v-if="msg.role === 'tool'" class="tool-card-row">
              <div class="tool-card">
                <div class="tool-header" @click="toggleToolExpand(msg.id)">
                  <div class="tool-info">
                    <span class="tool-icon">
                      <el-icon :size="14"><SetUp /></el-icon>
                    </span>
                    <span class="tool-name">{{ msg.tool_name || 'Tool' }}</span>
                    <span v-if="getToolDuration(msg.tool_call_id)" class="tool-duration">
                      {{ getToolDuration(msg.tool_call_id) }}ms
                    </span>
                    <span class="tool-status" :class="getToolStatus(msg.tool_call_id)">
                      {{ getToolStatusLabel(msg.tool_call_id) }}
                    </span>
                  </div>
                  <el-icon :size="12" class="expand-icon" :class="{ expanded: expandedTools.has(msg.id) }">
                    <ArrowDown />
                  </el-icon>
                </div>
                <div v-if="expandedTools.has(msg.id)" class="tool-body">
                  <div v-if="getToolArgs(msg.tool_call_id)" class="tool-section">
                    <div class="tool-section-label">参数</div>
                    <pre class="tool-json">{{ formatJson(getToolArgs(msg.tool_call_id)!) }}</pre>
                  </div>
                  <div v-if="msg.content" class="tool-section">
                    <div class="tool-section-label">结果</div>
                    <pre class="tool-json">{{ truncateResult(msg.content) }}</pre>
                  </div>
                </div>
              </div>
            </div>

            <!-- 用户消息 -->
            <div v-else-if="msg.role === 'user'" class="message-row user">
              <div class="message-body">
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
              </div>
            </div>

            <!-- AI 消息 -->
            <div v-else-if="msg.role === 'assistant' && msg.content" class="message-row assistant">
              <div class="message-body">
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
                <div class="message-actions">
                  <button class="msg-copy-btn" @click="handleCopyMessage(msg.content!, $event)">
                    <el-icon :size="13"><DocumentCopy /></el-icon>
                    <span>复制</span>
                  </button>
                </div>
              </div>
            </div>
          </template>

          <!-- 流式模式：等待首个 token 的 typing 指示器 -->
          <div v-if="agentStore.isStreaming && !agentStore.streamingContent" class="typing-row">
            <div class="message-body">
              <div class="typing-bubble">
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
              </div>
            </div>
          </div>
          <!-- 非流式模式：loading 指示器 -->
          <div v-else-if="agentStore.loading" class="typing-row">
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

      <!-- 输入区域 -->
      <div class="input-area" :class="{ 'is-welcome': isWelcomeMode }">
        <div class="input-area-inner" :class="{ 'welcome-center': isWelcomeMode }">
          <!-- 欢迎问候 (仅欢迎模式) -->
          <div v-if="isWelcomeMode" class="welcome-greeting">
            <div class="welcome-avatar">{{ agentName.charAt(0) }}</div>
            <h2 class="welcome-title">{{ agentName }}</h2>
            <p class="welcome-desc">{{ agentStore.currentAgent?.description || '智能体对话' }}</p>
            <div class="welcome-prompts">
              <button
                v-for="(prompt, i) in quickPrompts"
                :key="i"
                class="prompt-card"
                @click="handleQuickPrompt(prompt)"
              >
                <span class="prompt-text">{{ prompt }}</span>
              </button>
            </div>
          </div>

          <div class="input-pill">
          <button
            class="attach-btn"
            :disabled="agentStore.isStreaming || agentStore.loading || uploadingFiles"
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
            placeholder="输入消息..."
            :rows="1"
            :disabled="agentStore.isStreaming || agentStore.loading"
            @keydown="handleKeydown"
            @input="autoResize"
          />
          <ModelFanSelector
            v-model="selectedModel"
            :models="availableModels"
            :default-model-name="defaultModelName"
          />
          <button
            v-if="agentStore.isStreaming"
            class="send-btn stop-btn"
            @click="handleCancelStream"
          >
            <el-icon :size="16"><VideoPause /></el-icon>
          </button>
          <button
            v-else
            class="send-btn"
            :class="{ active: inputText.trim() || agentStore.pendingAttachments.length > 0 }"
            :disabled="(!inputText.trim() && agentStore.pendingAttachments.length === 0) || agentStore.loading"
            @click="handleSend"
          >
            <el-icon :size="16"><Promotion /></el-icon>
          </button>
        </div>
        <!-- 文件预览 -->
        <div v-if="agentStore.pendingAttachments.length > 0" class="attachment-preview-bar">
          <div
            v-for="att in agentStore.pendingAttachments"
            :key="att.id"
            class="attachment-chip"
          >
            <img v-if="isImageFile(att.file_type) && getImagePreviewUrl(att)" :src="getImagePreviewUrl(att)" class="att-thumb-img" />
            <span v-else class="att-type-badge">{{ getFileIcon(att.file_type) }}</span>
            <span class="att-name">{{ att.filename }}</span>
            <span class="att-size">{{ formatFileSize(att.file_size) }}</span>
            <button class="att-remove" @click="agentStore.removePendingAttachment(att.id)">
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
            </div>
          </div>
        </transition>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch, inject } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, ArrowLeft, ArrowDown, SetUp, Setting, Promotion, VideoPause, DocumentCopy, Paperclip, Close, Document, Download } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import { agentApi } from '@/api/agent'
import { chatApi } from '@/api/chat'
import type { AgentMessage } from '@/api/types'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import ModelFanSelector from '@/components/common/ModelFanSelector.vue'

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const isInWorkspace = inject('isInWorkspace', false)

const agentId = computed(() => Number(route.params.agentId))
const agentName = computed(() => agentStore.currentAgent?.name || '智能体')
const isWelcomeMode = computed(() => agentStore.messages.length === 0 && !agentStore.messagesLoading)

const inputText = ref('')
const useStream = ref(true)
const enableThinking = ref(false)
const settingsExpanded = ref(false)
const expandedReasoning = ref(new Set<number>())
const messagesRef = ref<HTMLElement>()
const fileInputRef = ref<HTMLInputElement>()
const uploadingFiles = ref(false)

// 模型选择
const selectedModel = ref('')
const availableModels = ref<Record<string, { max_tokens: number; temperature: number; top_p: number; model_type: string }>>({})
const defaultModelName = computed(() => Object.keys(availableModels.value)[0] || '')

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
    const results = await Promise.allSettled(validFiles.map(f => agentStore.uploadAttachment(f)))
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

function getMessageAttachments(msg: AgentMessage): Array<{ id?: number; filename: string; file_type?: string; file_size?: number; storage_path?: string }> {
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
  return filename.split('.').pop()?.toUpperCase() || 'FILE'
}

async function handleDownloadAttachment(att: { id?: number; filename: string }) {
  if (!att.id) return
  try {
    await agentApi.downloadAttachmentFile(att.id, att.filename)
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

const textareaRef = ref<HTMLTextAreaElement>()
const expandedTools = ref(new Set<number>())

const quickPrompts = [
  '你好，你能帮我做什么？',
  '帮我搜索知识库中的相关内容',
  '分析一下这个问题的原因',
  '总结一下要点',
]

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

watch(() => agentStore.messages.length, () => {
  scrollToBottom()
})
watch(() => agentStore.streamingContent, () => scrollToBottom())
watch(() => agentStore.loading, () => scrollToBottom())
watch(() => agentStore.pendingAttachments.length, () => {
  for (const att of agentStore.pendingAttachments) {
    if (isImageFile(att.file_type) && att.id && !imageBlobCache.has(att.id)) {
      loadAttachmentImage(att.id)
    }
  }
})

function goBack() {
  if (isInWorkspace) {
    router.push({ name: 'WorkspaceAgents' })
  } else {
    router.push({ name: 'Agents' })
  }
}

function handleNewChat() {
  agentStore.clearChat()
}

async function handleSelectConversation(sessionId: string) {
  if (agentStore.currentSessionId === sessionId) return
  await agentStore.fetchMessages(sessionId)
  scrollToBottom()
}

async function handleDeleteConversation(sessionId: string) {
  try {
    await ElMessageBox.confirm('确定删除此对话？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await agentStore.deleteConversation(sessionId)
    ElMessage.success('对话已删除')
  } catch {
    // cancelled
  }
}

function handleQuickPrompt(text: string) {
  inputText.value = text
  handleSend()
}

function toggleReasoning(msgId: number) {
  if (expandedReasoning.value.has(msgId)) {
    expandedReasoning.value.delete(msgId)
  } else {
    expandedReasoning.value.add(msgId)
  }
}

async function handleSend() {
  const content = inputText.value.trim()
  const hasAttachments = agentStore.pendingAttachments.length > 0
  if (!content && !hasAttachments) return

  const sendContent = content || (hasAttachments ? '请分析上传的文档' : '')
  inputText.value = ''
  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.style.height = 'auto'
    }
  })

  try {
    const attachmentIds = agentStore.pendingAttachments.map(a => a.id)
    const opts = {
      ...(selectedModel.value ? { llm_model: selectedModel.value } : {}),
      enable_thinking: enableThinking.value,
      attachmentIds: attachmentIds.length > 0 ? attachmentIds : undefined,
    }
    if (useStream.value) {
      await agentStore.sendMessageStream(agentId.value, sendContent, opts)
    } else {
      await agentStore.sendMessage(agentId.value, sendContent, opts)
    }
  } catch {
    ElMessage.error('发送失败，请重试')
  }
}

function handleCancelStream() {
  agentStore.cancelStream()
}

function handleCopyMessage(content: string, e: MouseEvent) {
  navigator.clipboard.writeText(content).then(() => {
    const btn = e.currentTarget as HTMLElement
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

// Tool call helpers
function getToolRecord(callId: string | null) {
  if (!callId) return null
  return agentStore.toolCalls.find((c) => c.callId === callId)
}

function getToolDuration(callId: string | null) {
  return getToolRecord(callId)?.durationMs
}

function getToolStatus(callId: string | null) {
  return getToolRecord(callId)?.status || 'running'
}

function getToolStatusLabel(callId: string | null) {
  const status = getToolStatus(callId)
  const map: Record<string, string> = { running: '执行中', completed: '完成', failed: '失败', pending: '等待中' }
  return map[status] || status
}

function getToolArgs(callId: string | null) {
  return getToolRecord(callId)?.arguments
}

function toggleToolExpand(msgId: number) {
  if (expandedTools.value.has(msgId)) {
    expandedTools.value.delete(msgId)
  } else {
    expandedTools.value.add(msgId)
  }
}

function formatJson(obj: Record<string, unknown>): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

function truncateResult(text: string): string {
  if (text.length <= 2000) return text
  return text.slice(0, 2000) + '\n... (已截断)'
}

onMounted(async () => {
  await Promise.all([
    agentStore.initForAgent(agentId.value),
    fetchModels(),
  ])
})

onBeforeUnmount(() => {
  for (const url of imageBlobCache.values()) {
    URL.revokeObjectURL(url)
  }
  imageBlobCache.clear()
})
</script>

<style scoped>
.agent-chat-view {
  position: absolute;
  inset: 0;
  display: flex;
  background: var(--color-bg-card);
  overflow: hidden;
  z-index: 1;
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

.chat-sidebar.compact {
  width: 220px;
}

.sidebar-top {
  padding: var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-base);
}

.back-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.new-chat-btn {
  flex: 1;
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

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

.conv-item {
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

.conv-item:hover {
  background: var(--color-bg-hover);
}

.conv-item.active {
  background: var(--color-primary-muted);
}

.conv-item.active .conv-title {
  color: var(--color-primary);
  font-weight: var(--weight-medium);
}

.conv-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  border-radius: 2px;
  background: var(--color-primary);
}

.conv-title {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: var(--leading-normal);
}

.conv-delete {
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

.conv-item:hover .conv-delete {
  opacity: 1;
}

.conv-delete:hover {
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
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--color-bg-card);
}

/* ========================================
   Floating Chat Header
   ======================================== */
.chat-header {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  z-index: 3;
  height: 48px;
  display: flex;
  align-items: center;
  padding: 0 var(--space-5);
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: var(--shadow-xs);
  transition: all var(--transition-base);
}

.chat-header.is-welcome {
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  box-shadow: none;
}

.header-agent-badge {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.badge-avatar {
  width: 24px;
  height: 24px;
  border-radius: var(--radius-md);
  background: var(--color-primary-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: var(--weight-bold);
  color: var(--color-primary);
}

.header-title {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
}

/* ========================================
   Welcome Greeting (inside input-area)
   ======================================== */
.welcome-greeting {
  text-align: center;
  margin-bottom: var(--space-6);
}

.welcome-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  max-width: var(--container-width-sm);
  width: 100%;
}

.welcome-avatar {
  width: 64px;
  height: 64px;
  border-radius: var(--radius-xl);
  background: var(--color-primary-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-primary);
  margin-bottom: var(--space-5);
  box-shadow: var(--shadow-md);
}

.welcome-title {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin-bottom: var(--space-2);
}

.welcome-desc {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-bottom: var(--space-6);
  text-align: center;
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
  padding: var(--space-3) var(--space-4);
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

.prompt-text {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  line-height: var(--leading-normal);
  transition: color var(--transition-fast);
}

.prompt-card:hover .prompt-text {
  color: var(--color-text);
}

/* ========================================
   Messages
   ======================================== */
.messages-container {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scroll-behavior: smooth;
  padding-top: 48px;
}

.messages-inner {
  max-width: var(--container-width-md);
  margin: 0 auto;
  padding: var(--space-6) var(--space-6) var(--space-4);
}

.message-row {
  display: flex;
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
  background: var(--color-user-bubble);
  color: var(--color-user-bubble-text);
  white-space: pre-wrap;
}

/* ========================================
   Message Attachments — File Card
   ======================================== */
.message-attachments {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.file-card {
  display: flex;
  align-items: center;
  width: 260px;
  padding: var(--space-3);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  box-sizing: border-box;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.file-card:hover {
  background: var(--color-bg-hover);
}

.file-card .file-icon-box {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: var(--space-3);
  flex-shrink: 0;
}

.file-icon-box .file-ext-label {
  font-size: 11px;
  font-weight: var(--weight-bold);
  color: #fff;
  letter-spacing: 0.3px;
}

.file-icon-box.file-pdf  { background: var(--color-file-pdf); }
.file-icon-box.file-doc  { background: var(--color-file-doc); }
.file-icon-box.file-txt  { background: var(--color-file-txt); }
.file-icon-box.file-md   { background: var(--color-file-md); }
.file-icon-box.file-default { background: var(--color-file-other); }

.file-card .file-info {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.file-card .file-name {
  font-size: var(--text-sm);
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-card .file-meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-top: var(--space-1);
}

.file-card .file-download-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  color: var(--color-text-muted);
  flex-shrink: 0;
  margin-left: var(--space-1);
  transition: all var(--transition-fast);
}

.file-card:hover .file-download-btn {
  color: var(--color-text);
  background: var(--color-bg-hover);
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
  margin-bottom: var(--space-2);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border-light);
  overflow: hidden;
}
.reasoning-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  cursor: pointer;
  user-select: none;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
.reasoning-header:hover {
  background: var(--color-bg-hover);
}
.reasoning-label {
  font-weight: var(--weight-medium);
}
.expand-icon {
  transition: transform var(--transition-fast);
}
.expand-icon.expanded {
  transform: rotate(180deg);
}
.reasoning-body {
  padding: var(--space-2) var(--space-3) var(--space-3);
  border-top: 1px solid var(--color-border-light);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  max-height: 400px;
  overflow-y: auto;
}

/* Message actions */
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

/* ========================================
   Tool Call Cards
   ======================================== */
.tool-card-row {
  margin-bottom: var(--space-4);
  animation: messageIn 0.35s ease forwards;
}

.tool-card {
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card-elevated);
  overflow: hidden;
  max-width: 600px;
}

.tool-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.tool-header:hover {
  background: var(--color-bg-hover);
}

.tool-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.tool-icon {
  display: flex;
  align-items: center;
  color: var(--color-info);
}

.tool-name {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
}

.tool-duration {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.tool-status {
  font-size: var(--text-xs);
  padding: 1px 6px;
  border-radius: var(--radius-full);
}

.tool-status.running {
  background: var(--color-warning-subtle);
  color: var(--color-warning);
}

.tool-status.completed {
  background: var(--color-success-subtle);
  color: var(--color-success);
}

.tool-status.failed {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

.expand-icon {
  color: var(--color-text-muted);
  transition: transform var(--transition-fast);
}

.expand-icon.expanded {
  transform: rotate(180deg);
}

.tool-body {
  border-top: 1px solid var(--color-border-light);
  padding: var(--space-3) var(--space-4);
}

.tool-section {
  margin-bottom: var(--space-3);
}

.tool-section:last-child {
  margin-bottom: 0;
}

.tool-section-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-bottom: var(--space-1);
}

.tool-json {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  background: var(--color-bg);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
  margin: 0;
}

/* ========================================
   Typing Indicator
   ======================================== */
.typing-row {
  display: flex;
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

.typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-text-faint);
  animation: dotPulse 1.4s ease-in-out infinite;
}

.typing-dot:nth-child(2) { animation-delay: 0.2s; }
.typing-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes dotPulse {
  0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); }
  30% { opacity: 1; transform: scale(1); }
}

/* ========================================
   Input Area — Pill Shape
   ======================================== */
.input-area {
  flex-shrink: 0;
  padding: 0 var(--space-6) var(--space-5);
  background: var(--color-bg-card);
  position: relative;
}

.input-area.is-welcome {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 3;
  padding: 0 var(--space-4);
  background: transparent;
}

.input-area-inner {
  max-width: var(--container-width-md);
  margin: 0 auto;
}

.input-area-inner.welcome-center {
  max-width: var(--container-width-sm);
  transform: translateY(calc(-50vh + 96px));
}

.input-pill {
  display: flex;
  align-items: flex-end;
  padding: var(--space-2) var(--space-3);
  gap: var(--space-2);
  background: var(--color-bg-input-bar);
  backdrop-filter: blur(var(--blur-input));
  -webkit-backdrop-filter: blur(var(--blur-input));
  border: 1px solid var(--color-border-light);
  border-radius: 24px;
  box-shadow: var(--shadow-sm);
  transition: border-color var(--transition-base), box-shadow var(--transition-base);
}

.input-pill:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-muted), var(--shadow-sm);
}

.input-action-btn {
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

.input-action-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
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

.input-hint {
  margin: 8px auto 0;
  text-align: center;
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

/* ========================================
   Input Footer — Settings Toggle
   ======================================== */
.input-footer {
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

/* ========================================
   Attachment Button & Preview
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

.attachment-preview-bar {
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

.att-thumb-img {
  width: 28px;
  height: 28px;
  object-fit: cover;
  border-radius: 4px;
  flex-shrink: 0;
}

.file-image {
  background: linear-gradient(135deg, #43e97b, #38f9d7);
  color: #fff;
}
</style>
