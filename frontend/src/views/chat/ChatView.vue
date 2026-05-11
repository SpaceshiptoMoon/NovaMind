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
              <div v-else class="message-text">{{ msg.content }}</div>
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
          <el-popover trigger="click" :width="180" placement="top-start">
            <template #reference>
              <button class="input-action-btn">
                <el-icon :size="16"><Setting /></el-icon>
              </button>
            </template>
            <div class="settings-popover">
              <label class="setting-item">
                <span>深度思考</span>
                <el-switch v-model="enableThinking" size="small" />
              </label>
              <label class="setting-item">
                <span>流式输出</span>
                <el-switch v-model="useStream" size="small" />
              </label>
              <div class="setting-item">
                <span>模型</span>
                <el-select
                  v-model="selectedModel"
                  :placeholder="defaultModelName || '默认'"
                  clearable
                  size="small"
                  style="width: 120px"
                >
                  <el-option v-for="(_, name) in availableModels" :key="name" :label="name" :value="name" />
                </el-select>
              </div>
              <button
                v-if="chatStore.currentSessionId"
                class="setting-item clickable"
                @click="handleOpenConfig(chatStore.currentSessionId)"
              >
                <span>会话设置</span>
                <el-icon :size="12"><ArrowRight /></el-icon>
              </button>
            </div>
          </el-popover>
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
            :class="{ active: inputText.trim() }"
            :disabled="!inputText.trim() || chatStore.loading"
            @click="handleSend"
          >
            <el-icon :size="16"><Promotion /></el-icon>
          </button>
        </div>
        <div class="input-hint">按 Enter 发送，Shift + Enter 换行</div>
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
import { ref, reactive, computed, nextTick, onMounted, watch, inject } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Setting, Promotion, VideoPause, DocumentCopy, ArrowRight, ArrowDown } from '@element-plus/icons-vue'
import { useChatStore } from '@/stores/chat'
import { chatApi } from '@/api/chat'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'

const chatStore = useChatStore()
const isInWorkspace = inject('isInWorkspace', false)

const inputText = ref('')
const useStream = ref(true)
const enableThinking = ref(false)
const expandedReasoning = ref(new Set<number>())
const messagesRef = ref<HTMLElement>()
const textareaRef = ref<HTMLTextAreaElement>()

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

watch(() => chatStore.messages.length, () => scrollToBottom())
watch(() => chatStore.streamingContent, () => scrollToBottom())
watch(() => chatStore.loading, () => scrollToBottom())

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
  if (!content) return

  inputText.value = ''
  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.style.height = 'auto'
    }
  })

  try {
    if (useStream.value) {
      await chatStore.sendMessageStream(content, {
        llm_model: selectedModel.value || undefined,
        enable_thinking: enableThinking.value,
      })
    } else {
      await chatStore.sendMessage(content, {
        llm_model: selectedModel.value || undefined,
        enable_thinking: enableThinking.value,
      })
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
const availableModels = ref<Record<string, { max_tokens: number; temperature: number; top_p: number }>>({})
const defaultModelName = computed(() => Object.keys(availableModels.value)[0] || '')

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
</script>

<style scoped>
/* ========================================
   Layout
   ======================================== */
.chat-view {
  position: absolute;
  inset: 0;
  display: flex;
  background: #FFFFFF;
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
  background: #FFFFFF;
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
  background: var(--color-primary);
  color: #FFFFFF;
  white-space: pre-wrap;
  box-shadow: 0 1px 4px rgba(66, 133, 244, 0.15);
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
  background: #f8f9fa;
  border: 1px solid #e9ecef;
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
  background: #f1f3f5;
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
  border-top: 1px solid #e9ecef;
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
  background: #FFFFFF;
}

.input-pill {
  max-width: 860px;
  margin: 0 auto;
  display: flex;
  align-items: flex-end;
  padding: 8px 8px 8px 4px;
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
  box-shadow: 0 2px 8px rgba(66, 133, 244, 0.25);
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
  max-width: 860px;
  margin: 8px auto 0;
  text-align: center;
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

/* ========================================
   Settings Popover
   ======================================== */
.settings-popover {
  display: flex;
  flex-direction: column;
}

.setting-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  font-size: var(--text-sm);
  color: var(--color-text);
  cursor: default;
}

.setting-item.clickable {
  cursor: pointer;
  border: none;
  background: transparent;
  font-family: var(--font-body);
  width: 100%;
  transition: color var(--transition-fast);
}

.setting-item.clickable:hover {
  color: var(--color-primary);
}
</style>
