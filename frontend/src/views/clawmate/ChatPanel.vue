<template>
  <div class="chat-panel">
    <!-- Header -->
    <header class="chat-header">
      <span class="chat-title">AI 助手</span>
    </header>

    <!-- Warning banner -->
    <div v-if="store.warning" class="warning-banner">
      <el-icon :size="14"><WarningFilled /></el-icon>
      <span>{{ store.warning }}</span>
    </div>

    <!-- Messages area -->
    <div ref="messagesRef" class="messages-container">
      <div class="messages-inner">
        <ChatMessageBubble
          v-for="msg in store.messages"
          :key="msg.id"
          :message="msg"
        />

        <!-- Typing indicator: streaming started but no content yet -->
        <div v-if="store.isStreaming && !store.streamingContent" class="typing-row">
          <div class="typing-bubble">
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
          </div>
        </div>
      </div>
    </div>

    <!-- Input area -->
    <div class="input-area">
      <div class="input-pill">
        <textarea
          ref="textareaRef"
          v-model="inputText"
          class="chat-textarea"
          placeholder="输入消息..."
          :rows="1"
          :disabled="store.isStreaming"
          @keydown="handleKeydown"
          @input="autoResize"
        />
        <ModelFanSelector
          v-model="selectedModel"
          :models="availableModels"
          :default-model-name="defaultModelName"
        />
        <!-- Stop button when streaming -->
        <button
          v-if="store.isStreaming"
          class="send-btn stop-btn"
          @click="handleStop"
        >
          <el-icon :size="16"><VideoPause /></el-icon>
        </button>
        <!-- Send button -->
        <button
          v-else
          class="send-btn"
          :class="{ active: inputText.trim() }"
          :disabled="!inputText.trim()"
          @click="handleSend"
        >
          <el-icon :size="16"><Promotion /></el-icon>
        </button>
      </div>
      <div class="input-hint">Enter 发送 · Shift+Enter 换行</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted } from 'vue'
import { WarningFilled, VideoPause, Promotion } from '@element-plus/icons-vue'
import { useClawMateStore } from '@/stores/clawmate'
import { chatApi } from '@/api/chat'
import ModelFanSelector from '@/components/common/ModelFanSelector.vue'
import ChatMessageBubble from './ChatMessageBubble.vue'

const store = useClawMateStore()

const inputText = ref('')
const selectedModel = ref('')
const messagesRef = ref<HTMLElement>()
const textareaRef = ref<HTMLTextAreaElement>()

// Model list
const availableModels = ref<Record<string, { max_tokens: number; temperature: number; top_p: number; model_type?: string }>>({})
const defaultModelName = computed(() => Object.keys(availableModels.value)[0] || '')

async function fetchModels() {
  try {
    const data = await chatApi.getModels()
    availableModels.value = data.models
  } catch {
    // ignore
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

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
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
    await store.sendMessage(content, selectedModel.value || undefined)
  } catch {
    // error handled in store
  }
}

function handleStop() {
  store.cancelStream()
}

// Auto-scroll on new messages / streaming
watch(() => store.messages.length, () => scrollToBottom())
watch(() => store.streamingContent, () => scrollToBottom())

onMounted(() => {
  fetchModels()
})
</script>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--color-bg);
  overflow: hidden;
}

/* Header */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
  background: var(--color-bg-card);
  flex-shrink: 0;
}

.chat-title {
  font-size: var(--text-base);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

/* Warning banner */
.warning-banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: rgba(240, 173, 78, 0.1);
  color: #e6a23c;
  font-size: var(--text-sm);
  flex-shrink: 0;
}

/* Messages area */
.messages-container {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scroll-behavior: smooth;
  padding: var(--space-4);
}

.messages-inner {
  max-width: 800px;
  margin: 0 auto;
}

/* Typing indicator */
.typing-row {
  display: flex;
  margin-bottom: var(--space-5);
  animation: messageIn 0.3s ease forwards;
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

@keyframes messageIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Input area */
.input-area {
  flex-shrink: 0;
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--color-border-light);
  background: var(--color-bg-card);
}

.input-pill {
  display: flex;
  align-items: flex-end;
  padding: var(--space-2) var(--space-3);
  gap: var(--space-2);
  background: var(--color-bg);
  border: 1px solid var(--color-border-light);
  border-radius: 24px;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.input-pill:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-subtle);
}

.chat-textarea {
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  font-family: var(--font-body);
  font-size: var(--text-base);
  line-height: 1.5;
  color: var(--color-text);
  background: transparent;
  padding: var(--space-2);
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
  border-radius: 50%;
  background: var(--color-border-light);
  color: var(--color-text-faint);
  cursor: not-allowed;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.send-btn.active {
  background: var(--color-primary);
  color: #ffffff;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.25);
}

.send-btn.active:hover {
  transform: scale(1.05);
}

.stop-btn {
  background: #e6a23c;
  color: #ffffff;
  cursor: pointer;
}

.stop-btn:hover {
  background: #cf8c2e;
}

.input-hint {
  margin-top: var(--space-1);
  text-align: center;
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}
</style>
