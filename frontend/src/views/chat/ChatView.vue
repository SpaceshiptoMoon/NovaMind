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
        </div>
      </div>

      <!-- 消息列表 -->
      <div v-else ref="messagesRef" class="messages-container">
        <MessageList
          :messages="chatStore.messages"
          :is-streaming="chatStore.isStreaming"
          :loading="chatStore.loading"
        />
      </div>

      <!-- 输入区域 -->
      <ChatInput
        :disabled="chatStore.isStreaming || chatStore.loading"
        :pending-attachments-count="chatStore.pendingAttachments.length"
        :available-models="availableModels"
        :default-model-name="defaultModelName"
        :selected-model="selectedModel"
        @send="handleSend"
        @cancel-stream="handleCancelStream"
        @open-config="openSessionConfig"
        @update:selected-model="selectedModel = $event"
      />
    </div>

    <!-- 会话配置弹窗 -->
    <SessionConfigDialog :sessionId="configSessionId" />

  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, nextTick, onMounted, onBeforeUnmount, watch, inject } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Setting, Promotion, VideoPause, DocumentCopy, ArrowRight, ArrowDown, Paperclip, Close, Document, Download, WarningFilled } from '@element-plus/icons-vue'
// Note: Setting is still used in settings toggle button
import { useChatStore } from '@/stores/chat'
import { chatApi } from '@/api/chat'
import { sessionApi } from '@/api/session'
import { useSpaceStore } from '@/stores/space'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import SourceList from '@/components/chat/SourceList.vue'
import type { ChatMessage, ChatSource } from '@/api/types'
import { useChatAttachments } from '@/composables/useChatAttachments'
import SessionConfigDialog from '@/components/chat/SessionConfigDialog.vue'
import MessageList from '@/components/chat/MessageList.vue'
import ChatInput from '@/components/chat/ChatInput.vue'

const chatStore = useChatStore()
const spaceStore = useSpaceStore()
const isInWorkspace = inject('isInWorkspace', false)

const inputText = ref('')
const useStream = ref(true)
const enableThinking = ref(false)
const enableWebSearch = ref(false)
const messagesRef = ref<HTMLElement>()



function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}


watch(() => chatStore.messages.length, () => {
  scrollToBottom()
})
let scrollRAF = 0
watch(() => chatStore.streamingContent, () => {
  if (!scrollRAF) {
    scrollRAF = requestAnimationFrame(() => {
      scrollToBottom()
      scrollRAF = 0
    })
  }
})
watch(() => chatStore.loading, () => scrollToBottom())
watch(() => chatStore.pendingAttachments.length, () => {
  for (const att of chatStore.pendingAttachments) {
    if (isImageFile(att.file_type) && att.id && !imageBlobCache.has(att.id)) {
      loadAttachmentImage(att.id)
    }
  }
})


async function handleNewSession() {
  chatStore.clearMessages()
}

async function openSessionConfig() {
  // 新对话无 session_id 时预先生成，配置绑到它；
  // 发消息时后端用同一 id 建会话（ensure_session_config 发现配置已存在直接复用）。
  if (!chatStore.currentSessionId) {
    chatStore.currentSessionId = crypto.randomUUID()
  }
  configSessionId.value = chatStore.currentSessionId

function openSessionConfig() {
  configSessionId.value = ''
  nextTick(() => {
    configSessionId.value = chatStore.currentSessionId
  })
}
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

async function handleSend(content: string, options: { useStream: boolean; enableThinking: boolean; enableWebSearch: boolean }) {
  const attachmentIds = chatStore.pendingAttachments.map(a => a.id)
  const opts = {
    llm_model: selectedModel.value || undefined,
    enable_thinking: options.enableThinking,
    enable_web_search: options.enableWebSearch || undefined,
    attachmentIds: attachmentIds.length > 0 ? attachmentIds : undefined,
  }

  try {
    if (options.useStream) {
      await chatStore.sendMessageStream(content, opts)
    } else {
      await chatStore.sendMessage(content, opts)
    }
  } catch {
    ElMessage.error('发送失败，请重试')
  }
}

function handleCancelStream() {
  chatStore.cancelStream()
}



// 模型选择
const selectedModel = ref('')
const availableModels = ref<Record<string, { max_tokens: number; temperature: number; top_p: number; model_type: string }>>({})
const defaultModelName = computed(() => Object.keys(availableModels.value)[0] || '')





const {
  isImageFile,
  imageBlobCache,
  loadAttachmentImage,
  getImagePreviewUrl,
  getFileExt,
  handleDownloadAttachment,
  formatFileSize,
  revokeBlobUrls,
} = useChatAttachments()

async function fetchModels() {
  try {
    const data = await chatApi.getModels()
    availableModels.value = data.models
  } catch {
    // ignore
  }
}

const configSessionId = ref('')

onMounted(() => {
  chatStore.fetchSessions()
  fetchModels()
})

onBeforeUnmount(() => {
  if (scrollRAF) cancelAnimationFrame(scrollRAF)
  revokeBlobUrls()
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
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  background: var(--color-bg-card);
}

.sidebar-top {
  padding: var(--space-4);
  border-bottom: 1px solid var(--color-border);
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
  padding: 10px 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
  margin-bottom: 1px;
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
  background: var(--color-bg-elevated);
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
  border-color: var(--color-text-faint);
  background: var(--color-bg-card);
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

/* Reasoning section */
.reasoning-section {
  margin-bottom: 8px;
  border-radius: 10px;
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border);
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
  border-top: 1px solid var(--color-border);
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  max-height: 400px;
  overflow-y: auto;
}

.reasoning-text {
  white-space: pre-wrap;
  word-break: break-word;
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
  border: 1px solid var(--color-border);
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
.file-icon-box.file-doc  { background: #6366f1; }
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
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-card .file-meta {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.file-card .file-download-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: var(--color-text-muted);
  flex-shrink: 0;
  margin-left: 4px;
  transition: all 0.15s;
}

.file-card:hover .file-download-btn {
  color: var(--color-text);
  background: var(--color-bg-hover);
}

/* ===== Image card in messages ===== */
.image-card {
  display: inline-flex;
  flex-direction: column;
  cursor: pointer;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--color-border);
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

/* ===== Refused / Low-confidence / Sources ===== */
.refused-banner {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  margin-bottom: 8px;
  border-radius: 10px;
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
  font-size: 13px;
  border: 1px solid #ef4444;
}

.message-content {
  position: relative;
}

.message-content.low-confidence {
  border-left: 3px solid #f59e0b;
}

.low-confidence-tip {
  margin-top: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
  font-size: 12px;
}

.form-hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>

<!-- 引用角标由 v-html 渲染、popover 内容 teleport 到 body，需全局样式 -->
<style>
.cite-marker {
  display: inline-block;
  cursor: pointer;
  padding: 0 4px;
  margin: 0 1px;
  font-size: 0.75em;
  line-height: 1;
  vertical-align: super;
  color: var(--color-primary);
  background: rgba(99, 102, 241, 0.1);
  border-radius: 4px;
  transition: background 0.15s, color 0.15s;
  user-select: none;
}

.cite-marker:hover {
  background: var(--color-primary);
  color: #fff;
}

.cite-popover.el-popover.el-popper {
  padding: 10px 12px !important;
}

.cite-pop-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cite-pop-name {
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  word-break: break-word;
}

.cite-pop-sub {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
  font-size: 11px;
  color: #6b7280;
}

.cite-pop-kind {
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.cite-pop-kind.kb {
  background: rgba(99, 102, 241, 0.12);
  color: var(--color-primary);
}

.cite-pop-kind.web {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.cite-pop-snippet {
  font-size: 12px;
  color: #4b5563;
  line-height: 1.5;
  max-height: 100px;
  overflow-y: auto;
}

.cite-pop-link {
  font-size: 12px;
  color: var(--color-primary);
}
</style>
