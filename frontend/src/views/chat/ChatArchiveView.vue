<template>
  <div class="chat-archive">
    <!-- 页头：归档说明 + 会话选择 -->
    <div class="archive-header">
      <div class="archive-header-main">
        <h2 class="archive-title">QA 历史归档</h2>
        <p class="archive-subtitle">历史对话已归档为只读；新的对话请前往「对话」页继续。</p>
      </div>
      <el-select
        v-model="selectedSessionId"
        class="archive-session-select"
        placeholder="选择历史会话"
        filterable
        :loading="loadingSessions"
        @change="handleSelectSession"
      >
        <el-option
          v-for="s in chatStore.sessions"
          :key="s.session_id"
          :label="s.preview || '未命名会话'"
          :value="s.session_id"
        />
      </el-select>
    </div>

    <!-- 消息区：只读渲染历史消息 -->
    <div class="archive-body">
      <div v-if="chatStore.loading" class="archive-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>加载中…</span>
      </div>
      <div v-else-if="chatStore.messages.length === 0" class="archive-empty">
        <p>{{ selectedSessionId ? '该会话暂无消息' : '暂无历史会话' }}</p>
      </div>
      <div v-else ref="messagesRef" class="archive-messages">
        <MessageList
          :messages="chatStore.messages"
          :is-streaming="false"
          :loading="false"
        />
      </div>
    </div>

    <!-- 禁用输入占位 -->
    <div class="archive-input-placeholder">
      <span>历史对话已归档，请在对话页继续</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * QA 历史归档页（/home/workspace/chat/archive，需 qa 应用）
 *
 * 老 QA 对话的只读出口：会话下拉切换 + MessageList 只读渲染；
 * 不带发送/配置/附件逻辑（新对话统一走 agent 对话面）。
 */
import { ref, onMounted, nextTick } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { useChatStore } from '@/stores/chat'
import MessageList from '@/components/chat/MessageList.vue'

const chatStore = useChatStore()
const selectedSessionId = ref('')
const loadingSessions = ref(false)
const messagesRef = ref<HTMLElement>()

async function handleSelectSession(sessionId: string) {
  if (!sessionId) return
  // 归档页与对话页共用 chat store：在途流不中止会把增量写进刚拉取的历史列表
  if (chatStore.isStreaming) chatStore.cancelStream()
  await chatStore.fetchMessages(sessionId)
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

onMounted(async () => {
  loadingSessions.value = true
  try {
    await chatStore.fetchSessions()
    // 默认选中最近一条会话，老用户进来即见内容
    const first = chatStore.sessions[0]
    if (first) {
      selectedSessionId.value = first.session_id
      await handleSelectSession(first.session_id)
    }
  } finally {
    loadingSessions.value = false
  }
})
</script>

<style scoped>
.chat-archive {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  background: var(--color-bg-card);
  min-width: 0;
  min-height: 0;
}

.archive-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.archive-header-main {
  min-width: 0;
}

.archive-title {
  font-size: 16px;
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  margin: 0 0 2px;
}

.archive-subtitle {
  font-size: 12px;
  color: var(--color-text-muted);
  margin: 0;
}

.archive-session-select {
  width: 260px;
  max-width: 100%;
  flex-shrink: 0;
}

.archive-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.archive-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.archive-loading,
.archive-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  color: var(--color-text-muted);
  font-size: 13px;
}

.archive-input-placeholder {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
  margin: 0 var(--space-5) var(--space-4);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
  font-size: 13px;
  color: var(--color-text-muted);
  background: var(--color-bg);
}

@media (max-width: 640px) {
  .archive-header {
    flex-direction: column;
    align-items: stretch;
  }

  .archive-session-select {
    width: 100%;
  }
}
</style>
