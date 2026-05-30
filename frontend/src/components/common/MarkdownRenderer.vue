<template>
  <div class="markdown-body" v-html="rendered" />
</template>

<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  content: string
}>()

const rendered = ref(props.content ? renderMarkdown(props.content) : '')

let rafId: number | null = null
let latestContent = props.content

watch(() => props.content, (newVal) => {
  latestContent = newVal
  if (rafId !== null) return
  rafId = requestAnimationFrame(() => {
    rendered.value = renderMarkdown(latestContent)
    rafId = null
  })
}, { flush: 'sync' })

onUnmounted(() => {
  if (rafId !== null) cancelAnimationFrame(rafId)
})
</script>

<style>
.markdown-body {
  font-family: var(--font-body);
  font-size: var(--text-base);
  line-height: var(--leading-relaxed);
  color: var(--color-text);
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4 {
  margin: var(--space-3) 0 var(--space-2);
  font-family: var(--font-display);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.markdown-body h1 { font-size: var(--text-xl); }
.markdown-body h2 { font-size: var(--text-xl); }
.markdown-body h3 { font-size: var(--text-lg); }

.markdown-body p { margin: var(--space-1) 0; }

.markdown-body ul,
.markdown-body ol {
  padding-left: var(--space-5);
  margin: var(--space-1) 0;
}

.markdown-body li { margin: var(--space-1) 0; }

.markdown-body blockquote {
  margin: var(--space-2) 0;
  padding: var(--space-1) var(--space-3);
  border-left: 3px solid var(--color-border);
  background: var(--color-bg-card-elevated);
  color: var(--color-text-secondary);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

/* Inline code */
.markdown-body code {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}

.markdown-body :not(pre) > code {
  padding: 2px var(--space-1);
  border-radius: var(--radius-sm);
  background: var(--color-bg-hover);
  color: var(--color-accent);
}

/* Code block wrapper */
.markdown-body .code-block {
  margin: var(--space-2) 0;
  border-radius: var(--radius-lg);
  background: var(--color-bg-card-elevated);
  overflow: hidden;
  border: 1px solid var(--color-border-light);
}

.markdown-body .code-block .hljs {
  background: transparent;
}

.markdown-body .code-block .code-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-1) var(--space-3);
  background: var(--color-bg-hover);
  border-bottom: 1px solid var(--color-border-light);
}

.markdown-body .code-block .code-lang {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.markdown-body .code-block .code-copy-btn {
  font-family: var(--font-body);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 2px var(--space-2);
  cursor: pointer;
  transition: all var(--transition-fast);
  line-height: var(--leading-normal);
}

.markdown-body .code-block .code-copy-btn:hover {
  color: var(--color-text);
  border-color: var(--color-text-muted);
  background: var(--color-bg-card-elevated);
}

.markdown-body .code-block .code-copy-btn.copied {
  color: var(--color-success);
  border-color: var(--color-success);
}

.markdown-body .code-block pre {
  margin: 0;
  padding: var(--space-3);
  background: transparent;
  overflow-x: auto;
}

.markdown-body .code-block pre code {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  background: transparent;
}

/* Legacy standalone pre (fallback for non-wrapped code) */
.markdown-body > pre {
  margin: var(--space-2) 0;
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border-light);
  overflow-x: auto;
}

.markdown-body > pre code {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  background: transparent;
}

.markdown-body table {
  border-collapse: collapse;
  margin: var(--space-2) 0;
  width: 100%;
}

.markdown-body th,
.markdown-body td {
  border: 1px solid var(--color-border-light);
  padding: var(--space-1) var(--space-3);
  text-align: left;
}

.markdown-body th {
  background: var(--color-bg-card-elevated);
  font-weight: var(--weight-semibold);
}

.markdown-body a {
  color: var(--color-primary);
  text-decoration: none;
}

.markdown-body a:hover {
  color: var(--color-primary-hover);
  text-decoration: underline;
}

.markdown-body hr {
  border: none;
  border-top: 1px solid var(--color-border-light);
  margin: var(--space-3) 0;
}
</style>
