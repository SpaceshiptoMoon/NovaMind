<template>
  <div class="message-row" :class="message.role">
    <!-- User message: right-aligned blue bubble -->
    <div v-if="message.role === 'user'" class="message-body">
      <div class="message-text user-bubble">{{ message.content }}</div>
    </div>

    <!-- Assistant message: left-aligned with MarkdownRenderer + reasoning -->
    <div v-else-if="message.role === 'assistant'" class="message-body">
      <div v-if="message.reasoning" class="reasoning-section">
        <div class="reasoning-header" @click="showReasoning = !showReasoning">
          <span class="reasoning-label">思考过程</span>
          <el-icon :size="12" class="expand-icon" :class="{ expanded: showReasoning }">
            <ArrowDown />
          </el-icon>
        </div>
        <div v-if="showReasoning" class="reasoning-body">
          <MarkdownRenderer :content="message.reasoning" />
        </div>
      </div>
      <MarkdownRenderer v-if="message.content" :content="message.content" class="message-text" />
    </div>

    <!-- Tool message: delegate to ToolCallCard -->
    <div v-else-if="message.role === 'tool'" class="message-body">
      <ToolCallCard
        :name="message.tool_name || 'Tool'"
        :call-id="message.tool_call_id || ''"
        :status="toolStatus"
        :result="message.content || undefined"
        :args="toolArguments"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { useClawMateStore } from '@/stores/clawmate'
import type { ClawMateChatMessage } from '@/api/types'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import ToolCallCard from './ToolCallCard.vue'

const props = defineProps<{
  message: ClawMateChatMessage
}>()

const store = useClawMateStore()
const showReasoning = ref(false)

const toolRecord = computed(() => {
  if (!props.message.tool_call_id) return null
  return store.toolCalls.find((c) => c.call_id === props.message.tool_call_id) || null
})

const toolStatus = computed(() => toolRecord.value?.status || 'completed')
const toolArguments = computed(() => toolRecord.value?.arguments)
</script>

<style scoped>
.message-row {
  display: flex;
  margin-bottom: var(--space-5);
  animation: messageIn 0.3s ease forwards;
}

.message-row.user {
  justify-content: flex-end;
}

.message-row.assistant {
  justify-content: flex-start;
}

.message-row.tool {
  justify-content: flex-start;
}

.message-body {
  max-width: 75%;
  min-width: 0;
}

.message-text {
  font-size: var(--text-base);
  line-height: 1.6;
  word-break: break-word;
}

/* User bubble */
.user-bubble {
  padding: var(--space-3) var(--space-4);
  border-radius: 18px 18px 4px 18px;
  background: var(--color-primary);
  color: #ffffff;
  white-space: pre-wrap;
}

/* Reasoning collapsible section */
.reasoning-section {
  margin-bottom: var(--space-2);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
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
  transition: background var(--transition-fast);
}

.reasoning-header:hover {
  background: var(--color-bg-hover);
}

.reasoning-label {
  font-weight: var(--weight-medium);
}

.expand-icon {
  transition: transform var(--transition-fast);
  color: var(--color-text-muted);
}

.expand-icon.expanded {
  transform: rotate(180deg);
}

.reasoning-body {
  padding: var(--space-2) var(--space-3) var(--space-3);
  border-top: 1px solid var(--color-border-light);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  max-height: 400px;
  overflow-y: auto;
}

/* Assistant message styling */
.message-row.assistant .message-text {
  padding: var(--space-3) var(--space-4);
  border-radius: 18px 18px 18px 4px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
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
</style>
