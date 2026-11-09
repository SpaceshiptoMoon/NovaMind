<template>
  <div class="work-trail">
    <template v-for="(step, si) in turn.steps" :key="si">
      <!-- AI 输出（LLM 一次响应）：摘要行默认收起，展开看完整 reasoning/文本/工具参数 -->
      <div v-if="step.ai && toContentBlocks(step.ai).length" class="ai-step">
        <button class="ai-step-summary" @click="toggleStep(si)">
          <span class="ai-step-kind">{{
            toContentBlocks(step.ai).some((b) => b.kind === 'tool_call') ? '调用工具' : '已完成思考'
          }}</span>
          <span class="ai-step-text">{{ stepSummary(step) }}</span>
          <el-icon :size="12" class="expand-icon" :class="{ expanded: expandedSteps.has(si) }">
            <ArrowDown />
          </el-icon>
        </button>
        <div v-if="expandedSteps.has(si)" class="ai-output">
          <template v-for="(block, bi) in toContentBlocks(step.ai)" :key="bi">
            <div v-if="block.kind === 'reasoning'" class="ai-reasoning">
              <MarkdownRenderer :content="block.text" />
            </div>
            <div v-else-if="block.kind === 'text'" class="ai-content">
              <MarkdownRenderer :content="block.text" />
            </div>
            <div v-else-if="block.kind === 'tool_call'" class="ai-tool-call">
              <span class="ai-tool-name">{{ block.name }}</span>
              <pre v-if="block.arguments" class="ai-tool-args">{{ formatToolArgs(block.arguments) }}</pre>
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
              <span v-if="toolDuration(tool.tool_call_id)" class="tool-duration">
                {{ toolDuration(tool.tool_call_id) }}ms
              </span>
              <span class="tool-status" :class="toolStatus(tool.tool_call_id)">
                {{ toolStatusLabel(toolStatus(tool.tool_call_id)) }}
              </span>
            </div>
            <div class="tool-header-actions">
              <button
                class="tool-drawer-btn"
                title="在右侧抽屉查看"
                @click.stop="emit('open-tool', tool.tool_call_id)"
              >
                <el-icon :size="12"><Expand /></el-icon>
              </button>

              <el-icon :size="12" class="expand-icon" :class="{ expanded: expandedTools.has(tool.id) }">
                <ArrowDown />
              </el-icon>
            </div>
          </div>
          <div v-if="expandedTools.has(tool.id)" class="tool-body">
            <!-- wiki 工具结果：条目带 url 时渲染可点链接直达阅读页 -->
            <div v-if="wikiLinks(tool).length > 0" class="tool-section">
              <div class="tool-section-label">Wiki 页面</div>
              <div class="wiki-tool-links">
                <a
                  v-for="link in wikiLinks(tool)"
                  :key="link.url"
                  class="wiki-tool-link"
                  :href="link.url"
                  @click.prevent="emit('open-wiki', link.url)"
                >
                  {{ link.title }}
                </a>
              </div>
            </div>
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
      <div class="reasoning-header" @click="reasoningExpanded = !reasoningExpanded">
        <span class="reasoning-label">思考过程</span>
        <el-icon :size="12" class="expand-icon" :class="{ expanded: reasoningExpanded }">
          <ArrowDown />
        </el-icon>
      </div>
      <div v-if="reasoningExpanded" class="reasoning-body">
        <MarkdownRenderer :content="turn.finalAssistant.reasoning" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 工作过程时间线（一轮内的 ReAct 轨迹）：AI 步骤摘要 → 展开完整输出、
 * 工具执行卡 → 展开结果、最终思考段。三个展开态全部组件内自持
 * （每轮一个实例，互不串扰），工具详情跳右面板与 wiki 跳转上抛父层。
 */
import { ref } from 'vue'
import { ArrowDown, Expand, SetUp } from '@element-plus/icons-vue'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import type { ToolCallRecord } from '@/api/types'
import type { ChatTurn } from '@/utils/chatRender'
import {
  findToolRecord,
  formatToolArgs,
  stepSummary,
  toContentBlocks,
  toolStatusLabel,
  truncateResult,
  wikiToolLinks,
} from '@/utils/chatRender'

const props = defineProps<{
  turn: ChatTurn
  /** 工具执行记录（duration/status 查询源），单聊为 agentStore.toolCalls */
  toolCalls: ToolCallRecord[]
}>()

const emit = defineEmits<{
  (e: 'open-tool', callId: string | null): void
  (e: 'open-wiki', url: string): void
}>()

// 展开态全部组件内自持：AI 步骤摘要（按轮内索引）、工具卡（按消息 id）、最终思考段
const expandedSteps = ref(new Set<number>())
const expandedTools = ref(new Set<number>())
const reasoningExpanded = ref(false)

function toggleStep(si: number) {
  if (expandedSteps.value.has(si)) expandedSteps.value.delete(si)
  else expandedSteps.value.add(si)
}

function toggleToolExpand(msgId: number) {
  if (expandedTools.value.has(msgId)) expandedTools.value.delete(msgId)
  else expandedTools.value.add(msgId)
}

function toolDuration(callId: string | null): number | undefined {
  return findToolRecord(props.toolCalls, callId)?.durationMs
}

function toolStatus(callId: string | null): string {
  return findToolRecord(props.toolCalls, callId)?.status || 'completed'
}

function wikiLinks(tool: { tool_name?: string | null; content?: string | null }) {
  return wikiToolLinks(tool)
}
</script>

<style scoped>
.work-trail {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: var(--space-1) 0 var(--space-2) var(--space-2);
  padding: var(--space-2) 0 var(--space-2) var(--space-4);
  border-left: 2px solid var(--color-border-light);
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
/* LLM 输出的 tool_calls（工具名 + 参数），作为 ai-output 的直接子块 */
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

/* 工具执行卡 */
.tool-card-row {
  margin-bottom: var(--space-4);
  animation: trail-in 0.35s ease forwards;
}

@keyframes trail-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
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

/* wiki 工具链接 */
.wiki-tool-links {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.wiki-tool-link {
  font-size: var(--text-sm);
  color: var(--color-primary);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wiki-tool-link:hover {
  text-decoration: underline;
}

/* 思考过程段 */
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
.reasoning-body {
  padding: var(--space-2) var(--space-3) var(--space-3);
  border-top: 1px solid var(--color-border-light);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  max-height: 400px;
  overflow-y: auto;
}
</style>
