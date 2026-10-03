<template>
  <div class="chat-view">
    <!-- 主聊天区域（工作台内：会话列表由 WorkspaceLayout 侧栏承载） -->
    <div class="chat-main">
      <!-- 空状态 / 消息列表（设置入口在输入卡工具行，不设顶栏） -->
      <div v-if="chatStore.messages.length === 0 && !chatStore.loading" class="welcome-screen">
        <div class="welcome-inner">
          <h2 class="welcome-title">今天想聊点什么？</h2>
          <p class="welcome-subtitle">
            我可以帮你回答问题、分析文档、编写代码，或从知识库中搜索资料
          </p>
        </div>
      </div>

      <div v-else ref="messagesRef" class="messages-container">
        <MessageList
          :messages="chatStore.messages"
          :is-streaming="chatStore.isStreaming"
          :loading="chatStore.loading"
        />
      </div>

      <!-- 输入区域（agent 输入卡同构；模型选择器移入卡内工具行） -->
      <ChatInput
        :disabled="chatStore.isStreaming || chatStore.loading"
        :pending-attachments-count="chatStore.pendingAttachments.length"
        :models="availableModels"
        :selected-model="selectedModel"
        @update:selected-model="selectedModel = $event"
        @send="handleSend"
        @cancel-stream="handleCancelStream"
        @open-config="openSessionConfig"
      />
    </div>

    <!-- 会话配置弹窗 -->
    <SessionConfigDialog :session-id="configSessionId" @saved="handleConfigSaved" />
  </div>
</template>

<script setup lang="ts">
/**
 * AI 对话页（/home/workspace/chat，经 /home/chat redirect 进入）
 *
 * 对应路由 WorkspaceChat（需 qa 应用），编排会话列表、消息流与输入卡；消息渲染交给
 * MessageList/ChatInput 组件，本层负责会话切换与配置弹窗。
 * 关键约束：流式进行中切换/新建会话必须先 cancelStream，否则 SSE 回调会写入新会话造成消息污染。
 */

import { ref, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useChatStore } from '@/stores/chat'
import { chatApi } from '@/api/chat'
import { useChatAttachments } from '@/composables/useChatAttachments'
import SessionConfigDialog from '@/components/chat/SessionConfigDialog.vue'
import MessageList from '@/components/chat/MessageList.vue'
import ChatInput from '@/components/chat/ChatInput.vue'

const chatStore = useChatStore()

const messagesRef = ref<HTMLElement>()

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

watch(
  () => chatStore.messages.length,
  () => {
    scrollToBottom()
  },
)
let scrollRAF = 0
watch(
  () => chatStore.streamingContent,
  () => {
    if (!scrollRAF) {
      scrollRAF = requestAnimationFrame(() => {
        scrollToBottom()
        scrollRAF = 0
      })
    }
  },
)
watch(
  () => chatStore.loading,
  () => scrollToBottom(),
)
watch(
  () => chatStore.pendingAttachments.length,
  () => {
    for (const att of chatStore.pendingAttachments) {
      if (isImageFile(att.file_type) && att.id && !imageBlobCache.has(att.id)) {
        loadAttachmentImage(att.id)
      }
    }
  },
)

function openSessionConfig() {
  if (!chatStore.currentSessionId) {
    chatStore.currentSessionId = crypto.randomUUID()
  }
  configSessionId.value = ''
  nextTick(() => {
    configSessionId.value = chatStore.currentSessionId ?? ''
  })
}

// 配置弹窗保存成功后重新拉取，使当前会话即时应用新配置
async function handleConfigSaved() {
  if (configSessionId.value) {
    await chatStore.fetchSessionConfig(configSessionId.value)
  }
}

/** 发送消息：组装附件 id 与模型/思考/联网选项，按是否流式分发到 store */
async function handleSend(
  content: string,
  options: {
    useStream: boolean
    enableThinking: boolean
    enableWebSearch: boolean
    llmModel?: string
  },
) {
  const attachmentIds = chatStore.pendingAttachments.map((a) => a.id)
  const opts = {
    // 模型选择在输入卡内（''=Auto 表示不指定，由后端走默认配置）
    llm_model: options.llmModel || undefined,
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

// 模型选择（输入卡内 ModelTrigger，'' = Auto）
const selectedModel = ref('')
const availableModels = ref<
  Record<string, { max_tokens: number; temperature: number; top_p: number; model_type: string }>
>({})

const { isImageFile, imageBlobCache, loadAttachmentImage, revokeBlobUrls } = useChatAttachments()

/** 拉取可用模型列表供输入卡内 ModelTrigger 选择 */
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
   Main Chat Area
   ======================================== */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  /* 与智能体页同画布（白底），用户气泡 --color-user-bubble（#fafafa）在其上可辨 */
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
  max-width: var(--container-width-sm);
  width: 100%;
  /* 呼吸感：整体重心略上移（LobeChat welcome 对齐），标题-副题留白加大 */
  margin-top: -8vh;
}

.welcome-title {
  font-family: var(--font-display);
  font-size: 32px;
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin-bottom: var(--space-4);
  letter-spacing: var(--tracking-tight);
  text-align: center;
}

.welcome-subtitle {
  font-size: var(--text-base);
  color: var(--color-text-muted);
  margin-bottom: var(--space-10);
  text-align: center;
  line-height: var(--leading-relaxed);
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
  max-width: var(--container-width-md);
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
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
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
  background: var(--color-bg-hover);
  border-radius: 4px;
  transition:
    background 0.15s,
    color 0.15s;
  user-select: none;
}

.cite-marker:hover {
  background: var(--color-btn-primary);
  color: var(--color-btn-primary-text);
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
  color: var(--color-text);
  word-break: break-word;
}

.cite-pop-sub {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
  font-size: 11px;
  color: var(--color-text-muted);
}

.cite-pop-kind {
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.cite-pop-kind.kb {
  background: var(--color-info-subtle);
  color: var(--color-primary);
}

.cite-pop-kind.web {
  background: var(--color-info-subtle);
  color: var(--color-text-secondary);
}

.cite-pop-snippet {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.5;
  max-height: 100px;
  overflow-y: auto;
}

.cite-pop-link {
  font-size: 12px;
  color: var(--color-primary);
}
</style>
