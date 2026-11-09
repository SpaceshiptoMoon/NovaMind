<template>
  <div class="input-area" :class="{ 'is-welcome': welcome }">
    <div class="input-area-inner" :class="{ 'welcome-center': welcome }">
      <!-- 追问建议（DeerFlow suggestions 对齐）：每轮回答后静默生成，点选即替换/追加草稿 -->
      <div v-if="followups.length && !welcome" class="followup-bar">
        <button
          v-for="(f, i) in followups"
          :key="f"
          class="followup-pill"
          :style="{ animationDelay: `${i * 60}ms` }"
          @click="handleFollowup(f)"
        >
          <el-icon :size="12" class="followup-icon"><ChatDotRound /></el-icon>
          <span class="followup-text">{{ f }}</span>
        </button>
      </div>
      <!-- 欢迎问候（仅欢迎模式）：功能性提问 + agent 名（克制排版，无 emoji/渐变噱头） -->
      <div v-if="welcome" class="welcome-greeting">
        <h2 class="welcome-title">有什么可以帮你？</h2>
        <p class="welcome-desc">
          {{ agentName }}<template v-if="agentDescription"> · {{ agentDescription }}</template>
        </p>
      </div>

      <div class="input-card">
        <!-- 附件缩略图栏（卡内顶部，有附件才渲染） -->
        <div v-if="enableAttachments && attachments.length > 0" class="input-attachments">
          <div v-for="att in attachments" :key="att.id" class="attachment-chip">
            <img
              v-if="isImageFile(att.file_type) && getImagePreviewUrl(att)"
              :src="getImagePreviewUrl(att)"
              class="att-thumb-img"
            />
            <span v-else class="att-type-badge">{{ getFileIcon(att.file_type) }}</span>
            <span class="att-name">{{ att.filename }}</span>
            <span class="att-size">{{ formatFileSize(att.file_size) }}</span>
            <button v-if="att.id != null" class="att-remove" @click="emit('remove-attachment', att.id)">
              <el-icon :size="10"><Close /></el-icon>
            </button>
          </div>
        </div>

        <!-- 文本框区 -->
        <div class="input-scroll">
          <textarea
            ref="textareaRef"
            v-model="inputText"
            class="chat-textarea"
            placeholder="输入消息..."
            :rows="1"
            :disabled="streaming || loading"
            @keydown="handleKeydown"
            @input="autoResize"
          />
        </div>

        <!-- 底部工具行：左 = + 附件 + 模式 chip 群；右 = 模型 + ContextMeter + 发送/停止 -->
        <div class="input-row">
          <div class="input-tools">
            <button
              v-if="enableAttachments"
              class="input-add-btn"
              :disabled="streaming || loading || uploading"
              @click="triggerFileSelect"
              title="上传文档"
            >
              <el-icon :size="14"><Plus /></el-icon>
            </button>
            <input
              ref="fileInputRef"
              type="file"
              accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.gif,.webp"
              multiple
              style="display: none"
              @change="handleFileSelected"
            />
            <!-- 工作目录 chip（已绑定时）：状态显示，点击上抛打开绑定弹窗 -->
            <button
              v-if="enableWorkspace && isWorkspaceBound"
              class="mode-chip workspace-chip active"
              :title="`工作目录：${workspaceRoot}（点击更换 / 退出）`"
              @click="emit('open-workspace')"
            >
              <el-icon :size="14" class="mode-chip-icon"><FolderOpened /></el-icon>
              <span class="workspace-chip-path">{{ workspaceRootName }}</span>
            </button>
            <div v-if="enableModes || enableResearch" class="input-modes">
              <!-- 模式档位（DeerFlow 式单选）：极速=直接作答；深度思考=先推理再作答。
                   后端 enable_thinking 为布尔、无 effort 档位，故映射两档 -->
              <el-popover
                v-if="enableModes"
                v-model:visible="modeMenuOpen"
                trigger="click"
                placement="top-start"
                :width="264"
                :popper-style="{ padding: '6px' }"
              >
                <template #reference>
                  <button
                    class="mode-chip"
                    :class="{ active: thinkingLevel === 'deep' }"
                    title="回答模式"
                  >
                    <el-icon :size="14" class="mode-chip-icon">
                      <MagicStick v-if="thinkingLevel === 'deep'" />
                      <Lightning v-else />
                    </el-icon>
                    <span>{{ thinkingLevel === 'deep' ? '深度思考' : '极速' }}</span>
                  </button>
                </template>
                <div class="mode-level-menu">
                  <button
                    class="mode-level-item"
                    :class="{ selected: thinkingLevel === 'flash' }"
                    @click="setThinkingLevel('flash')"
                  >
                    <el-icon :size="14" class="mode-level-icon"><Lightning /></el-icon>
                    <span class="mode-level-text">
                      <span class="mode-level-name">
                        极速
                        <el-icon v-if="thinkingLevel === 'flash'" :size="12"><Check /></el-icon>
                      </span>
                      <span class="mode-level-desc">直接作答，适合简单问题</span>
                    </span>
                  </button>
                  <button
                    class="mode-level-item"
                    :class="{ selected: thinkingLevel === 'deep' }"
                    @click="setThinkingLevel('deep')"
                  >
                    <el-icon :size="14" class="mode-level-icon"><MagicStick /></el-icon>
                    <span class="mode-level-text">
                      <span class="mode-level-name">
                        深度思考
                        <el-icon v-if="thinkingLevel === 'deep'" :size="12"><Check /></el-icon>
                      </span>
                      <span class="mode-level-desc">回答前先推理，复杂问题更稳（耗时更长）</span>
                    </span>
                  </button>
                </div>
              </el-popover>
              <button
                v-if="enableResearch"
                class="mode-chip"
                :class="{ active: researchEnabled }"
                title="复杂课题先调研再作答（耗时数分钟）"
                @click="toggleDeepResearch"
              >
                <el-icon :size="14" class="mode-chip-icon"><Collection /></el-icon>
                <span>深度研究</span>
              </button>
            </div>
          </div>
          <div class="input-trailing">
            <ModelTrigger
              v-if="enableModel && Object.keys(models).length"
              :model-value="selectedModel"
              :models="models"
              @update:model-value="(v: string) => (selectedModel = v)"
            />
            <ContextMeter
              v-if="enableContext && contextUsage"
              :used="contextUsage.used_tokens"
              :window="contextUsage.context_window"
              :breakdown="contextUsage"
            />
            <button v-if="streaming" class="send-primary stop-primary" title="停止" @click="emit('stop')">
              <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden>
                <rect x="3" y="3" width="10" height="10" rx="3" fill="currentColor" />
              </svg>
            </button>
            <button
              v-else
              class="send-primary"
              :class="{ active: canSend }"
              :disabled="!canSend || loading"
              title="发送"
              @click="send"
            >
              <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden>
                <path
                  d="M8.3125 0.980183C8.66767 1.0531 8.97902 1.20418 9.2627 1.43233C9.48724 1.61297 9.73029 1.85793 9.97949 2.10714L14.707 6.83468L13.293 8.24874L9 3.95577V15.0417H7V3.95577L2.70703 8.24874L1.29297 6.83468L6.02051 2.10714C6.26971 1.85793 6.51277 1.61297 6.7373 1.43233C6.97662 1.23986 7.28445 1.04402 7.6875 0.980183C7.8973 0.947006 8.1031 0.95516 8.3125 0.980183Z"
                  fill="currentColor"
                />
              </svg>
            </button>
          </div>
        </div>
      </div>

      <!-- 快捷提示 pill（仅欢迎模式，输入卡下方，deer-flow Suggestion 对齐） -->
      <div v-if="welcome && quickPrompts.length" class="suggestion-list">
        <button
          v-for="(prompt, i) in quickPrompts"
          :key="i"
          class="suggestion-item"
          :style="{ animationDelay: `${i * 40}ms` }"
          @click="sendQuick(prompt)"
        >
          {{ prompt }}
        </button>
      </div>

      <!-- 键盘提示（卡外微 caption，仅非欢迎态显示） -->
      <div v-if="showHint && !welcome" class="input-hint">
        <span class="hint-item"><kbd>Enter</kbd> 发送</span>
        <span class="hint-item"><kbd>Shift</kbd>+<kbd>Enter</kbd> 换行</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * dsh 风格单一浮动输入卡（单聊/群聊共用）：附件栏 → 文本框 → 底部左右工具行。
 *
 * 能力开关 props 化：附件/档位/深度研究/工作目录/模型/上下文按需渲染（群聊传精简组合）。
 * 草稿与档位是组件内自持的输入态；发送时组装 payload 上抛（附件由父层从 store 取 id）；
 * 追问建议的「替换/追加草稿」逻辑内聚在此。欢迎态（welcome）渲染居中变体+快捷提示。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatDotRound,
  Check,
  Close,
  Collection,
  FolderOpened,
  Lightning,
  MagicStick,
  Plus,
} from '@element-plus/icons-vue'
import ModelTrigger from '@/components/common/ModelTrigger.vue'
import ContextMeter from '@/components/common/ContextMeter.vue'
import type { AgentContextUsageData, ChatAttachment } from '@/api/types'
import { formatFileSize, isImageFile, type ChatSendPayload } from '@/utils/chatRender'
import { getImagePreviewUrl, loadAttachmentImage } from '@/utils/attachmentPreview'

const props = withDefaults(
  defineProps<{
    streaming?: boolean
    loading?: boolean
    uploading?: boolean
    /** 待上传附件（父层 store 托管） */
    attachments?: ChatAttachment[]
    followups?: string[]
    /** 欢迎态（首屏居中变体）：问候 + agent 信息 + 快捷提示 */
    welcome?: boolean
    agentName?: string
    agentDescription?: string
    quickPrompts?: string[]
    /** 能力开关：按聊天形态组合（单聊全开，群聊只留文本+发送） */
    enableAttachments?: boolean
    enableModes?: boolean
    enableResearch?: boolean
    enableWorkspace?: boolean
    enableModel?: boolean
    enableContext?: boolean
    showHint?: boolean
    /** 工作目录 chip（enableWorkspace 时显示） */
    isWorkspaceBound?: boolean
    workspaceRoot?: string
    workspaceRootName?: string
    /** 模型选择（enableModel 时显示） */
    models?: Record<string, { max_tokens: number; temperature: number; top_p: number; model_type: string }>
    selectedModel?: string
    /** 上下文用量（enableContext 时显示） */
    contextUsage?: AgentContextUsageData | null
  }>(),
  {
    streaming: false,
    loading: false,
    uploading: false,
    attachments: () => [],
    followups: () => [],
    welcome: false,
    agentName: '',
    agentDescription: '',
    quickPrompts: () => [],
    enableAttachments: false,
    enableModes: false,
    enableResearch: false,
    enableWorkspace: false,
    enableModel: false,
    enableContext: false,
    showHint: true,
    isWorkspaceBound: false,
    workspaceRoot: '',
    workspaceRootName: '',
    models: () => ({}),
    selectedModel: '',
    contextUsage: null,
  },
)

const emit = defineEmits<{
  (e: 'send', payload: ChatSendPayload): void
  (e: 'stop'): void
  (e: 'files-selected', files: File[]): void
  (e: 'remove-attachment', id: number): void
  (e: 'open-workspace'): void
  /** 深度研究开关变化：未勾选 research 工具的告警由父层做（组件不持有 agent 数据） */
  (e: 'research-toggled', v: boolean): void
}>()

// ===================== 模型选择 =====================
// 组件内自持（'' = Auto 跟随智能体配置）；props.selectedModel 仅作初值
const selectedModel = ref(props.selectedModel)
watch(
  () => props.selectedModel,
  (v) => {
    selectedModel.value = v
  },
)

// ===================== 附件图片预拉 =====================
// 待上传附件变化时为图片拉 Blob URL（发送前缩略预览）
watch(
  () => props.attachments,
  (atts) => {
    for (const att of atts) {
      if (isImageFile(att.file_type) && att.id) void loadAttachmentImage(att.id)
    }
  },
  { immediate: true },
)

// ===================== 草稿与发送 =====================
const inputText = ref('')
const textareaRef = ref<HTMLTextAreaElement>()

const canSend = computed(() => !!inputText.value.trim() || props.attachments.length > 0)

/** 发送：空文本但有附件时以默认文案触发文档分析；发送后清草稿复位高度 */
function send() {
  if (!canSend.value || props.loading) return
  const content = inputText.value.trim()
  const sendContent =
    content || (props.attachments.length > 0 ? '请分析上传的文档' : '')
  inputText.value = ''
  emit('send', {
    content: sendContent,
    enableThinking: thinkingLevel.value === 'deep',
    enableResearch: researchEnabled.value,
    model: selectedModel.value,
  })
  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.style.height = 'auto'
    }
  })
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function autoResize() {
  nextTick(() => {
    const el = textareaRef.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  })
}

/** 欢迎态快捷提示：直接作为内容发送（不走草稿） */
function sendQuick(text: string) {
  inputText.value = text
  send()
}

// ===================== 追问建议（DeerFlow suggestions 对齐） =====================

/** 点击追问 pill：草稿非空时弹「替换/追加」二选（DeerFlow 同语义），随后收起全部。
 *  收起动作由父层在 send 前清空 followups 完成；此处只改草稿并聚焦 */
function handleFollowup(text: string) {
  const commit = (value: string) => {
    inputText.value = value
    nextTick(() => {
      autoResize()
      textareaRef.value?.focus()
    })
  }
  const current = inputText.value
  if (!current.trim()) {
    commit(text)
    return
  }
  ElMessageBox.confirm('替换当前输入内容，还是追加到末尾？', '插入追问', {
    distinguishCancelAndClose: true,
    confirmButtonText: '替换',
    cancelButtonText: '追加',
  })
    .then(() => commit(text))
    .catch((action) => {
      // cancel=追加（distinguishCancelAndClose）；close=放弃
      if (action === 'cancel') commit(`${current}\n${text}`)
    })
}

// ===================== 模式档位与深度研究 =====================

// 回答模式档位（DeerFlow 式）：极速=enable_thinking off；深度思考=on
const thinkingLevel = ref<'flash' | 'deep'>('flash')
const modeMenuOpen = ref(false)

function setThinkingLevel(level: 'flash' | 'deep') {
  thinkingLevel.value = level
  modeMenuOpen.value = false
}

// 深度研究开关（请求级）：开启时本轮消息引导模型优先调用 research 工具。
// 依赖 Agent 勾选 research 工具；未勾选时的告警在父层（经 research-toggled 事件感知）
const researchEnabled = ref(false)

function toggleDeepResearch() {
  researchEnabled.value = !researchEnabled.value
  emit('research-toggled', researchEnabled.value)
}

// ===================== 附件选择 =====================

const fileInputRef = ref<HTMLInputElement>()

function triggerFileSelect() {
  fileInputRef.value?.click()
}

/** 校验文件类型/大小后上抛合法文件（与后端 ALLOWED_FILE_TYPES 对齐；无 doc：后端不支持） */
function handleFileSelected(e: Event) {
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
  if (validFiles.length) emit('files-selected', validFiles)
  input.value = ''
}

function getFileIcon(type: string): string {
  const map: Record<string, string> = {
    pdf: 'PDF',
    docx: 'DOC',
    txt: 'TXT',
    md: 'MD',
    jpg: 'IMG',
    jpeg: 'IMG',
    png: 'IMG',
    gif: 'IMG',
    webp: 'IMG',
  }
  return map[type] || 'FILE'
}

defineExpose({
  /** 外部定位焦点（如发送后） */
  focus: () => textareaRef.value?.focus(),
})
</script>

<style scoped>
/* WorkBuddy 风格：输入卡直接浮在对话画布上，不做白色底 band */
.input-area {
  flex-shrink: 0;
  padding: var(--space-2) var(--space-6) var(--space-5);
  background: transparent;
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
  position: relative;
  /* 与对话态同宽（md 档）：sm 档 576px 装不下「+附件+4 chip+模型+发送」单行（需 ~610px），
     换行会把右侧模型/发送簇挤到第二行；同宽也消除首条消息后卡片宽度跳变 */
  max-width: var(--container-width-md);
  transform: translateY(calc(-50vh + 80px));
}

/* dsh 风格 hero 光晕：输入卡背后的柔和椭圆，CSS radial-gradient + blur 近似 dsh SVG gaussian */
.input-area-inner.welcome-center::before {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -40px;
  width: 110%;
  height: 320px;
  transform: translateX(-50%);
  background: radial-gradient(ellipse at center, rgba(99, 102, 241, 0.1), transparent 70%);
  filter: blur(40px);
  pointer-events: none;
  z-index: -1;
}

/* dsh 风格单一浮动输入卡：附件栏 → 文本框 → 底部左右工具行 */
.input-card {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  padding: 10px 12px 6px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-md);
  transition:
    border-color var(--transition-base),
    box-shadow var(--transition-base);
}

.input-card:focus-within {
  border-color: var(--color-primary);
  box-shadow:
    0 0 0 3px var(--color-primary-muted),
    var(--shadow-sm);
}

/* 附件缩略图栏（卡内顶部，有附件才渲染） */
.input-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 4px 4px 0;
}

/* 文本框区 */
.input-scroll {
  max-height: 160px;
  overflow-y: auto;
}

.chat-textarea {
  display: block;
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  font-family: var(--font-body);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  color: var(--color-text);
  background: transparent;
  padding: 4px 8px 0 12px;
}

.chat-textarea::placeholder {
  color: var(--color-text-faint);
}

.chat-textarea:disabled {
  opacity: 0.5;
}

/* 底部工具行：左 = + 附件 + 模式 chip；右 = 模型 + ContextMeter + 发送/停止 */
.input-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 2px 4px 0;
  /* 窄屏工具行放不下时整体换行，而不是内部元素互相叠压 */
  flex-wrap: wrap;
}

.input-tools,
.input-modes,
.input-trailing {
  display: flex;
  align-items: center;
  min-width: 0;
}

.input-tools {
  gap: 12px;
}

.input-modes {
  gap: 8px;
  /* 极窄视口 chip 群整体放不下时换行（chip 本身 nowrap 不可压缩） */
  flex-wrap: wrap;
}

/* 模式档位菜单（DeerFlow ModeHoverGuide 式）：档位名+一句描述，选中态勾标 */
.mode-level-menu {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.mode-level-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background var(--transition-fast);
}

.mode-level-item:hover,
.mode-level-item.selected {
  background: var(--color-bg-hover);
}

.mode-level-icon {
  color: var(--color-text-muted);
  margin-top: 2px;
  flex-shrink: 0;
}

.mode-level-item.selected .mode-level-icon {
  color: var(--color-text);
}

.mode-level-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.mode-level-name {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
}

.mode-level-desc {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  line-height: 1.5;
}

.input-trailing {
  flex: none;
  gap: 12px;
  /* 左侧工具簇 flex-wrap 换行时，右簇仍吸右，不落回第二行行首 */
  margin-left: auto;
}

/* + 附件圆形按钮（dsh 风格 28px 圆） */
.input-add-btn {
  display: grid;
  place-items: center;
  flex: none;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-bg-hover);
  color: var(--color-text);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.input-add-btn:hover:not(:disabled) {
  background: var(--color-bg-card-elevated);
}

.input-add-btn:disabled {
  opacity: 0.5;
  cursor: default;
}

/* 模式 chip：极速/深度思考/深度研究/工作目录 */
.mode-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 10px;
  /* 窄屏被 flex 压缩时叠字（四字标签塞进 54px），宁可换行不可收缩 */
  flex-shrink: 0;
  white-space: nowrap;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.mode-chip:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-text);
}

/* 模式芯片激活态：中性深灰（AI 聊天惯例——模式开关不做实心墨黑） */
.mode-chip.active {
  background: var(--color-chip-active);
  border-color: var(--color-chip-active);
  color: var(--color-chip-active-text);
  font-weight: var(--weight-medium);
}

.mode-chip-icon {
  display: inline-flex;
  align-items: center;
  font-size: 14px;
  line-height: 1;
}

/* 工作目录 chip（绑定后显示）：复用 mode-chip 基础样式，限宽截断 */
.workspace-chip {
  max-width: 220px;
}

.workspace-chip-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 发送 / 停止主按钮（34px 圆形，active 纯黑） */
.send-primary {
  display: grid;
  place-items: center;
  flex: none;
  width: 34px;
  height: 34px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-bg-hover);
  color: var(--color-text-faint);
  cursor: not-allowed;
  transition: all var(--transition-base);
}

.send-primary.active {
  /* 发送激活：深灰非纯黑（与 chat 输入卡同款） */
  background: var(--color-send-active);
  color: var(--color-chip-active-text);
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
}

.send-primary.active:hover {
  background: var(--color-send-active-hover);
  transform: scale(1.05);
}

.send-primary.stop-primary {
  background: var(--color-warning);
  cursor: pointer;
}

.send-primary.stop-primary:hover {
  background: var(--color-accent);
}

/* 卡外键盘提示（仅非欢迎态显示） */
.input-hint {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin: 6px auto 0;
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

.hint-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.hint-item kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  padding: 1px 5px;
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1.5;
  color: var(--color-text-secondary);
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border-light);
  border-bottom-width: 2px;
  border-radius: 4px;
}

/* 欢迎问候（克制排版：纯色标题 + 灰字描述，无动画噱头） */
.welcome-greeting {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  text-align: center;
  margin-bottom: var(--space-5);
  animation: welcome-fade-in 0.25s ease both;
}

.welcome-title {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  letter-spacing: var(--tracking-tight);
  margin: 0;
}

.welcome-desc {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  text-align: center;
  line-height: var(--leading-relaxed);
  max-width: 32rem;
  margin: 0;
}

@keyframes welcome-fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

/* 快捷提示 pill（deer-flow Suggestion 对齐：stagger 入场） */
.suggestion-list {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-2);
  margin-top: var(--space-4);
  padding: 0 var(--space-2);
}

.suggestion-item {
  padding: 8px 16px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  cursor: pointer;
  user-select: none;
  transition: all var(--transition-base);
  animation: welcome-fade-in 0.2s ease both;
}

.suggestion-item:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-muted);
  color: var(--color-text);
}

/* 追问建议 pills（每轮回答后输入卡上方胶囊，stagger 浮现） */
.followup-bar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  padding: 0 var(--space-2);
}

.followup-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 7px 14px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  cursor: pointer;
  user-select: none;
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast),
    color var(--transition-fast),
    transform var(--transition-fast),
    box-shadow var(--transition-fast);
  animation: followup-in 0.28s cubic-bezier(0.22, 1, 0.36, 1) backwards;
}

.followup-pill:hover {
  border-color: var(--color-border-focus);
  background: var(--color-bg-card-elevated);
  color: var(--color-text);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}

.followup-pill:active {
  transform: translateY(0) scale(0.98);
  box-shadow: none;
}

.followup-icon {
  flex-shrink: 0;
  color: var(--color-primary);
}

.followup-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@keyframes followup-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
}

/* 待上传附件 chip */
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

.att-thumb-img {
  width: 28px;
  height: 28px;
  object-fit: cover;
  border-radius: 4px;
  flex-shrink: 0;
}
</style>
