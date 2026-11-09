<template>
  <div class="agent-chat-view">
    <!-- 左侧：会话列表（共享组件，群聊同款交互） -->
    <ChatSessionSidebar
      compact
      show-back
      :sessions="sidebarSessions"
      :current-session-id="agentStore.currentSessionId"
      :loading="agentStore.conversationsLoading"
      :mobile-open="mobileSidebarOpen"
      @update:mobile-open="mobileSidebarOpen = $event"
      @select="handleSelectConversation"
      @new="handleNewChat"
      @delete="handleDeleteConversation"
      @back="goBack"
    />

    <!-- 右侧：对话区域 -->
    <div class="chat-main">
      <ChatHeader
        :agent-name="agentName"
        :is-welcome-mode="isWelcomeMode"
        :view-mode="viewMode"
        :has-session="!!currentSessionId"
        :is-workspace-bound="isWorkspaceBound"
        :workspace-pill-title="workspacePillTitle"
        @update:view-mode="viewMode = $event"
        @work="handleWorkTabClick"
      />

      <!-- 工作目录选择器（唯一实现，右面板目录视图共用绑定动作）：选定即进入工作模式 -->
      <WorkspaceBindDialog v-model="workspaceDialogVisible" />

      <!-- 消息列表：按轮分组，工作过程折叠 -->
      <div
        v-if="!isWelcomeMode && viewMode === 'chat'"
        ref="messagesRef"
        class="messages-container"
        @scroll="handleMessagesScroll"
      >
        <div class="messages-inner">
          <template v-for="turn in turns" :key="turn.key">
            <UserMessage v-if="turn.userMsg" :msg="turn.userMsg" />
            <AssistantTurn
              :turn="turn"
              :agent-name="agentName"
              :tool-calls="agentStore.toolCalls"
              :active-tick="elapsedTick"
              @open-tool="openToolInDrawer"
              @open-wiki="openWikiFromChat"
              @copy="handleCopyMessage"
            />
          </template>

          <!-- E5 异步审批卡：危险代码执行前的用户决策（全局单例瞬时态，
               随消息流滚动展示在流末尾；决策经 WS 回传，120s 后端超时按拒绝兜底） -->
          <ApprovalCard
            v-if="!isWelcomeMode && agentStore.pendingApproval"
            :approval="agentStore.pendingApproval"
            @approve="(id) => handleApproval(id, 'approve')"
            @deny="(id) => handleApproval(id, 'deny')"
          />
        </div>
      </div>

      <!-- 回到底部：用户上拉离开底部后出现（对话模式） -->
      <button
        v-if="!isWelcomeMode && viewMode === 'chat' && !stickToBottom"
        class="jump-to-bottom"
        title="回到底部"
        @click="handleJumpToBottom"
      >
        <el-icon :size="14"><ArrowDown /></el-icon>
      </button>

      <!-- 轨迹视图（调试向消息时间线，平铺每条消息 + 内置 inspector 展开详情）：全屏互斥切换 -->
      <div v-if="!isWelcomeMode && viewMode === 'trajectory'" class="trajectory-container">
        <TrajectoryList
          :messages="agentStore.messages"
          :tool-calls="agentStore.toolCalls"
          :session-id="agentStore.currentSessionId"
        />
      </div>

      <!-- 输入区域（dsh 风格单一浮动卡片；欢迎态居中变体） -->
      <InputCard
        v-if="viewMode === 'chat'"
        :streaming="agentStore.isStreaming"
        :loading="agentStore.loading"
        :uploading="uploadingFiles"
        :attachments="agentStore.pendingAttachments"
        :followups="followups"
        :welcome="isWelcomeMode"
        :agent-name="agentName"
        :agent-description="agentStore.currentAgent?.description || ''"
        :quick-prompts="quickPrompts"
        enable-attachments
        enable-modes
        enable-research
        enable-workspace
        enable-model
        enable-context
        :is-workspace-bound="isWorkspaceBound"
        :workspace-root="workspaceRoot"
        :workspace-root-name="workspaceRootName"
        :models="availableModels"
        :context-usage="agentStore.contextUsage"
        @send="handleSend"
        @stop="handleCancelStream"
        @files-selected="handleFilesSelected"
        @remove-attachment="(id) => agentStore.removePendingAttachment(id)"
        @open-workspace="workspaceDialogVisible = true"
        @research-toggled="handleResearchToggled"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 智能体对话页（/home/workspace/agents/:agentId/chat）
 *
 * 对应路由 WorkspaceAgentChat。渲染主体已拆至 components/agent/chat/
 * （会话栏/头部/用户消息/assistant 轮/工作轨迹/输入卡），本壳只保留：
 * 路由接线、按轮分组（groupTurns）、流式滚动跟随、会话切换、发送编排与追问建议。
 * 关键交互：各轮默认折叠只看最终回复，展开态下沉在 AssistantTurn 组件内自持；
 * 流式自动滚底仅在用户本就位于底部时跟随（stickToBottom），上拉看历史不被拽回。
 */
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch, inject } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import { agentApi } from '@/api/agent'
import { useWorkbenchStore } from '@/stores/workbench'
import { useWorkspaceBinding } from '@/composables/useWorkspaceBinding'
import { groupTurns, type ChatSendPayload, type ChatTurn } from '@/utils/chatRender'
import { revokeAllAttachmentImages } from '@/utils/attachmentPreview'
import ChatSessionSidebar from '@/components/agent/chat/ChatSessionSidebar.vue'
import ChatHeader from '@/components/agent/chat/ChatHeader.vue'
import UserMessage from '@/components/agent/chat/UserMessage.vue'
import AssistantTurn from '@/components/agent/chat/AssistantTurn.vue'
import InputCard from '@/components/agent/chat/InputCard.vue'
import ApprovalCard from '@/components/agent/ApprovalCard.vue'
import WorkspaceBindDialog from '@/components/agent/WorkspaceBindDialog.vue'
import TrajectoryList from '@/components/agent/TrajectoryList.vue'
import { copyToClipboard } from '@/utils/clipboard'

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const workbench = useWorkbenchStore()
const isInWorkspace = inject('isInWorkspace', false)

const agentId = computed(() => Number(route.params.agentId))
const agentName = computed(() => agentStore.currentAgent?.name || '智能体')
const isWelcomeMode = computed(
  () => agentStore.messages.length === 0 && !agentStore.messagesLoading,
)

// 窄屏悬浮会话栏开合态（窄屏判定与 resize 监听在 ChatSessionSidebar 内）
const mobileSidebarOpen = ref(false)

// ===================== 本地文件夹工作区（绑定即本地模式） =====================
// 绑定/解绑动作与右面板共用 useWorkspaceBinding；本页只消费绑定状态（pill 激活态/chip）
const currentSessionId = computed(() => agentStore.currentSessionId)
const { isWorkspaceBound, workspaceRoot, workspaceRootName } = useWorkspaceBinding()
const workspacePillTitle = computed(() =>
  isWorkspaceBound.value ? `工作目录：${workspaceRoot.value}` : '选择文件夹进入工作模式',
)

// ===================== 视图模式 =====================
// 对话（产品化气泡）/ 轨迹（调试向全屏时间线，TrajectoryList 自带详情栏）。
// 轨迹保持全屏互斥切换而非侧车——过程时间线在窄面板里展不开
const viewMode = ref<'chat' | 'trajectory'>('chat')
const workspaceDialogVisible = ref(false)

/** 「工作」tab：未绑定→弹目录选择器（选定即绑定激活）；已绑定→回到对话视图干活 */
function handleWorkTabClick() {
  if (isWorkspaceBound.value) {
    viewMode.value = 'chat'
  } else {
    workspaceDialogVisible.value = true
  }
}

// ===================== 会话侧栏数据与动作 =====================
const sidebarSessions = computed(() =>
  agentStore.conversations.map((c) => ({ id: c.session_id, title: c.title || '新对话' })),
)

function goBack() {
  // 广场页已删：工作台内返回智能体占位页，否则回首页
  if (isInWorkspace) {
    router.push({ name: 'WorkspaceAgents' })
  } else {
    router.push('/home')
  }
}

function handleNewChat() {
  agentStore.clearChat()
}

async function handleSelectConversation(sessionId: string) {
  if (agentStore.currentSessionId === sessionId) return
  // 流式进行中先中止：SSE 回调写 store 全局 messages，不中止会把旧会话增量写进新会话
  if (agentStore.isStreaming) agentStore.cancelStream()
  await agentStore.fetchMessages(sessionId)
  workbench.resetSelection()
  followups.value = []
  scrollToBottom()
  // 窄屏悬浮态选中后收起让位主区（非窄屏时 mobile-open 不生效，无副作用）
  mobileSidebarOpen.value = false
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

// ===================== 按轮分组 =====================
// 分组与 ReAct 步骤归类在 utils/chatRender.groupTurns（纯函数，群聊可复用）
const turns = computed<ChatTurn[]>(() =>
  groupTurns(agentStore.messages, agentStore.isStreaming || agentStore.loading),
)

// ===================== 流式滚动跟随 =====================
const messagesRef = ref<HTMLElement>()

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      // 容器开了 scroll-behavior:smooth，直接赋值会走动画；流式高频触发时动画
      // 不断重启永远到不了底，回到底部按钮也会因 smooth 渐进而第一次点不到位。
      // 跟随滚动/一键归位要即时落点，瞬间到位。
      messagesRef.value.style.scrollBehavior = 'auto'
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
      messagesRef.value.style.scrollBehavior = ''
    }
  })
}

// 用户上拉看历史时不被流式输出拽回底部：只有本来就在底部附近（±80px）才自动跟随。
// stickToBottom 由滚动事件驱动更新，是自动滚动唯一判据。
const stickToBottom = ref(true)

function handleMessagesScroll() {
  const el = messagesRef.value
  if (!el) return
  stickToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

function scrollToBottomIfNeeded() {
  if (stickToBottom.value) scrollToBottom()
}

function handleJumpToBottom() {
  scrollToBottom()
  stickToBottom.value = true
}

watch(
  () => agentStore.messages.length,
  () => {
    scrollToBottomIfNeeded()
  },
)
watch(
  () => agentStore.streamingContent,
  () => scrollToBottomIfNeeded(),
)
watch(
  () => agentStore.loading,
  () => scrollToBottomIfNeeded(),
)

// ===================== 发送编排 =====================
const uploadingFiles = ref(false)

const quickPrompts = [
  '你好，你能帮我做什么？',
  '帮我搜索知识库中的相关内容',
  '分析一下这个问题的原因',
  '总结一下要点',
]

async function handleSend(payload: ChatSendPayload) {
  followups.value = [] // 发送即收起上一轮建议，等本轮回答完成后再生成
  // 主动发送 = 意图朝向最新内容：即使此前上拉看历史，也恢复自动跟随并滚到底
  stickToBottom.value = true
  scrollToBottom()

  try {
    const attachmentIds = agentStore.pendingAttachments.map((a) => a.id)
    // 恒走流式（DeerFlow 同款默认）：非流式分支随开关下线删除
    await agentStore.sendMessageStream(agentId.value, payload.content, {
      enable_thinking: payload.enableThinking,
      deep_research: payload.enableResearch,
      llm_model: payload.model || undefined,
      attachmentIds: attachmentIds.length > 0 ? attachmentIds : undefined,
    })
  } catch {
    ElMessage.error('发送失败，请重试')
    return
  }
  // 回答完成后台静默生成追问（DeerFlow suggestions 同构）；失败静默不提示
  void loadFollowups(payload.model)
}

/** 上传附件：校验已在 InputCard 完成，这里并行上传并逐个报告失败项 */
async function handleFilesSelected(files: File[]) {
  uploadingFiles.value = true
  const results = await Promise.allSettled(files.map((f) => agentStore.uploadAttachment(f)))
  for (let i = 0; i < results.length; i++) {
    const result = results[i]
    const failedFile = files[i]
    if (result?.status === 'rejected') {
      ElMessage.error(`上传失败: ${failedFile?.name ?? ''}`)
    }
  }
  uploadingFiles.value = false
}

// 深度研究依赖 Agent 勾选 research 工具；未勾选时 hint 注入后模型会空转一轮
// 工具调用再口播失败——开启瞬间明示，避免用户以为开关生效
function handleResearchToggled(enabled: boolean) {
  if (
    enabled &&
    agentStore.currentAgent &&
    !(agentStore.currentAgent.enabled_tools || []).includes('research')
  ) {
    ElMessage.warning('当前智能体未启用 research 工具，深度研究不会执行（请在智能体管理中勾选）')
  }
}

function handleCancelStream() {
  agentStore.cancelStream()
}

// ===================== 追问建议（DeerFlow suggestions 对齐） =====================

const followups = ref<string[]>([])

/** 静默生成追问：失败/空结果都不打扰（增强能力，空态即无 pills） */
async function loadFollowups(model?: string) {
  if (!currentSessionId.value || agentStore.isStreaming) return
  try {
    const data = await agentApi.suggestFollowups(
      currentSessionId.value,
      model || undefined,
    )
    followups.value = (data.suggestions || []).filter((s) => s.trim())
  } catch {
    followups.value = []
  }
}

// ===================== 动作转发（消息渲染子组件上抛） =====================

/** 在右侧抽屉打开该工具调用的结果详情（面板唯一入口见右上角浮动按钮） */
function openToolInDrawer(callId: string | null) {
  if (!callId) return
  workbench.selectToolCall(callId)
}

/** 对话内跳转 wiki 阅读页（SPA 路由，保留会话状态） */
function openWikiFromChat(url: string) {
  void router.push(url)
}

function handleCopyMessage(content: string, e: MouseEvent) {
  // currentTarget 只在事件派发同步阶段有效，异步回调里是 null——必须先捕获
  const btn = e.currentTarget as HTMLElement
  copyToClipboard(content).then((ok) => {
    if (!ok) {
      ElMessage.error('复制失败，请手动选择文本复制')
      return
    }
    btn.classList.add('copied')
    const label = btn.querySelector('span')
    if (label) {
      label.textContent = '已复制'
      setTimeout(() => {
        btn.classList.remove('copied')
        label.textContent = '复制'
      }, 2000)
    }
  })
}

/** E5 审批决策回传（WS send 通道；后端 120s 超时按 deny 兜底） */
function handleApproval(approvalId: string, decision: 'approve' | 'deny') {
  agentStore.respondApproval(approvalId, decision)
}

// ===================== 模型列表与生命周期 =====================

const availableModels = ref<
  Record<string, { max_tokens: number; temperature: number; top_p: number; model_type: string }>
>({})

async function fetchModels() {
  try {
    const data = await agentApi.getModels()
    availableModels.value = data.models
  } catch {
    // ignore
  }
}

// 进行中折叠条的实时秒数：elapsedTick 每秒自增驱动 AssistantTurn 折叠条重算
const elapsedTick = ref(0)
let elapsedTimer: number | null = null

onMounted(async () => {
  await agentStore.initForAgent(agentId.value)
  fetchModels()
  elapsedTimer = window.setInterval(() => {
    elapsedTick.value++
  }, 1000)
})

onBeforeUnmount(() => {
  if (elapsedTimer !== null) window.clearInterval(elapsedTimer)
  revokeAllAttachmentImages()
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

.chat-main {
  flex: 1;
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--color-bg-elevated);
}

/* 轨迹全屏视图容器（对话/轨迹互斥切换，保持最初全屏形态） */
.trajectory-container {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding-top: 48px;
  background: var(--color-bg-elevated);
}

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

/* 回到底部悬浮键：悬在输入卡上方，离开底部才出现 */
.jump-to-bottom {
  position: absolute;
  right: 24px;
  bottom: 140px;
  z-index: 4;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  box-shadow: var(--shadow-md);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.jump-to-bottom:hover {
  color: var(--color-text);
  border-color: var(--color-border);
}
</style>
