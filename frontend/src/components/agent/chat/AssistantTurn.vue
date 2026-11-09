<template>
  <div v-if="hasContent" class="assistant-turn">
    <div class="turn-avatar" :title="agentName">{{ agentName.charAt(0) }}</div>
    <div class="turn-body">
      <!-- 有工作过程（ReAct 步骤或思考过程）即显示折叠头；始终默认折叠（含进行中，
         进行中与已完成的区分靠 spinner/主题色与「思考中/思考完成」一词之差，句式统一），
         展开才见运行轨迹。展开态组件内自持 -->
      <button
        v-if="hasTrail"
        class="fold-line"
        :class="{ running: turn.isActive }"
        @click="expanded = !expanded"
      >
        <span v-if="turn.isActive" class="fold-spinner" aria-hidden="true"></span>
        <span class="fold-status">{{ foldStatusLabel }}</span>
        <el-icon :size="12" class="fold-chevron" :class="{ expanded }">
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
        @toggle="toggleInSet(expandedCompactions, c.id)"
      />

      <!-- 计划卡（Plan-and-Execute）：常驻胶囊行，展开看步骤清单/进度/总结 -->
      <PlanCard
        v-for="p in turn.planItems"
        :key="`plan-${p.id}`"
        :plan="getPlanData(p)"
        :expanded="expandedPlans.has(p.id)"
        @toggle="toggleInSet(expandedPlans, p.id)"
      />

      <!-- 深度研究进度卡（批3 research 工具）：spinner 胶囊行，展开看进度条与计划 -->
      <ResearchProgressCard
        v-for="r in turn.researchItems"
        :key="`research-${r.id}`"
        :data="getResearchData(r)"
        :expanded="expandedResearch.has(r.id)"
        @toggle="toggleInSet(expandedResearch, r.id)"
      />

      <!-- 纠偏警告行（loop_detection）：常显轻量提示，不折叠（用户应看到的异常信号） -->
      <div v-for="n in turn.noticeItems" :key="`notice-${n.id}`" class="notice-row">
        <el-icon :size="12" class="notice-icon"><Warning /></el-icon>
        <span class="notice-text">{{ n.content }}</span>
      </div>

      <!-- 工作过程轨迹（默认折叠，展开才渲染内容） -->
      <WorkTrail
        v-if="hasTrail && expanded"
        :turn="turn"
        :tool-calls="toolCalls"
        @open-tool="(id) => emit('open-tool', id)"
        @open-wiki="(url) => emit('open-wiki', url)"
      />

      <!-- 最终回复（始终显示） -->
      <div v-if="turn.finalAssistant?.content" class="final-answer">
        <MarkdownRenderer :content="turn.finalAssistant.content" class="answer-text" />
        <div class="message-actions">
          <button
            class="msg-copy-btn"
            @click="emit('copy', turn.finalAssistant.content!, $event)"
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
        <div class="typing-bubble">
          <span class="typing-dot"></span>
          <span class="typing-dot"></span>
          <span class="typing-dot"></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * assistant 一轮：左 avatar + 右内容列（折叠条 → 标记卡 → 工作轨迹 → 最终回复）。
 *
 * 折叠条与各标记卡的展开态全部组件内自持（一轮一实例）；工作轨迹委托 WorkTrail，
 * 复制与工具详情/wiki 跳转上抛父层。进行中耗时由父层的 activeTick 每秒驱动刷新。
 */
import { computed, ref } from 'vue'
import { ArrowDown, DocumentCopy, Warning } from '@element-plus/icons-vue'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import CompactionItem from '@/components/agent/CompactionItem.vue'
import PlanCard from '@/components/agent/PlanCard.vue'
import ResearchProgressCard from '@/components/agent/ResearchProgressCard.vue'
import WorkTrail from './WorkTrail.vue'
import type { ToolCallRecord } from '@/api/types'
import type { ChatTurn } from '@/utils/chatRender'
import {
  formatDuration,
  getCompactionData,
  getPlanData,
  getResearchData,
} from '@/utils/chatRender'

const props = defineProps<{
  turn: ChatTurn
  agentName: string
  toolCalls: ToolCallRecord[]
  /** 进行中秒数 tick：父层每秒自增，驱动折叠条「思考中 · Ns」刷新 */
  activeTick?: number
}>()

const emit = defineEmits<{
  (e: 'open-tool', callId: string | null): void
  (e: 'open-wiki', url: string): void
  (e: 'copy', content: string, event: MouseEvent): void
}>()

// 折叠条展开态（默认折叠，含进行中——轨迹不抢视觉焦点）
const expanded = ref(false)
// 标记卡就地展开态（compaction/plan/research 各自独立）
const expandedCompactions = ref(new Set<number>())
const expandedPlans = ref(new Set<number>())
const expandedResearch = ref(new Set<number>())

function toggleInSet(set: Set<number>, id: number) {
  if (set.has(id)) set.delete(id)
  else set.add(id)
}

const hasTrail = computed(() => props.turn.steps.length > 0 || !!props.turn.finalAssistant?.reasoning)
const hasContent = computed(
  () => props.turn.items.length > 0 || !!props.turn.finalAssistant || props.turn.isActive,
)

// 折叠条状态标签：固定两段式「思考中/思考完成 · 耗时」，保证任意轮次长度一致
const foldStatusLabel = computed(() => {
  const duration = props.turn.isActive ? activeDuration.value : turnDuration.value
  return duration
    ? `${props.turn.isActive ? '思考中' : '思考完成'} · ${duration}`
    : props.turn.isActive
      ? '思考中'
      : '思考完成'
})

// 该轮总耗时（无有效时间区间返回空串，折叠条省略耗时段）
const turnDuration = computed(() => {
  const { endTime, startTime } = props.turn
  if (endTime && startTime) {
    const ms = endTime - startTime
    if (ms > 0) return formatDuration(ms)
  }
  return ''
})

// 进行中耗时：起点=本轮用户消息时间，终点=now；activeTick 变化驱动重算
const activeDuration = computed(() => {
  void props.activeTick
  if (!props.turn.startTime) return ''
  return formatDuration(Date.now() - props.turn.startTime)
})
</script>

<style scoped>
.assistant-turn {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-top: var(--space-2);
  animation: turn-in 0.35s ease forwards;
}

@keyframes turn-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
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

/* 最终回复 */
.final-answer {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.final-answer .answer-text {
  font-size: var(--text-base);
  line-height: var(--leading-relaxed);
  word-break: break-word;
}

.final-answer .message-actions {
  align-self: flex-start;
}

/* 复制按钮（hover 浮现） */
.message-actions {
  display: flex;
  gap: var(--space-2);
  padding: 2px 2px 0;
  opacity: 0;
  transition: opacity var(--transition-fast);
}

.assistant-turn:hover .message-actions {
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

/* 流式点点占位 */
.typing-row {
  display: flex;
  margin-bottom: 28px;
  animation: turn-in 0.35s ease forwards;
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
  animation: dot-pulse 1.4s ease-in-out infinite;
}

.typing-dot:nth-child(2) {
  animation-delay: 0.2s;
}
.typing-dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes dot-pulse {
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
</style>
