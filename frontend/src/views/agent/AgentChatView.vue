<template>
  <div class="agent-chat-view">
    <!-- 左侧：会话列表 -->
    <div class="chat-sidebar" :class="{ compact: isInWorkspace, 'mobile-open': mobileSidebarOpen }">
      <div class="sidebar-top">
        <button
          v-if="isNarrowViewport"
          class="sidebar-toggle-btn"
          :title="mobileSidebarOpen ? '收起会话列表' : '展开会话列表'"
          @click="mobileSidebarOpen = !mobileSidebarOpen"
        >
          <el-icon :size="16">
            <Expand v-if="!mobileSidebarOpen" />
            <Close v-else />
          </el-icon>
        </button>
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
        <div
          v-if="agentStore.conversations.length === 0 && !agentStore.conversationsLoading"
          class="sidebar-empty"
        >
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
          <div v-if="!isWelcomeMode" class="header-tabs" role="tablist">
            <button
              class="view-pill"
              :class="{ active: viewMode === 'chat' }"
              role="tab"
              :aria-selected="viewMode === 'chat'"
              @click="viewMode = 'chat'"
            >
              聊天
            </button>
            <button
              class="view-pill"
              :class="{ active: viewMode === 'trajectory' }"
              role="tab"
              :aria-selected="viewMode === 'trajectory'"
              @click="viewMode = 'trajectory'"
            >
              轨迹
            </button>
          </div>
        </div>
      </header>

      <!-- 消息列表 (仅对话模式)：按轮分组，工作过程折叠 -->
      <div
        v-if="!isWelcomeMode && viewMode === 'chat'"
        ref="messagesRef"
        class="messages-container"
        @scroll="handleMessagesScroll"
      >
        <div class="messages-inner">
          <template v-for="turn in turns" :key="turn.key">
            <div class="chat-turn">
              <!-- 用户消息 -->
              <div v-if="turn.userMsg" class="message-row user">
                <div class="message-body">
                  <div class="message-text">{{ turn.userMsg.content }}</div>
                  <div
                    v-if="getMessageAttachments(turn.userMsg).length"
                    class="message-attachments"
                  >
                    <template
                      v-for="att in getMessageAttachments(turn.userMsg)"
                      :key="att.filename"
                    >
                      <div
                        v-if="isImageFile(att.file_type) && att.id"
                        class="image-card"
                        @click="handleDownloadAttachment(att)"
                      >
                        <img
                          v-if="getImagePreviewUrl(att)"
                          :src="getImagePreviewUrl(att)"
                          class="image-thumb"
                          loading="lazy"
                        />
                        <div v-else class="image-thumb image-thumb-loading">加载中...</div>
                        <div class="image-info">
                          <span class="image-name">{{ att.filename }}</span>
                          <span class="image-size">{{ formatFileSize(att.file_size ?? 0) }}</span>
                        </div>
                      </div>
                      <div v-else class="file-card" @click="handleDownloadAttachment(att)">
                        <div class="file-icon-box" :class="getFileIconClass(att.file_type)">
                          <span class="file-ext-label">{{ getFileExt(att.filename) }}</span>
                        </div>
                        <div class="file-info">
                          <div class="file-name">{{ att.filename }}</div>
                          <div class="file-meta">
                            {{ getFileExt(att.filename) }} ·
                            {{ formatFileSize(att.file_size ?? 0) }}
                          </div>
                        </div>
                        <div class="file-download-btn" title="下载">
                          <el-icon :size="16"><Download /></el-icon>
                        </div>
                      </div>
                    </template>
                  </div>
                </div>
              </div>

              <!-- assistant 一轮：左 avatar + 右内容列（WorkBuddy 风格：头像随内容内联，不重复占一整行名称头） -->
              <div
                v-if="turn.items.length || turn.finalAssistant || turn.isActive"
                class="assistant-turn"
              >
                <div class="turn-avatar" :title="agentName">{{ agentName.charAt(0) }}</div>
                <div class="turn-body">
                  <!-- 有工作过程（ReAct 步骤或思考过程）即显示折叠头；始终默认折叠（含进行中，
                     进行中与已完成的区分靠 spinner/主题色与「思考中/思考过程」一词之差，句式统一），
                     展开才见运行轨迹 -->
                  <button
                    v-if="turn.steps.length > 0 || turn.finalAssistant?.reasoning"
                    class="fold-line"
                    :class="{ running: turn.isActive }"
                    @click="toggleTurn(turn)"
                  >
                    <span
                      v-if="turn.isActive"
                      class="fold-spinner"
                      aria-hidden="true"
                    ></span>
                    <span class="fold-status">{{ foldStatusLabel(turn) }}</span>
                    <el-icon
                      :size="12"
                      class="fold-chevron"
                      :class="{ expanded: isTurnExpanded(turn) }"
                    >
                      <ArrowDown />
                    </el-icon>
                  </button>

                  <!-- 压缩标记行（CompactionItem）：压缩发生位置的「已压缩 N 条」可展开看摘要。
                     dsh shadowed 语义：不移除历史消息，仅标记 model 在此停止看到之前历史 -->
                  <CompactionItem
                    v-for="c in turn.compactionItems"
                    :key="`compaction-${c.id}`"
                    :data="getCompactionData(c)"
                    :expanded="expandedCompactions.has(c.id)"
                    @toggle="toggleCompaction(c.id)"
                  />

                  <!-- 计划卡（Plan-and-Execute）：常驻胶囊行，展开看步骤清单/进度/总结 -->
                  <PlanCard
                    v-for="p in turn.planItems"
                    :key="`plan-${p.id}`"
                    :plan="getPlanData(p)"
                    :expanded="expandedPlans.has(p.id)"
                    @toggle="togglePlan(p.id)"
                  />

                  <!-- 深度研究进度卡（批3 research 工具）：spinner 胶囊行，展开看进度条与计划 -->
                  <ResearchProgressCard
                    v-for="r in turn.researchItems"
                    :key="`research-${r.id}`"
                    :data="getResearchData(r)"
                    :expanded="expandedResearch.has(r.id)"
                    @toggle="toggleResearch(r.id)"
                  />

                  <!-- 纠偏警告行（loop_detection）：常显轻量提示，不折叠（用户应看到的异常信号） -->
                  <div
                    v-for="n in turn.noticeItems"
                    :key="`notice-${n.id}`"
                    class="notice-row"
                  >
                    <el-icon :size="12" class="notice-icon"><Warning /></el-icon>
                    <span class="notice-text">{{ n.content }}</span>
                  </div>

                  <!-- 工作过程：按 ReAct 步骤渲染。始终默认折叠（含进行中——轨迹不抢视觉焦点，
                     进行中状态由折叠条「思考中 · Ns」表达），展开后每个 AI 步骤也是
                     摘要行默认收起（回答、调用工具、结果逐层 disclosure）。
                     无步骤且无思考过程时不渲染空容器 -->
                  <div
                    v-if="turn.steps.length > 0 || turn.finalAssistant?.reasoning"
                    v-show="isTurnExpanded(turn)"
                    class="work-trail"
                  >
                    <template v-for="(step, si) in turn.steps" :key="si">
                      <!-- AI 输出（LLM 一次响应）：摘要行默认收起，展开看完整 reasoning/文本/工具参数 -->
                      <div v-if="step.ai && toContentBlocks(step.ai).length" class="ai-step">
                        <button
                          class="ai-step-summary"
                          @click="toggleStep(`${turn.key}:${si}`)"
                        >
                          <span class="ai-step-kind">{{
                            toContentBlocks(step.ai).some((b) => b.kind === 'tool_call') ? '调用工具' : '已完成思考'
                          }}</span>
                          <span class="ai-step-text">{{ stepSummary(step) }}</span>
                          <el-icon
                            :size="12"
                            class="expand-icon"
                            :class="{ expanded: expandedSteps.has(`${turn.key}:${si}`) }"
                          >
                            <ArrowDown />
                          </el-icon>
                        </button>
                        <div
                          v-if="expandedSteps.has(`${turn.key}:${si}`)"
                          class="ai-output"
                        >
                          <template
                            v-for="(block, bi) in toContentBlocks(step.ai)"
                            :key="bi"
                          >
                            <div v-if="block.kind === 'reasoning'" class="ai-reasoning">
                              <MarkdownRenderer :content="block.text" />
                            </div>
                            <div v-else-if="block.kind === 'text'" class="ai-content">
                              <MarkdownRenderer :content="block.text" />
                            </div>
                            <div v-else-if="block.kind === 'tool_call'" class="ai-tool-call">
                              <span class="ai-tool-name">{{ block.name }}</span>
                              <pre v-if="block.arguments" class="ai-tool-args">{{
                                formatToolArgs(block.arguments)
                              }}</pre>
                            </div>
                          </template>
                        </div>
                      </div>
                      <!-- 工具实际执行（结果与 AI 输出分离；参数已在 AI 输出的 tool_calls 展示） -->
                      <div v-for="tool in step.tools" :key="tool.id" class="tool-card-row">
                        <div class="tool-card">
                          <div class="tool-header" @click="toggleToolExpand(tool.id)">
                            <div class="tool-info">
                              <span class="tool-icon">
                                <el-icon :size="14"><SetUp /></el-icon>
                              </span>
                              <span class="tool-name">{{ tool.tool_name || 'Tool' }}</span>
                              <span v-if="getToolDuration(tool.tool_call_id)" class="tool-duration">
                                {{ getToolDuration(tool.tool_call_id) }}ms
                              </span>
                              <span class="tool-status" :class="getToolStatus(tool.tool_call_id)">
                                {{ getToolStatusLabel(tool.tool_call_id) }}
                              </span>
                            </div>
                            <div class="tool-header-actions">
                              <button
                                class="tool-drawer-btn"
                                title="在右侧抽屉查看"
                                @click.stop="openToolInDrawer(tool.tool_call_id)"
                              >
                                <el-icon :size="12"><Expand /></el-icon>
                              </button>
                              <el-icon
                                :size="12"
                                class="expand-icon"
                                :class="{ expanded: expandedTools.has(tool.id) }"
                              >
                                <ArrowDown />
                              </el-icon>
                            </div>
                          </div>
                          <div v-if="expandedTools.has(tool.id)" class="tool-body">
                            <div v-if="tool.content" class="tool-section">
                              <div class="tool-section-label">结果</div>
                              <pre class="tool-json">{{ truncateResult(tool.content) }}</pre>
                            </div>
                          </div>
                        </div>
                      </div>
                    </template>

                    <!-- 思考过程（来自最终 assistant 的 reasoning） -->
                    <div v-if="turn.finalAssistant?.reasoning" class="reasoning-section">
                      <div
                        class="reasoning-header"
                        @click="toggleReasoning(turn.finalAssistant.id)"
                      >
                        <span class="reasoning-label">思考过程</span>
                        <el-icon
                          :size="12"
                          class="expand-icon"
                          :class="{ expanded: expandedReasoning.has(turn.finalAssistant.id) }"
                        >
                          <ArrowDown />
                        </el-icon>
                      </div>
                      <div
                        v-if="expandedReasoning.has(turn.finalAssistant.id)"
                        class="reasoning-body"
                      >
                        <MarkdownRenderer :content="turn.finalAssistant.reasoning" />
                      </div>
                    </div>
                  </div>

                  <!-- 最终回复（始终显示） -->
                  <div v-if="turn.finalAssistant?.content" class="final-answer">
                    <MarkdownRenderer :content="turn.finalAssistant.content" class="message-text" />
                    <div class="message-actions">
                      <button
                        class="msg-copy-btn"
                        @click="handleCopyMessage(turn.finalAssistant.content!, $event)"
                      >
                        <el-icon :size="13"><DocumentCopy /></el-icon>
                        <span>复制</span>
                      </button>
                    </div>
                  </div>
                  <!-- 流式/加载中且无轨迹：点点占位（有轨迹时由折叠条「思考中」表达，不重复显示） -->
                  <div
                    v-else-if="turn.isActive && !turn.steps.length && !turn.finalAssistant?.reasoning"
                    class="typing-row"
                  >
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
            </div>
          </template>
        </div>
      </div>

      <!-- 回到底部：用户上拉离开底部后出现（对话模式） -->
      <button
        v-if="!isWelcomeMode && viewMode === 'chat' && !stickToBottom"
        class="jump-to-bottom"
        title="回到底部"
        @click="scrollToBottom(); stickToBottom = true"
      >
        <el-icon :size="14"><ArrowDown /></el-icon>
      </button>

      <!-- 轨迹视图（调试向消息时间线，平铺每条消息 + 内部 inspector 展开详情） -->
      <div v-if="!isWelcomeMode && viewMode === 'trajectory'" class="trajectory-container">
        <TrajectoryList
          :messages="agentStore.messages"
          :tool-calls="agentStore.toolCalls"
          :session-id="agentStore.currentSessionId"
        />
      </div>

      <!-- 输入区域（dsh 风格单一浮动卡片：附件栏 → 文本框 → 底部左右工具行） -->
      <div v-if="viewMode === 'chat'" class="input-area" :class="{ 'is-welcome': isWelcomeMode }">
        <div class="input-area-inner" :class="{ 'welcome-center': isWelcomeMode }">
          <!-- 欢迎问候 (仅欢迎模式)：功能性提问 + agent 名（克制排版，无 emoji/渐变噱头） -->
          <div v-if="isWelcomeMode" class="welcome-greeting">
            <h2 class="welcome-title">有什么可以帮你？</h2>
            <p class="welcome-desc">
              {{ agentName
              }}<template v-if="agentStore.currentAgent?.description">
                · {{ agentStore.currentAgent.description }}</template
              >
            </p>
          </div>

          <div class="input-card">
            <!-- 附件缩略图栏（卡内顶部，有附件才渲染） -->
            <div v-if="agentStore.pendingAttachments.length > 0" class="input-attachments">
              <div
                v-for="att in agentStore.pendingAttachments"
                :key="att.id"
                class="attachment-chip"
              >
                <img
                  v-if="isImageFile(att.file_type) && getImagePreviewUrl(att)"
                  :src="getImagePreviewUrl(att)"
                  class="att-thumb-img"
                />
                <span v-else class="att-type-badge">{{ getFileIcon(att.file_type) }}</span>
                <span class="att-name">{{ att.filename }}</span>
                <span class="att-size">{{ formatFileSize(att.file_size) }}</span>
                <button class="att-remove" @click="agentStore.removePendingAttachment(att.id)">
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
                :disabled="agentStore.isStreaming || agentStore.loading"
                @keydown="handleKeydown"
                @input="autoResize"
              />
            </div>

            <!-- 底部工具行：左 = + 附件 + 模式 chip；右 = 模型 + ContextMeter + 发送/停止 -->
            <div class="input-row">
              <div class="input-tools">
                <button
                  class="input-add-btn"
                  :disabled="agentStore.isStreaming || agentStore.loading || uploadingFiles"
                  @click="triggerFileSelect"
                  title="上传文档"
                >
                  <el-icon :size="14"><Plus /></el-icon>
                </button>
                <input
                  ref="fileInputRef"
                  type="file"
                  accept=".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.gif,.webp"
                  style="display: none"
                  @change="handleFileSelected"
                />
                <div class="input-modes">
                  <button
                    class="mode-chip"
                    :class="{ active: enableThinking }"
                    @click="enableThinking = !enableThinking"
                  >
                    <el-icon :size="14" class="mode-chip-icon"><MagicStick /></el-icon>
                    <span>深度思考</span>
                  </button>
                  <button
                    class="mode-chip"
                    :class="{ active: useStream }"
                    @click="useStream = !useStream"
                  >
                    <el-icon :size="14" class="mode-chip-icon"><Lightning /></el-icon>
                    <span>流式输出</span>
                  </button>
                  <button
                    class="mode-chip"
                    :class="{ active: enableResearch }"
                    title="复杂课题先调研再作答（耗时数分钟）"
                    @click="toggleDeepResearch"
                  >
                    <el-icon :size="14" class="mode-chip-icon"><Collection /></el-icon>
                    <span>深度研究</span>
                  </button>
                  <!-- teleported=false：popper 留在组件 DOM 内，scoped 样式直接生效；
                       宽度响应式：320px 满宽在极窄视口会溢出（抗压缩三档规范） -->
                  <el-popover
                    v-model:visible="scopePopoverVisible"
                    placement="top-start"
                    :width="scopePopoverWidth"
                    trigger="click"
                    :teleported="false"
                    popper-class="kb-scope-popper"
                    @show="onScopePopoverShow"
                  >
                    <template #reference>
                      <button
                        class="mode-chip kb-scope-trigger"
                        :class="{ active: knowledgeScopeActive }"
                        title="限定知识工具与深度研究的检索范围"
                      >
                        <el-icon :size="14" class="mode-chip-icon"><Collection /></el-icon>
                        <span>{{
                          knowledgeScopeLabel
                        }}</span>
                      </button>
                    </template>
                    <div class="kb-scope-panel">
                      <div class="kb-scope-title">知识检索范围</div>
                      <div class="kb-scope-hint">
                        限定知识工具与深度研究的检索范围；不选则检索全部可见空间。
                      </div>
                      <el-checkbox-group v-model="selectedSpaceIds" class="kb-scope-list">
                        <el-checkbox
                          v-for="sp in spaces"
                          :key="sp.id"
                          :value="sp.id"
                          class="kb-scope-item"
                        >
                          <span class="kb-scope-item-name">{{ sp.name }}</span>
                        </el-checkbox>
                      </el-checkbox-group>
                      <div v-if="spaces.length === 0" class="kb-scope-empty">
                        暂无可见空间
                      </div>
                      <div class="kb-scope-actions">
                        <button class="kb-scope-btn" @click="clearKnowledgeScope">全部</button>
                        <button class="kb-scope-btn primary" @click="saveKnowledgeScope">
                          应用{{ selectedSpaceIds.length ? `（${selectedSpaceIds.length}）` : '' }}
                        </button>
                      </div>
                    </div>
                  </el-popover>
                </div>
              </div>
              <div class="input-trailing">
                <ModelTrigger
                  v-if="Object.keys(availableModels).length"
                  v-model="selectedModel"
                  :models="availableModels"
                />
                <ContextMeter
                  v-if="agentStore.contextUsage"
                  :used="agentStore.contextUsage.used_tokens"
                  :window="agentStore.contextUsage.context_window"
                  :breakdown="agentStore.contextUsage"
                />
                <button
                  v-if="agentStore.isStreaming"
                  class="send-primary stop-primary"
                  title="停止"
                  @click="handleCancelStream"
                >
                  <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden>
                    <rect x="3" y="3" width="10" height="10" rx="3" fill="currentColor" />
                  </svg>
                </button>
                <button
                  v-else
                  class="send-primary"
                  :class="{ active: inputText.trim() || agentStore.pendingAttachments.length > 0 }"
                  :disabled="
                    (!inputText.trim() && agentStore.pendingAttachments.length === 0) ||
                    agentStore.loading
                  "
                  title="发送"
                  @click="handleSend"
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
          <div v-if="isWelcomeMode" class="suggestion-list">
            <button
              v-for="(prompt, i) in quickPrompts"
              :key="i"
              class="suggestion-item"
              :style="{ animationDelay: `${i * 40}ms` }"
              @click="handleQuickPrompt(prompt)"
            >
              {{ prompt }}
            </button>
          </div>

          <!-- 键盘提示（卡外微 caption，仅非欢迎态显示） -->
          <div v-if="!isWelcomeMode" class="input-hint">
            <span class="hint-item"><kbd>Enter</kbd> 发送</span>
            <span class="hint-item"><kbd>Shift</kbd>+<kbd>Enter</kbd> 换行</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 智能体对话页（/home/workspace/agents/:agentId/chat）
 *
 * 对应路由 WorkspaceAgentChat，承载 ReAct 多步对话：消息按轮分组渲染（工作过程默认折叠）、
 * 聊天/轨迹双视图切换、附件上传与图片预览、上下文压缩标记就地展开、模型选择。
 * 关键交互：按 turn 分组的 computed 是渲染核心——各轮（含进行中）默认折叠只看最终回复，
 * 用户点开折叠条后以手动意图为准（manualTurnOverrides）；流式自动滚底仅在用户本就
 * 位于底部时跟随（stickToBottom），上拉看历史不被拽回，靠回到底部悬浮键一键归位。
 */

import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch, inject } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus,
  Delete,
  ArrowLeft,
  ArrowDown,
  SetUp,
  DocumentCopy,
  Close,
  Download,
  Expand,
  MagicStick,
  Lightning,
  Collection,
  Warning,
} from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import { useWorkbenchStore } from '@/stores/workbench'
import { agentApi } from '@/api/agent'
import { spaceApi } from '@/api/space'
import type {
  AgentMessage,
  AgentCompactionData,
  ContentBlock,
  KnowledgeBindings,
  OpenAICompatToolCall,
  ResearchProgressData,
  Space,
} from '@/api/types'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import ModelTrigger from '@/components/common/ModelTrigger.vue'
import ContextMeter from '@/components/common/ContextMeter.vue'
import CompactionItem from '@/components/agent/CompactionItem.vue'
import PlanCard from '@/components/agent/PlanCard.vue'
import ResearchProgressCard from '@/components/agent/ResearchProgressCard.vue'
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

// 窄屏（≤720px）页内会话侧栏改为悬浮抽屉，默认收起；选中会话后自动收起让位主区
const isNarrowViewport = ref(window.innerWidth <= 720)
const mobileSidebarOpen = ref(false)
window.addEventListener('resize', () => {
  isNarrowViewport.value = window.innerWidth <= 720
  if (!isNarrowViewport.value) mobileSidebarOpen.value = false
})

const inputText = ref('')
const useStream = ref(true)
const enableThinking = ref(false)
// 深度研究开关（请求级）：开启时本轮消息引导模型优先调用 research 工具
const enableResearch = ref(false)

// 深度研究依赖 Agent 勾选 research 工具；未勾选时 hint 注入后模型会空转一轮
// 工具调用再口播失败——开启瞬间明示，避免用户以为开关生效
function toggleDeepResearch() {
  enableResearch.value = !enableResearch.value
  if (
    enableResearch.value &&
    agentStore.currentAgent &&
    !(agentStore.currentAgent.enabled_tools || []).includes('research')
  ) {
    ElMessage.warning('当前智能体未启用 research 工具，深度研究不会执行（请在智能体管理中勾选）')
  }
}

// ===================== 知识范围绑定（会话级，批2 extra_config.knowledge_bindings） =====================
const spaces = ref<Space[]>([])
const selectedSpaceIds = ref<number[]>([])
const knowledgeBindingsLoaded = ref(false)

const knowledgeScopeActive = computed(() => selectedSpaceIds.value.length > 0)
const knowledgeScopeLabel = computed(() =>
  knowledgeScopeActive.value ? `知识范围 ${selectedSpaceIds.value.length}` : '知识范围',
)

async function ensureSpacesLoaded() {
  if (spaces.value.length) return
  try {
    const res = await spaceApi.getSpaces({ skip: 0, limit: 50 })
    spaces.value = res.items
  } catch {
    spaces.value = []
  }
}

async function loadKnowledgeBindings(sessionId: string | null) {
  if (!sessionId) {
    selectedSpaceIds.value = []
    knowledgeBindingsLoaded.value = true
    return
  }
  try {
    const conv = await agentApi.getSession(sessionId)
    selectedSpaceIds.value = [...(conv.extra_config?.knowledge_bindings?.space_ids ?? [])]
  } catch {
    selectedSpaceIds.value = []
  }
  knowledgeBindingsLoaded.value = true
}

async function saveKnowledgeScope() {
  scopePopoverVisible.value = false
  const sessionId = agentStore.currentSessionId
  if (!sessionId) {
    // 新会话尚无 session_id：选择已暂存，首条消息建立会话后自动应用
    ElMessage.info('将在发送首条消息后自动应用')
    return
  }
  const bindings: KnowledgeBindings | null =
    selectedSpaceIds.value.length > 0 ? { space_ids: [...selectedSpaceIds.value] } : null
  try {
    await agentApi.updateKnowledgeBindings(sessionId, bindings)
    ElMessage.success('知识范围已更新')
  } catch {
    ElMessage.error('知识范围保存失败')
  }
}

function clearKnowledgeScope() {
  selectedSpaceIds.value = []
  // 「全部」= 放弃限定检索全部可见空间，选完即收起
  scopePopoverVisible.value = false
}
// 模型选择：'' = Auto（跟随智能体配置）；否则指定本次对话使用的模型
const selectedModel = ref('')
const availableModels = ref<
  Record<string, { max_tokens: number; temperature: number; top_p: number; model_type: string }>
>({})
const expandedReasoning = ref(new Set<number>())
// 工作过程折叠态：按 turn.key 记忆（历史轮默认折叠；当前流式轮自动展开）
const expandedTurns = ref(new Set<string>())
// 用户手动点过折叠条的轮次（这些轮次不再走 isActive 默认态）
const manualTurnOverrides = ref(new Set<string>())
// 压缩标记行就地展开态：按 compaction 消息 id 记忆（dsh 就地 disclosure，与 expandedReasoning 同模式）
const expandedCompactions = ref(new Set<number>())
function toggleCompaction(id: number) {
  if (expandedCompactions.value.has(id)) expandedCompactions.value.delete(id)
  else expandedCompactions.value.add(id)
}

// 计划卡就地展开态：按 plan 消息 id 记忆（同 expandedCompactions 模式）
const expandedPlans = ref(new Set<number>())
function togglePlan(id: number) {
  if (expandedPlans.value.has(id)) expandedPlans.value.delete(id)
  else expandedPlans.value.add(id)
}

// 研究进度卡就地展开态（同 expandedPlans 模式）
const expandedResearch = ref(new Set<number>())
function toggleResearch(id: number) {
  if (expandedResearch.value.has(id)) expandedResearch.value.delete(id)
  else expandedResearch.value.add(id)
}

// 视图模式：聊天（产品化气泡）/ 轨迹（调试向消息时间线，平铺每条消息 + 点击展开详情）
const viewMode = ref<'chat' | 'trajectory'>('chat')

// ===================== 按轮分组 =====================
// 一轮 = 一条用户消息 + 其后的所有 tool/assistant/system 消息（直到下一条用户消息）。
// 只展示该轮「最后一条 assistant」的最终回复；其前的 tool/中间 assistant/思考过程
// 按序折叠在 avatar 折叠头下，并显示该轮总耗时。
interface ReActStep {
  // 一个 ReAct 步骤 = AI 一次响应（决策消息 content + tool_calls）+ 其调用的工具执行结果
  ai: AgentMessage | null
  tools: AgentMessage[]
}

interface ChatTurn {
  key: string
  userMsg: AgentMessage | null
  items: AgentMessage[]
  compactionItems: AgentMessage[]
  planItems: AgentMessage[]
  noticeItems: AgentMessage[]
  researchItems: AgentMessage[]
  finalAssistant: AgentMessage | null
  workItems: AgentMessage[]
  steps: ReActStep[]
  startTime: number
  endTime: number | null
  isActive: boolean
}

function tsOf(iso: string | null | undefined): number {
  if (!iso) return 0
  const t = new Date(iso).getTime()
  return Number.isNaN(t) ? 0 : t
}

function formatDuration(ms: number): string {
  if (!ms || ms < 0) ms = 0
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const sec = s % 60
  if (m < 60) return `${m}m${sec.toString().padStart(2, '0')}s`
  const h = Math.floor(m / 60)
  return `${h}h${(m % 60).toString().padStart(2, '0')}m`
}

/** 把扁平消息流按「一条用户消息 + 其后所有消息」切轮，并给每轮归类最终回复与 ReAct 步骤 */
const turns = computed<ChatTurn[]>(() => {
  const msgs = agentStore.messages
  const result: ChatTurn[] = []
  let current: ChatTurn | null = null
  for (const msg of msgs) {
    if (msg.role === 'user') {
      if (current) result.push(current)
      current = {
        key: `turn-${msg.id}`,
        userMsg: msg,
        items: [],
        compactionItems: [],
        planItems: [],
        noticeItems: [],
        researchItems: [],
        finalAssistant: null,
        workItems: [],
        steps: [],
        startTime: tsOf(msg.created_at),
        endTime: null,
        isActive: false,
      }
    } else if (current) {
      // compaction/plan/notice 标记行分流到专属列表，不计入 items/workItems/steps，
      // 也不参与 finalAssistant 检测（role!=='assistant' 天然排除）。
      // plan/notice 不分流会掉进 byIter（iteration ?? 0 建空步虚增 steps.length）
      if (msg.role === 'compaction') {
        current.compactionItems.push(msg)
      } else if (msg.role === 'plan') {
        current.planItems.push(msg)
      } else if (msg.role === 'research') {
        current.researchItems.push(msg)
      } else if (msg.role === 'notice') {
        current.noticeItems.push(msg)
      } else {
        current.items.push(msg)
      }
    } else {
      // 没有前置用户消息的孤立消息（如历史首条是 assistant 或 compaction）
      current = {
        key: `turn-orphan-${msg.id}`,
        userMsg: null,
        items: msg.role === 'compaction' || msg.role === 'plan' || msg.role === 'notice' ? [] : [msg],
        compactionItems: msg.role === 'compaction' ? [msg] : [],
        planItems: msg.role === 'plan' ? [msg] : [],
        noticeItems: msg.role === 'notice' ? [msg] : [],
        researchItems: msg.role === 'research' ? [msg] : [],
        finalAssistant: null,
        workItems: [],
        steps: [],
        startTime: tsOf(msg.created_at),
        endTime: null,
        isActive: false,
      }
    }
  }
  if (current) result.push(current)

  for (const t of result) {
    // 找该轮最后一条有内容的 assistant 作为最终回复
    let lastIdx = -1
    for (let i = t.items.length - 1; i >= 0; i--) {
      const it = t.items[i]
      // 排除含 tool_call 块的决策消息：那是「AI 决定调用工具」的中间步骤，
      // content 是该轮决策文本而非最终回答；即便它是该轮最后一条 assistant 也不能当最终回复。
      // 判别基于 ContentBlock（不依赖 extra.tool_calls 字段存在性），空 content 的决策也能正确归类
      if (it && it.role === 'assistant' && it.content && !hasToolCallBlocks(it)) {
        lastIdx = i
        break
      }
    }
    if (lastIdx >= 0) {
      const final = t.items[lastIdx]
      if (final) {
        t.finalAssistant = final
        t.workItems = t.items.filter((_, i) => i !== lastIdx)
        t.endTime = tsOf(final.created_at)
      }
    } else {
      t.workItems = [...t.items]
      const lastItem = t.items[t.items.length - 1]
      if (lastItem) t.endTime = tsOf(lastItem.created_at)
    }

    // 按 ReAct 步骤分组：优先用 iteration 字段（同一轮的 assistant 决策 + tool 归同一步），
    // 还原 LLM 一次响应（ai: content + tool_calls）+ 工具执行（tools）的原始结构。
    // 无 iteration（历史数据）fallback 到老的顺序推断（assistant 开新 step，tool 归入）。
    const steps: ReActStep[] = []
    const hasIter = t.workItems.some((it) => it.iteration != null)
    if (hasIter) {
      const byIter = new Map<number, ReActStep>()
      const order: number[] = []
      for (const item of t.workItems) {
        const iter = item.iteration ?? 0
        let step = byIter.get(iter)
        if (!step) {
          step = { ai: null, tools: [] }
          byIter.set(iter, step)
          order.push(iter)
        }
        if (item.role === 'assistant') {
          step.ai = item
        } else if (item.role === 'tool') {
          step.tools.push(item)
        }
      }
      for (const iter of order) steps.push(byIter.get(iter)!)
    } else {
      let cur: ReActStep | null = null
      for (const item of t.workItems) {
        if (item.role === 'assistant') {
          if (cur) steps.push(cur)
          cur = { ai: item, tools: [] }
        } else if (item.role === 'tool') {
          if (!cur) cur = { ai: null, tools: [] }
          cur.tools.push(item)
        }
      }
      if (cur) steps.push(cur)
    }
    t.steps = steps
  }

  // 当前正在流式/加载的最后一轮标记为 active
  if (result.length && (agentStore.isStreaming || agentStore.loading)) {
    const last = result[result.length - 1]
    if (last) last.isActive = true
  }
  return result
})

function isTurnExpanded(turn: ChatTurn): boolean {
  // 默认态：折叠（含进行中——思考层/工具轨迹不抢视觉焦点，进行中状态由折叠条
  // 「生成中…」文案表达）；用户点过折叠条后以手动意图为准（manualOverrides
  // 记住该轮被显式展开/收起）
  if (manualTurnOverrides.value.has(turn.key)) {
    return expandedTurns.value.has(turn.key)
  }
  return false
}

function toggleTurn(turn: ChatTurn) {
  const next = !isTurnExpanded(turn)
  manualTurnOverrides.value.add(turn.key)
  if (next) expandedTurns.value.add(turn.key)
  else expandedTurns.value.delete(turn.key)
}

// 折叠条状态标签：固定两段式「思考中/思考完成 · 耗时」，保证任意轮次长度一致；
// 状态差异由 spinner + 主题色 + 「中/完成」一词之差表达，步数明细展开折叠条可见
function foldStatusLabel(turn: ChatTurn): string {
  const duration = turn.isActive ? activeTurnDuration(turn) : turnDuration(turn)
  return duration ? `${turn.isActive ? '思考中' : '思考完成'} · ${duration}` : turn.isActive ? '思考中' : '思考完成'
}

// 该轮总耗时（无有效时间区间返回空串，由调用方省略该段）
function turnDuration(turn: ChatTurn): string {
  if (turn.endTime && turn.startTime) {
    const ms = turn.endTime - turn.startTime
    if (ms > 0) return formatDuration(ms)
  }
  return ''
}

const messagesRef = ref<HTMLElement>()
const fileInputRef = ref<HTMLInputElement>()
const uploadingFiles = ref(false)

function triggerFileSelect() {
  fileInputRef.value?.click()
}

/** 校验文件类型/大小后并行上传附件，逐个报告失败项 */
async function handleFileSelected(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files?.length) return
  const maxSize = 20 * 1024 * 1024
  // 与后端 ALLOWED_FILE_TYPES 对齐（无 doc：后端不支持 .doc 解析，不提供"自动转换"）
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
    const results = await Promise.allSettled(validFiles.map((f) => agentStore.uploadAttachment(f)))
    for (let i = 0; i < results.length; i++) {
      const result = results[i]
      const failedFile = validFiles[i]
      if (result?.status === 'rejected') {
        ElMessage.error(`上传失败: ${failedFile?.name ?? ''}`)
      }
    }
    uploadingFiles.value = false
  }
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

function getMessageAttachments(msg: AgentMessage): Array<{
  id?: number
  filename: string
  file_type?: string
  file_size?: number
  storage_path?: string
}> {
  const extra = msg.extra as Record<string, unknown> | null | undefined
  return (
    (extra?.attachments as Array<Record<string, unknown>> | undefined)?.map((a) => ({
      id: typeof a.id === 'number' ? a.id : undefined,
      filename: typeof a.filename === 'string' ? a.filename : '',
      file_type: typeof a.file_type === 'string' ? a.file_type : undefined,
      file_size: typeof a.file_size === 'number' ? a.file_size : undefined,
      storage_path: typeof a.storage_path === 'string' ? a.storage_path : undefined,
    })) ?? []
  )
}

// 压缩标记的 extra.compaction 提取（模板内不做复杂类型断言）
function getCompactionData(msg: AgentMessage): AgentCompactionData | undefined {
  return (msg.extra as Record<string, unknown> | null | undefined)?.compaction as
    | AgentCompactionData
    | undefined
}

/** 计划卡的 extra.plan 提取（字段缺省安全：历史数据无 statuses/summary） */
function getPlanData(msg: AgentMessage): {
  title?: string
  steps: string[]
  statuses?: string[]
  summary?: string
  interrupted?: boolean
} {
  const plan = (
    msg.extra as { plan?: Record<string, unknown> } | null | undefined
  )?.plan
  return {
    title: typeof plan?.title === 'string' ? plan.title : undefined,
    steps: Array.isArray(plan?.steps) ? (plan?.steps as string[]) : [],
    statuses: Array.isArray(plan?.statuses) ? (plan?.statuses as string[]) : undefined,
    summary: typeof plan?.summary === 'string' ? plan.summary : undefined,
    interrupted: plan?.interrupted === true,
  }
}

/** 研究进度卡的 extra.research 提取（字段缺省安全：历史/异常数据兜底空态） */
function getResearchData(msg: AgentMessage): ResearchProgressData {
  const r = (
    msg.extra as { research?: Record<string, unknown> } | null | undefined
  )?.research
  return {
    status: typeof r?.status === 'string' ? r.status : 'analyzing',
    current_step: typeof r?.current_step === 'string' ? r.current_step : undefined,
    progress_percent: typeof r?.progress_percent === 'number' ? r.progress_percent : 0,
    completed_tasks: typeof r?.completed_tasks === 'number' ? r.completed_tasks : 0,
    total_tasks: typeof r?.total_tasks === 'number' ? r.total_tasks : 0,
    plan: (r?.plan as ResearchProgressData['plan']) ?? null,
  }
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

/** 拉取附件图片为 Blob URL 缓存用于预览（img 标签带不上鉴权头，须走带 token 的 fetch） */
async function loadAttachmentImage(attId: number) {
  if (imageBlobCache.has(attId)) return
  try {
    const token = localStorage.getItem('access_token')
    const res = await fetch(`${baseURL}/agent/attachments/${attId}/download`, {
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

const textareaRef = ref<HTMLTextAreaElement>()
const expandedTools = ref(new Set<number>())

// 进行中折叠条的实时秒数：elapsedTick 每秒自增驱动重算（生成期间折叠条显示「思考中 · Ns」）
const elapsedTick = ref(0)
let elapsedTimer: number | null = null
// 进行中折叠条耗时：起点=本轮用户消息时间，终点=now（无有效起点返回空串，折叠条省略耗时段）
function activeTurnDuration(turn: ChatTurn): string {
  void elapsedTick.value
  if (!turn.startTime) return ''
  return formatDuration(Date.now() - turn.startTime)
}

// 轨迹内每个 AI 步骤的展开态：按 step 在轮内的唯一键（turnKey:index）记忆，默认收起。
// 步骤行摘要 = 思考/回答首行 + 工具调用名，展开看完整 reasoning/文本/参数。
const expandedSteps = ref(new Set<string>())
function toggleStep(key: string) {
  if (expandedSteps.value.has(key)) expandedSteps.value.delete(key)
  else expandedSteps.value.add(key)
}

const quickPrompts = [
  '你好，你能帮我做什么？',
  '帮我搜索知识库中的相关内容',
  '分析一下这个问题的原因',
  '总结一下要点',
]

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

function autoResize() {
  nextTick(() => {
    const el = textareaRef.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  })
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
watch(
  () => agentStore.pendingAttachments.length,
  () => {
    for (const att of agentStore.pendingAttachments) {
      if (isImageFile(att.file_type) && att.id && !imageBlobCache.has(att.id)) {
        loadAttachmentImage(att.id)
      }
    }
  },
)

// 会话切换时同步知识范围绑定（新会话/未加载时重置为不限定）。
// pendingScopeApply：发送首条消息建立会话后，watch 触发的加载会 GET 到
// extra_config=null 并清空用户刚勾选的范围——跳过这一次，保留选择等流结束后自动应用
//（流式对话期间会话行被 chat 事务锁定，流中 PUT 绑定会 1205 锁超时）。
let pendingScopeApply = false
watch(
  () => agentStore.currentSessionId,
  (sid) => {
    if (pendingScopeApply) {
      pendingScopeApply = false
      return
    }
    loadKnowledgeBindings(sid)
  },
  { immediate: true },
)

async function applyKnowledgeScope() {
  const sessionId = agentStore.currentSessionId
  if (!sessionId) return
  const bindings: KnowledgeBindings | null =
    selectedSpaceIds.value.length > 0 ? { space_ids: [...selectedSpaceIds.value] } : null
  try {
    await agentApi.updateKnowledgeBindings(sessionId, bindings)
    ElMessage.success('知识范围已应用')
  } catch {
    ElMessage.error('知识范围保存失败')
  }
}

// 知识范围 popover 宽度：桌面 320，窄视口收进边距（teleported=false 下
// overflow:hidden 祖先会裁切溢出部分）
const scopePopoverWidth = computed(() => Math.min(320, window.innerWidth - 24))

// 受控开关：应用/全部后主动收起面板
const scopePopoverVisible = ref(false)

// 列表视口自适应高度：popper 向上弹出（top-start），列表过高会把标题/首项
// 顶出视口上缘被裁。弹出时按「chip 上缘到视口顶的可用空间 − 面板其余部分
// 固定高度（壳内距+标题+说明+操作行+间隙 ≈ 152px）− 8px 余量」精确钳制；
// CSS 拿不到 chip 位置，只能在 show 时量。下限 120px 保证至少可见数项。
function onScopePopoverShow() {
  ensureSpacesLoaded()
  nextTick(() => {
    const chip = document.querySelector<HTMLElement>('.kb-scope-trigger')
    const list = document.querySelector<HTMLElement>('.kb-scope-list')
    if (!chip || !list) return
    const available = chip.getBoundingClientRect().top - 8 - 152
    list.style.maxHeight = `${Math.max(120, Math.min(224, available))}px`
  })
}

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
  workbench.resetSelection()
}

async function handleSelectConversation(sessionId: string) {
  if (agentStore.currentSessionId === sessionId) return
  // 流式进行中先中止：SSE 回调写 store 全局 messages，不中止会把旧会话增量写进新会话
  if (agentStore.isStreaming) agentStore.cancelStream()
  await agentStore.fetchMessages(sessionId)
  // 切换会话后清空抽屉选中态，避免残留上一会话工具结果
  workbench.resetSelection()
  scrollToBottom()
  if (isNarrowViewport.value) mobileSidebarOpen.value = false
}

// 在右侧抽屉打开该工具调用的结果详情（chat 模式工具卡片用）
function openToolInDrawer(callId: string | null) {
  if (!callId) return
  workbench.selectToolCall(callId)
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

/** 发送消息：空文本但有附件时以默认文案触发文档分析 */
async function handleSend() {
  const content = inputText.value.trim()
  const hasAttachments = agentStore.pendingAttachments.length > 0
  if (!content && !hasAttachments) return

  const sendContent = content || (hasAttachments ? '请分析上传的文档' : '')
  inputText.value = ''
  // 主动发送 = 意图朝向最新内容：即使此前上拉看历史，也恢复自动跟随并滚到底
  stickToBottom.value = true
  scrollToBottom()
  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.style.height = 'auto'
    }
  })

  try {
    const attachmentIds = agentStore.pendingAttachments.map((a) => a.id)
    const opts = {
      enable_thinking: enableThinking.value,
      deep_research: enableResearch.value,
      llm_model: selectedModel.value || undefined,
      attachmentIds: attachmentIds.length > 0 ? attachmentIds : undefined,
    }
    // 新会话 + 已勾选范围：会话建立后 watch 跳过清空（pendingScopeApply），
    // 流结束后再 PUT——流中会话行被 chat 事务锁定，流中写绑定会锁超时
    const shouldApplyScope =
      !agentStore.currentSessionId && selectedSpaceIds.value.length > 0
    const sessionAtSend = agentStore.currentSessionId
    pendingScopeApply = shouldApplyScope
    try {
      if (useStream.value) {
        await agentStore.sendMessageStream(agentId.value, sendContent, opts)
      } else {
        await agentStore.sendMessage(agentId.value, sendContent, opts)
      }
      if (shouldApplyScope) await applyKnowledgeScope()
    } finally {
      // 复位绑定发送生命周期：失败/中止时不能让标记挂着——否则 watch 会把
      // 下一次会话切换的绑定加载跳过，残留勾选可写错其他会话
      if (agentStore.currentSessionId === sessionAtSend) pendingScopeApply = false
    }
  } catch {
    ElMessage.error('发送失败，请重试')
  }
}

function handleCancelStream() {
  agentStore.cancelStream()
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

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

// Tool call helpers
function toContentBlocks(msg: AgentMessage | null): ContentBlock[] {
  // 把 assistant 消息的 reasoning/content/extra.tool_calls 三字段统一成 block 数组，
  // 前端按 kind 分发渲染（reasoning → think, text → 回答, tool_call → 工具调用）。
  // 纯表示层视图模型，后端存储不变。决策消息 blocks=[reasoning?,text?,tool_call*]，
  // 最终回答 blocks=[reasoning?,text?]，纯 tool 消息不走此路径。
  if (!msg) return []
  const blocks: ContentBlock[] = []
  if (msg.reasoning) blocks.push({ kind: 'reasoning', text: msg.reasoning })
  if (msg.content) blocks.push({ kind: 'text', text: msg.content })
  const tcs = msg.extra?.tool_calls as OpenAICompatToolCall[] | undefined
  if (tcs?.length) {
    for (const tc of tcs) {
      blocks.push({
        kind: 'tool_call',
        id: tc.id,
        name: tc.function.name,
        arguments: tc.function.arguments,
      })
    }
  }
  return blocks
}

function hasToolCallBlocks(msg: AgentMessage | null): boolean {
  // 判定 assistant 消息是否含工具调用块（决策消息），用于 finalAssistant 归类
  return toContentBlocks(msg).some((b) => b.kind === 'tool_call')
}

/** 步骤摘要行文案：思考取首行截断，纯回答取首行，工具调用列名（最多两个 + 省略） */
function stepSummary(step: ReActStep): string {
  const blocks = toContentBlocks(step.ai)
  const toolCalls = blocks.filter((b) => b.kind === 'tool_call')
  const think = blocks.find((b) => b.kind === 'reasoning')
  const text = blocks.find((b) => b.kind === 'text')
  const parts: string[] = []
  if (toolCalls.length) {
    const names = toolCalls.map((b) => (b.kind === 'tool_call' ? b.name : ''))
    parts.push(
      names.length > 2 ? `调用 ${names.slice(0, 2).join('、')} 等 ${names.length} 个工具` : `调用 ${names.join('、')}`,
    )
  }
  const firstLine = (source: string) => {
    const line = source.trim().split('\n').find((l) => l.trim()) || ''
    return line.length > 40 ? line.slice(0, 40) + '…' : line
  }
  if (think) parts.push(firstLine(think.text))
  else if (text && !toolCalls.length) parts.push(firstLine(text.text))
  return parts.join(' · ') || '思考中'
}

function formatToolArgs(args: string | undefined): string {
  // tool_calls.function.arguments 是 JSON 字符串，parse 后格式化展示
  if (!args) return ''
  try {
    return JSON.stringify(JSON.parse(args), null, 2)
  } catch {
    return args
  }
}

function getToolRecord(callId: string | null) {
  if (!callId) return null
  return agentStore.toolCalls.find((c) => c.callId === callId)
}

function getToolDuration(callId: string | null) {
  return getToolRecord(callId)?.durationMs
}

function getToolStatus(callId: string | null) {
  // 实时流期间 toolCalls 记录一定存在（onToolCall 同时建记录与消息）；
  // 走到默认分支只可能是历史回放且未匹配到记录，持久化的 tool 消息必然已结束，故默认 completed
  return getToolRecord(callId)?.status || 'completed'
}

function getToolStatusLabel(callId: string | null) {
  const status = getToolStatus(callId)
  const map: Record<string, string> = {
    running: '执行中',
    completed: '完成',
    failed: '失败',
    pending: '等待中',
  }
  return map[status] || status
}

function toggleToolExpand(msgId: number) {
  if (expandedTools.value.has(msgId)) {
    expandedTools.value.delete(msgId)
  } else {
    expandedTools.value.add(msgId)
  }
}

function truncateResult(text: string): string {
  if (text.length <= 2000) return text
  return text.slice(0, 2000) + '\n... (已截断)'
}

async function fetchModels() {
  try {
    const data = await agentApi.getModels()
    availableModels.value = data.models
  } catch {
    // ignore
  }
}

onMounted(async () => {
  await agentStore.initForAgent(agentId.value)
  fetchModels()
  // 进行中折叠条的实时秒数：每秒 tick 驱动「思考中 · Ns」刷新（仅流式期间有活跃轮）
  elapsedTimer = window.setInterval(() => {
    elapsedTick.value++
  }, 1000)
})

onBeforeUnmount(() => {
  if (elapsedTimer !== null) window.clearInterval(elapsedTimer)
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
  /* 与工作台目录栏同底色：左两栏（目录+会话）一体暖灰，聊天画布独白聚焦 */
  background: var(--color-bg-sidebar);
}

.chat-sidebar.compact {
  width: 220px;
}

/* 窄屏断点：固定 220px 侧栏不收缩，会把聊天主区挤到不可用（320px 下仅剩 ~50px）；
   断点内改绝对定位悬浮，主区占满全宽，经顶栏按钮开合 */
@media (max-width: 720px) {
  .chat-sidebar {
    position: absolute;
    z-index: 30;
    height: 100%;
    box-shadow: var(--shadow-lg);
    transform: translateX(-100%);
    transition: transform 0.25s ease;
  }

  .chat-sidebar.mobile-open {
    transform: translateX(0);
  }
}

.sidebar-top {
  padding: var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

.sidebar-toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-base);
}

.sidebar-toggle-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-lg);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-base);
}

.back-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.new-chat-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  color: var(--color-text);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition: all var(--transition-base);
}

.new-chat-btn:hover {
  border-color: var(--color-border);
  background: var(--color-bg-hover);
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
  /* 与目录栏 list-item.active 同款中性选中语言（灰底+墨色指示条），两栏一体 */
  background: var(--color-bg-hover);
}

.conv-item.active .conv-title {
  color: var(--color-text);
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
  background: var(--color-text);
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
  background: var(--color-bg-elevated);
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
  background: var(--color-bg-header);
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
  min-width: 0;
}

.header-left {
  display: flex;
  align-items: center;
  min-width: 0;
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
  flex-shrink: 0;
}

.header-title {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 视图切换 tab（聊天 / 轨迹）：分段控件，与左侧助手徽标分组留白 */
.header-tabs {
  display: flex;
  gap: 2px;
  margin-left: var(--space-4);
  padding: 2px;
  background: var(--color-bg-hover);
  border-radius: var(--radius-full);
}

.view-pill {
  padding: 3px 14px;
  border: none;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
}

.view-pill:hover {
  color: var(--color-text);
}

.view-pill.active {
  background: var(--color-bg-card);
  box-shadow: var(--shadow-xs);
  color: var(--color-text);
  font-weight: var(--weight-medium);
}

/* 轨迹视图容器 */
.trajectory-container {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding-top: 48px;
  background: var(--color-bg-elevated);
}

/* ========================================
   Welcome Greeting（克制排版：纯色标题 + 灰字描述，无动画噱头）
   ======================================== */
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

/* ========================================
   Suggestion Pills (deer-flow Suggestion 对齐：输入卡下方一排胶囊，stagger 入场)
   ======================================== */
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

.message-row {
  display: flex;
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

/* ========================================
   按轮分组：左 avatar + 右内容列 + 工作过程 + 最终回复
   ======================================== */
.chat-turn {
  margin-bottom: 32px;
}

.assistant-turn {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-top: var(--space-2);
  animation: messageIn 0.35s ease forwards;
}

.turn-avatar {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-full);
  background: var(--color-chip-active);
  color: var(--color-chip-active-text);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  flex-shrink: 0;
  user-select: none;
}

.turn-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* 折叠线：已完成耗时 / 生成中 */
.fold-line {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  padding: 3px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.fold-line:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-text);
}

/* 进行中折叠条：主题色 + spinner，与已完成态区分 */
.fold-line.running {
  color: var(--color-primary, var(--color-text));
  border-color: var(--color-border);
}

.fold-spinner {
  width: 10px;
  height: 10px;
  flex-shrink: 0;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: fold-spin 0.8s linear infinite;
}

@keyframes fold-spin {
  to {
    transform: rotate(360deg);
  }
}

/* 轨迹内 AI 步骤：摘要行（默认收起）+ 展开详情 */
.ai-step {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.ai-step-summary {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: 5px 10px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  font-family: var(--font-body);
  cursor: pointer;
  text-align: left;
  transition: all var(--transition-fast);
  min-width: 0;
}

.ai-step-summary:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-text);
}

.ai-step-kind {
  flex-shrink: 0;
  font-weight: var(--weight-semibold);
}

.ai-step-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ai-step .expand-icon {
  flex-shrink: 0;
  margin-left: auto;
  transition: transform var(--transition-fast);
  color: inherit;
}

.ai-step .expand-icon.expanded {
  transform: rotate(180deg);
}

.fold-chevron {
  transition: transform var(--transition-fast);
  color: inherit;
}

.fold-chevron.expanded {
  transform: rotate(180deg);
}

/* 纠偏警告行（loop_detection）：常显轻量提示 */
.notice-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  width: fit-content;
  max-width: 100%;
  padding: 4px 12px;
  border: 1px solid var(--color-warning-border, rgba(245, 158, 11, 0.35));
  border-radius: var(--radius-full);
  background: var(--color-warning-bg, rgba(245, 158, 11, 0.08));
  color: var(--color-warning-text, #b45309);
  font-size: var(--text-xs);
  margin: var(--space-1) 0;
  min-width: 0;
}

.notice-icon {
  flex-shrink: 0;
  margin-top: 2px;
}

.notice-text {
  word-break: break-word;
  overflow-wrap: anywhere;
  min-width: 0;
}

/* 工作过程时间线 */
.work-trail {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: var(--space-1) 0 var(--space-2) var(--space-2);
  padding: var(--space-2) 0 var(--space-2) var(--space-4);
  border-left: 2px solid var(--color-border-light);
}

.work-assistant {
  padding: var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card-elevated);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

.work-assistant :deep(p) {
  margin: 0 0 8px;
}

.work-assistant :deep(p:last-child) {
  margin-bottom: 0;
}

/* AI 输出单元：还原 LLM 一次响应（reasoning + content + tool_calls），不分离不合成 */
.ai-output {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card-elevated);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}
.ai-output :deep(p:last-child) {
  margin-bottom: 0;
}
.ai-reasoning {
  border-left: 2px solid var(--color-border-light);
  padding-left: var(--space-2);
  color: var(--color-text-secondary);
  font-style: italic;
}
.ai-content {
  color: var(--color-text-secondary);
}
/* recall tools：LLM 输出的 tool_calls（工具名 + 参数），作为 ai-output 的直接子块 */
.ai-tool-call {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2);
  border-radius: var(--radius-md);
  background: var(--color-bg-card-elevated);
}
.ai-tool-name {
  font-family: var(--font-mono, monospace);
  font-weight: 600;
  color: var(--color-text-primary, var(--color-text-secondary));
}
.ai-tool-args {
  margin: 0;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-md);
  background: var(--color-bg-card-elevated);
  font-family: var(--font-mono, monospace);
  font-size: var(--text-xs, 12px);
  color: var(--color-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

/* 最终回复 */
.final-answer {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.final-answer .message-text {
  font-size: var(--text-base);
  line-height: var(--leading-relaxed);
  word-break: break-word;
}

.final-answer .message-actions {
  align-self: flex-start;
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

.file-icon-box.file-pdf {
  background: var(--color-file-pdf);
}
.file-icon-box.file-doc {
  background: var(--color-file-doc);
}
.file-icon-box.file-txt {
  background: var(--color-file-txt);
}
.file-icon-box.file-md {
  background: var(--color-file-md);
}
.file-icon-box.file-default {
  background: var(--color-file-other);
}

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

.tool-header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.tool-drawer-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.tool-drawer-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-primary);
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
  background: var(--color-primary-muted);
  color: var(--color-text-secondary);
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

.typing-dot:nth-child(2) {
  animation-delay: 0.2s;
}
.typing-dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes dotPulse {
  0%,
  60%,
  100% {
    opacity: 0.3;
    transform: scale(0.8);
  }
  30% {
    opacity: 1;
    transform: scale(1);
  }
}

/* ========================================
   Input Area — Pill Shape
   ======================================== */
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

/* 模式 chip：深度思考 / 流式输出 */
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

/* 知识范围弹层面板（el-popover 内，非 scoped 生效域需 :global） */
.kb-scope-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.kb-scope-title {
  font-size: 13px;
  font-weight: var(--weight-semibold, 600);
  color: var(--color-text);
}

.kb-scope-hint {
  font-size: 12px;
  color: var(--color-text-tertiary, #a1a1aa);
  line-height: 1.5;
  margin-top: -6px;
}

.kb-scope-list {
  display: flex;
  flex-direction: column;
  /* 动态上限由 onScopePopoverShow 按 chip 到视口顶的可用空间精确设置；
     此处 160px 仅作 CSS 加载先于 show 测量的保底，防极端场景顶出视口 */
  max-height: 160px;
  overflow-y: auto;
  margin: 0 -6px;
  padding: 0 6px;
  /* 窄列表滚动条贴边难点中：留出右缘呼吸空隙 */
  scrollbar-gutter: stable;
}

.kb-scope-item {
  height: 30px;
  /* flex column 列表内禁收缩：不禁则超容器高的项被均摊压扁（20px），
     scrollHeight==clientHeight 永不滚动 */
  flex-shrink: 0;
  margin-right: 0;
  padding: 0 8px;
  border-radius: var(--radius-md, 8px);
  transition: background var(--transition-fast);
}

.kb-scope-item:hover {
  background: var(--color-bg-hover);
}

.kb-scope-item-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 240px;
  display: inline-block;
  vertical-align: bottom;
  font-size: 13px;
  color: var(--color-text);
}

.kb-scope-empty {
  font-size: 12px;
  color: var(--color-text-tertiary, #a1a1aa);
  padding: 8px 0;
  text-align: center;
}

.kb-scope-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  border-top: 1px solid var(--color-border-light);
  padding-top: 10px;
}

.kb-scope-btn {
  height: 28px;
  padding: 0 14px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md, 8px);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.kb-scope-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
  border-color: var(--color-border);
}

.kb-scope-btn.primary {
  background: var(--color-chip-active);
  border-color: var(--color-chip-active);
  color: var(--color-chip-active-text);
  font-weight: var(--weight-medium, 500);
}

.kb-scope-btn.primary:hover {
  background: var(--color-send-active-hover, #52525b);
  border-color: var(--color-send-active-hover, #52525b);
  color: var(--color-chip-active-text);
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

/* ========================================
   Input Footer — Quick Actions
   ======================================== */
/* (已合并进 .input-card 底部 .input-row，旧 .input-footer / .quick-actions / .action-chip 废弃) */

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
  background: var(--color-file-image-bg);
  color: var(--color-file-image);
}
</style>

<style>
/* 知识范围 popper 外壳（teleported=false 留在组件内，但 popper 类不在任何
   scoped 作用域，需全局穿透对齐输入卡设计语言：大圆角 + 精修阴影 + 呼吸感内距） */
.kb-scope-popper.el-popover.el-popper {
  padding: 14px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-lg);
}
</style>
