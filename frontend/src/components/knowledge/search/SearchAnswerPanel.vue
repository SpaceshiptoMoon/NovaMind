<template>
  <div class="llm-answer">
    <div class="llm-answer-header">
      <span>AI 回答</span>
      <span class="llm-answer-meta">
        <span v-if="model" class="llm-answer-model">{{ model }}</span>
        <span v-if="elapsedMs" class="llm-answer-model">{{ elapsedMs }}ms</span>
      </span>
    </div>
    <div class="llm-answer-content">
      <MarkdownRenderer :content="answer" />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 检索 AI 回答面板：LLM 生成的 Markdown 回答 + 模型/耗时元信息。
 *
 * 空间内检索页与全局检索页共用；生成失败时父级不渲染本面板、改提示
 * answerError（降级文案由调用方决定展示形态）。
 */
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'

defineProps<{
  /** LLM 生成的回答正文（Markdown） */
  answer: string
  /** 生成使用的模型名 */
  model?: string | null
  /** 生成耗时（毫秒） */
  elapsedMs?: number | null
}>()
</script>

<style scoped>
.llm-answer {
  margin-bottom: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: var(--color-primary-subtle);
  border-radius: var(--radius-lg);
  border-left: 3px solid var(--color-primary);
}

.llm-answer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-3);
  font-weight: var(--weight-semibold);
  font-size: var(--text-sm);
  color: var(--color-primary);
}

.llm-answer-meta {
  display: flex;
  gap: var(--space-3);
}

.llm-answer-model {
  font-weight: var(--weight-normal);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.llm-answer-content {
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--color-text);
}
</style>
