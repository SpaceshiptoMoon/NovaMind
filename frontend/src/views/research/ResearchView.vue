<template>
  <div class="research-chat">
    <!-- 左侧：研究历史 -->
    <div v-if="spaceId && sidebarVisible" class="chat-sidebar">
      <div class="sidebar-top">
        <button class="new-research-btn" @click="handleNewResearch">
          <el-icon :size="16"><Plus /></el-icon>
          <span>新研究</span>
        </button>
        <button class="toggle-sidebar-btn" @click="sidebarVisible = false">
          <el-icon :size="14"><Fold /></el-icon>
        </button>
      </div>
      <div class="history-list">
        <div
          v-for="item in recentHistory"
          :key="item.session_id"
          class="conv-item"
          :class="{ active: currentSessionId === item.session_id }"
          @click="handleViewHistory(item)"
        >
          <div class="conv-info">
            <span class="conv-title">{{ item.query }}</span>
            <div class="conv-meta">
              <el-tag size="small" :type="getModeTagType(item.research_mode)">{{ getModeText(item.research_mode) }}</el-tag>
              <span class="conv-time">{{ formatTime(item.created_at) }}</span>
            </div>
          </div>
        </div>
        <div v-if="recentHistory.length === 0" class="sidebar-empty">
          <span>暂无研究记录</span>
        </div>
      </div>
    </div>

    <!-- 右侧：对话区域 -->
    <div class="chat-main">
      <!-- 展开侧边栏按钮 -->
      <button v-if="spaceId && !sidebarVisible" class="open-sidebar-btn" @click="sidebarVisible = true">
        <el-icon :size="16"><Expand /></el-icon>
      </button>
      <!-- 空状态：欢迎屏幕 -->
      <div v-if="researchStore.messages.length === 0 && !researchStore.isResearching" class="welcome-screen">
        <div class="welcome-inner">
          <div class="welcome-icon">
            <el-icon :size="40" color="var(--color-primary)"><Search /></el-icon>
          </div>
          <h2 class="welcome-title">深度研究</h2>
          <p class="welcome-subtitle">输入研究问题，AI 将自动搜索、分析并生成研究报告</p>
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
          <template v-for="msg in researchStore.messages" :key="msg.id">
            <!-- 用户消息 -->
            <div v-if="msg.role === 'user'" class="message-row user">
              <div class="message-body">
                <div class="message-text">{{ msg.content }}</div>
                <div class="message-actions">
                  <button class="msg-copy-btn" @click="handleCopyMessage(msg.content, $event)">
                    <el-icon :size="13"><DocumentCopy /></el-icon>
                    <span>复制</span>
                  </button>
                </div>
              </div>
            </div>

            <!-- 进度消息 -->
            <div v-else-if="msg.role === 'progress'" class="message-row progress">
              <div class="message-body">
                <div class="progress-card" :class="{ 'is-done': msg.done }">
                  <div class="progress-header">
                    <el-icon v-if="!msg.done" class="is-loading" :size="16" color="var(--color-primary)"><Loading /></el-icon>
                    <el-icon v-else :size="16" color="var(--color-success)"><CircleCheck /></el-icon>
                    <span class="progress-text">{{ msg.content }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 研究报告消息 -->
            <div v-else-if="msg.role === 'assistant'" class="message-row assistant">
              <div class="message-body">
                <!-- 研究统计 -->
                <div v-if="msg.stats" class="report-stats">
                  <span><el-icon :size="12"><Timer /></el-icon> {{ msg.stats.elapsed_seconds }}s</span>
                  <span><el-icon :size="12"><FolderOpened /></el-icon> 内部 {{ msg.stats.internal_searches }} 次</span>
                  <span><el-icon :size="12"><Link /></el-icon> 外部 {{ msg.stats.external_searches }} 次</span>
                  <span><el-icon :size="12"><Document /></el-icon> {{ msg.stats.sources_count }} 来源</span>
                </div>
                <!-- 来源标签 -->
                <div v-if="msg.sources?.length" class="report-sources">
                  <el-tag
                    v-for="source in msg.sources"
                    :key="source"
                    size="small"
                    type="info"
                  >
                    {{ source }}
                  </el-tag>
                </div>
                <!-- 报告内容 -->
                <div class="message-text">
                  <MarkdownRenderer :content="msg.content" />
                </div>
                <div class="message-actions">
                  <button class="msg-copy-btn" @click="handleCopyMessage(msg.content, $event)">
                    <el-icon :size="13"><DocumentCopy /></el-icon>
                    <span>复制</span>
                  </button>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- 输入区域 -->
      <div class="input-area">
        <div class="input-container">
          <div class="input-wrapper">
            <textarea
              ref="textareaRef"
              v-model="inputText"
              class="chat-textarea"
              :placeholder="spaceId ? '输入研究问题...' : '请先在左侧选择一个知识空间'"
              :rows="1"
              :disabled="researchStore.isResearching || !spaceId"
              @keydown="handleKeydown"
              @input="autoResize"
            />
            <button
              v-if="researchStore.isResearching"
              class="send-btn stop-btn"
              @click="handleCancel"
            >
              <el-icon :size="16"><VideoPause /></el-icon>
            </button>
            <button
              v-else
              class="send-btn"
              :class="{ active: inputText.trim() && spaceId }"
              :disabled="!inputText.trim() || !spaceId"
              @click="handleSend"
            >
              <el-icon :size="16"><Promotion /></el-icon>
            </button>
          </div>
          <div class="input-footer">
            <div class="input-left">
              <el-select v-model="researchMode" size="small" style="width: 100px" :disabled="researchStore.isResearching">
                <el-option label="快速" value="quick" />
                <el-option label="标准" value="standard" />
                <el-option label="深度" value="deep" />
              </el-select>
              <el-select v-model="searchSource" size="small" style="width: 120px" :disabled="researchStore.isResearching">
                <el-option label="混合搜索" value="hybrid" />
                <el-option label="仅知识库" value="internal" />
                <el-option label="仅网络" value="external" />
              </el-select>
              <el-select
                v-model="selectedModel"
                :placeholder="defaultModelName ? `默认: ${defaultModelName}` : '默认模型'"
                clearable
                size="small"
                class="model-select"
                :disabled="researchStore.isResearching"
              >
                <el-option
                  v-for="m in llmModels"
                  :key="m.model"
                  :label="m.model"
                  :value="m.model"
                />
              </el-select>
              <button class="config-btn" @click="advancedDialogVisible = true">
                <el-icon :size="14"><Setting /></el-icon>
                <span>高级</span>
              </button>
            </div>
            <div class="input-right">
              <router-link v-if="spaceId" :to="`/home/workspace/research/${spaceId}/history`" class="config-btn">
                <el-icon :size="14"><Clock /></el-icon>
                <span>历史记录</span>
              </router-link>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 高级设置弹窗 -->
    <el-dialog v-model="advancedDialogVisible" title="高级设置" width="420px" append-to-body destroy-on-close>
      <el-form label-width="90px">
        <el-form-item label="温度">
          <el-slider v-model="advancedSettings.temperature" :min="0" :max="20" :step="1" :format-tooltip="(v: number) => (v / 10).toFixed(1)" />
        </el-form-item>
        <el-form-item label="最大 Token">
          <el-input-number v-model="advancedSettings.max_tokens" :min="1024" :max="16384" :step="1024" style="width: 100%" />
        </el-form-item>
        <el-form-item label="检索数量">
          <el-input-number v-model="advancedSettings.retrieval_top_k" :min="1" :max="50" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="advancedDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, nextTick, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Search,
  Plus,
  Promotion,
  VideoPause,
  DocumentCopy,
  Loading,
  Timer,
  FolderOpened,
  Link,
  Document,
  Setting,
  Clock,
  CircleCheck,
  Fold,
  Expand,
} from '@element-plus/icons-vue'
import { useResearchStore } from '@/stores/research'
import { researchApi } from '@/api/research'
import { userApi } from '@/api/user'
import type { AvailableModelItem, Research } from '@/api/types'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'

const route = useRoute()
const researchStore = useResearchStore()

const spaceId = computed(() => {
  const id = Number(route.params.spaceId)
  return isNaN(id) ? null : id
})

// 输入状态
const inputText = ref('')
const sidebarVisible = ref(true)
const researchMode = ref<'quick' | 'standard' | 'deep'>('standard')
const searchSource = ref<'internal' | 'external' | 'hybrid'>('hybrid')
const selectedModel = ref('')
const messagesRef = ref<HTMLElement>()
const textareaRef = ref<HTMLTextAreaElement>()

// 模型列表
const llmModels = ref<AvailableModelItem[]>([])
const defaultModelName = ref('')

// 高级设置
const advancedDialogVisible = ref(false)
const advancedSettings = reactive({
  temperature: 7,
  max_tokens: 4096,
  retrieval_top_k: 10,
})

const quickPrompts = [
  { icon: '📊', text: '分析市场趋势并总结关键数据' },
  { icon: '🔬', text: '对比两种技术方案的优劣' },
  { icon: '📋', text: '调研行业最新研究报告' },
  { icon: '💡', text: '总结某领域的前沿研究方向' },
]

// 历史研究
const recentHistory = ref<Research[]>([])
const currentSessionId = ref('')
function getModeText(mode: string) {
  const map: Record<string, string> = { quick: '快速', standard: '标准', deep: '深度' }
  return map[mode] || mode
}

function getModeTagType(mode: string) {
  const map: Record<string, string> = { quick: 'info', standard: '', deep: 'warning' }
  return map[mode] || 'info'
}

function formatTime(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function fetchRecentHistory() {
  if (!spaceId.value) return
  try {
    const data = await researchStore.fetchHistory(spaceId.value, { limit: 10, offset: 0 })
    recentHistory.value = data?.items || []
  } catch {
    // ignore
  }
}

async function handleViewHistory(item: Research) {
  if (!spaceId.value) return

  currentSessionId.value = item.session_id

  // always fetch detail to get full report
  let research: Research
  try {
    research = await researchApi.getResearchDetail(spaceId.value, item.session_id)
  } catch {
    ElMessage.error('加载研究详情失败')
    return
  }

  researchStore.clearMessages()
  // push user message
  researchStore.messages.push({
    id: `hist_user_${research.session_id}`,
    role: 'user',
    content: research.query,
  })
  // push assistant message with report
  researchStore.messages.push({
    id: `hist_report_${research.session_id}`,
    role: 'assistant',
    content: research.final_report || '暂无报告内容',
    stats: research.stats,
    sources: research.search_summary?.sources,
  })
  scrollToBottom()
}

function handleNewResearch() {
  currentSessionId.value = ''
  researchStore.clearMessages()
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

watch(() => researchStore.messages.length, () => scrollToBottom())
watch(() => researchStore.messages.map((m) => m.content).join(''), () => scrollToBottom())

function handleQuickPrompt(text: string) {
  inputText.value = text
  handleSend()
}

async function handleSend() {
  const content = inputText.value.trim()
  if (!content || !spaceId.value) return

  inputText.value = ''
  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.style.height = 'auto'
    }
  })

  try {
    currentSessionId.value = ''
    await researchStore.startResearchStream(spaceId.value!, {
      query: content,
      research_mode: researchMode.value,
      search_source: searchSource.value,
      internal_search: {
        top_k: advancedSettings.retrieval_top_k,
      },
      external_search: {},
      llm: {
        llm_model: selectedModel.value || undefined,
        temperature: advancedSettings.temperature / 10,
        max_tokens: advancedSettings.max_tokens,
      },
    })
    ElMessage.success('研究完成')
  } catch {
    ElMessage.error('研究执行失败')
  }
}

function handleCancel() {
  researchStore.cancelResearch()
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

async function fetchModels() {
  try {
    const data = await userApi.getAvailableModelDetails()
    llmModels.value = data.llm || []
    defaultModelName.value = data.llm?.[0]?.model || ''
  } catch {
    // ignore
  }
}

onMounted(() => {
  fetchModels()
  fetchRecentHistory()
})

watch(spaceId, () => {
  fetchRecentHistory()
})
</script>

<style scoped>
.research-chat {
  display: flex;
  background: var(--color-bg);
  overflow: hidden;
  height: 100%;
}

/* ========================================
   Sidebar (Left Panel)
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
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

.new-research-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: var(--font-body);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.new-research-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-muted);
}

.toggle-sidebar-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

.toggle-sidebar-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}

.open-sidebar-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  margin: var(--space-3) 0 0 var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.open-sidebar-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}

.history-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

.conv-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3);
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

.conv-info {
  flex: 1;
  min-width: 0;
}

.conv-title {
  display: block;
  font-size: var(--text-sm);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: var(--leading-normal);
}

.conv-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: 4px;
}

.conv-time {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
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
   Chat Main (Right Panel)
   ======================================== */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--color-bg);
}

/* ========================================
   Welcome Screen
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
  max-width: 640px;
  width: 100%;
}

.welcome-icon {
  width: 72px;
  height: 72px;
  border-radius: var(--radius-xl);
  background: linear-gradient(135deg, #E8F0FE 0%, #FEF1EE 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-6);
  box-shadow: 0 4px 16px rgba(66, 133, 244, 0.12);
}

.welcome-title {
  font-family: var(--font-display);
  font-size: var(--text-3xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
  margin-bottom: var(--space-3);
  letter-spacing: var(--tracking-tight);
}

.welcome-subtitle {
  font-size: var(--text-base);
  color: var(--color-text-muted);
  margin-bottom: var(--space-8);
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
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
  cursor: pointer;
  transition: all var(--transition-base);
  text-align: left;
  font-family: var(--font-body);
}

.prompt-card:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
  box-shadow: var(--shadow-sm);
}

.prompt-icon {
  font-size: 18px;
  flex-shrink: 0;
  margin-top: 1px;
}

.prompt-text {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-normal);
}

.prompt-card:hover .prompt-text {
  color: var(--color-text);
}

/* ========================================
   Messages
   ======================================== */
.messages-container {
  flex: 1;
  overflow-y: auto;
  scroll-behavior: smooth;
}

.messages-inner {
  max-width: 800px;
  margin: 0 auto;
  padding: var(--space-6) var(--space-6) var(--space-4);
}

.message-row {
  display: flex;
  gap: var(--space-4);
  margin-bottom: var(--space-6);
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
  max-width: 70%;
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
  border-radius: var(--radius-2xl) var(--radius-2xl) 4px var(--radius-2xl);
  background: var(--color-primary);
  color: #FFFFFF;
  white-space: pre-wrap;
  box-shadow: 0 1px 4px rgba(66, 133, 244, 0.15);
}

/* Assistant message */
.message-row.assistant .message-text {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-2xl) var(--radius-2xl) var(--radius-2xl) 4px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  position: relative;
}

.message-row.assistant .message-text::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 2px;
  border-radius: 1px;
  background: linear-gradient(180deg, var(--color-primary), var(--color-accent));
  opacity: 0.3;
}

/* Progress message */
.progress-card {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-2xl) var(--radius-2xl) var(--radius-2xl) 4px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  position: relative;
  min-width: 240px;
}

.progress-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 2px;
  border-radius: 1px;
  background: linear-gradient(180deg, var(--color-primary), var(--color-accent));
  opacity: 0.3;
}

.progress-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.progress-text {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.progress-card.is-done {
  opacity: 0.7;
}

.progress-card.is-done .progress-text {
  color: var(--color-text-muted);
}

/* Report stats */
.report-stats {
  display: flex;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  padding: var(--space-2) var(--space-3);
  background: var(--color-bg);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
}

.report-stats span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.report-sources {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: var(--space-3);
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
   Input Area
   ======================================== */
.input-area {
  padding: 0 var(--space-6) var(--space-5);
  background: var(--color-bg);
}

.input-container {
  max-width: 800px;
  margin: 0 auto;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  transition: border-color var(--transition-base), box-shadow var(--transition-base);
}

.input-container:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-muted), var(--shadow-sm);
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  padding: var(--space-3) var(--space-3) var(--space-3) var(--space-4);
  gap: var(--space-2);
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
  padding: var(--space-1) 0;
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

.input-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-1) var(--space-4) var(--space-2);
}

.input-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.model-select {
  width: 140px;
}

.config-btn {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  border: none;
  background: transparent;
  font-family: var(--font-body);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  cursor: pointer;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  transition: all var(--transition-fast);
}

.config-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}

.input-right {
  display: flex;
  align-items: center;
}

.input-right .config-btn {
  text-decoration: none;
}
</style>
