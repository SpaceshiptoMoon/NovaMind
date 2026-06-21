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

      <!-- 浮动头部 -->
      <header class="chat-header" :class="{ 'is-welcome': isWelcomeMode }">
        <span v-if="!isWelcomeMode" class="header-title">深度研究</span>
      </header>

      <!-- 消息列表 (仅对话模式) -->
      <div v-if="!isWelcomeMode" ref="messagesRef" class="messages-container">
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
                  <span><el-icon :size="12"><Document /></el-icon> {{ msg.stats.total_results }} 来源</span>
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
      <div class="input-area" :class="{ 'is-welcome': isWelcomeMode }">
        <div class="input-area-inner" :class="{ 'welcome-center': isWelcomeMode }">
          <!-- 欢迎问候 (仅欢迎模式) -->
          <div v-if="isWelcomeMode" class="welcome-greeting">
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

          <div class="input-pill">
          <el-popover trigger="click" :width="220" placement="top-start">
            <template #reference>
              <button class="input-action-btn" :disabled="researchStore.isResearching">
                <el-icon :size="16"><Setting /></el-icon>
              </button>
            </template>
            <div class="settings-popover">
              <div class="setting-item">
                <span>研究模式</span>
                <el-select v-model="researchMode" size="small" style="width: 90px">
                  <el-option label="快速" value="quick" />
                  <el-option label="标准" value="standard" />
                  <el-option label="深度" value="deep" />
                </el-select>
              </div>
              <div class="setting-item">
                <span>搜索源</span>
                <el-select v-model="searchSource" size="small" style="width: 110px">
                  <el-option label="混合搜索" value="hybrid" />
                  <el-option label="仅知识库" value="internal" />
                  <el-option label="仅网络" value="external" />
                </el-select>
              </div>
              <div class="setting-item">
                <span>模型</span>
                <el-select
                  v-model="selectedModel"
                  :placeholder="defaultModelName || '默认'"
                  clearable
                  size="small"
                  style="width: 120px"
                >
                  <el-option
                    v-for="m in llmModels"
                    :key="m.model"
                    :label="m.model"
                    :value="m.model"
                  />
                </el-select>
              </div>
              <button class="setting-item clickable" @click="advancedDialogVisible = true">
                <span>高级设置</span>
                <el-icon :size="12"><ArrowRight /></el-icon>
              </button>
              <router-link
                v-if="spaceId"
                :to="`/home/workspace/research/${spaceId}/history`"
                class="setting-item clickable"
              >
                <span>历史记录</span>
                <el-icon :size="12"><ArrowRight /></el-icon>
              </router-link>
            </div>
          </el-popover>
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
        <div class="input-hint">按 Enter 发送，Shift + Enter 换行</div>
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
  CircleCheck,
  Fold,
  Expand,
  ArrowRight,
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
const isWelcomeMode = computed(() => researchStore.messages.length === 0 && !researchStore.isResearching)
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

  let research: Research
  try {
    research = await researchApi.getResearchDetail(spaceId.value, item.session_id)
  } catch {
    ElMessage.error('加载研究详情失败')
    return
  }

  researchStore.clearMessages()
  researchStore.messages.push({
    id: `hist_user_${research.session_id}`,
    role: 'user',
    content: research.query,
  })
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
watch(() => researchStore.isResearching, () => scrollToBottom())
watch(() => researchStore.loading, () => scrollToBottom())

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
  gap: var(--space-2);
  align-items: center;
}

.new-research-btn {
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

.welcome-title {
  font-family: var(--font-display);
  font-size: var(--text-4xl);
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
  font-size: var(--text-xl);
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

/* Assistant message */
.message-row.assistant .message-text {
  padding: var(--space-4) var(--space-5);
  border-radius: 18px 18px 18px 4px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
}

/* Progress message */
.progress-card {
  padding: var(--space-3) var(--space-4);
  border-radius: 18px 18px 18px 4px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  min-width: 240px;
}

.progress-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
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
  padding: 8px 8px 8px 4px;
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
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.25);
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
  text-decoration: none;
}

.setting-item.clickable:hover {
  color: var(--color-primary);
}
</style>
