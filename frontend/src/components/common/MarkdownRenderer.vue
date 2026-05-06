<template>
  <div class="markdown-body" v-html="rendered" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  content: string
}>()

const rendered = computed(() => renderMarkdown(props.content))
</script>

<style>
.markdown-body {
  font-family: var(--font-body);
  font-size: 14px;
  line-height: 1.7;
  color: var(--color-text);
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4 {
  margin: 12px 0 8px;
  font-family: var(--font-display);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.markdown-body h1 { font-size: 20px; }
.markdown-body h2 { font-size: 18px; }
.markdown-body h3 { font-size: 16px; }

.markdown-body p { margin: 6px 0; }

.markdown-body ul,
.markdown-body ol {
  padding-left: 20px;
  margin: 6px 0;
}

.markdown-body li { margin: 2px 0; }

.markdown-body blockquote {
  margin: 8px 0;
  padding: 4px 12px;
  border-left: 3px solid var(--color-border);
  background: var(--color-bg-card-elevated);
  color: var(--color-text-secondary);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

/* Inline code */
.markdown-body code {
  font-family: var(--font-mono);
  font-size: 13px;
}

.markdown-body :not(pre) > code {
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-hover);
  color: var(--color-accent);
}

/* Code block wrapper — warm light theme */
.markdown-body .code-block {
  margin: 10px 0;
  border-radius: var(--radius-lg);
  background: #F7F5F2;
  overflow: hidden;
  border: 1px solid var(--color-border-light);
}

/* Override hljs github theme bg to match our warm tone */
.markdown-body .code-block .hljs {
  background: transparent;
}

.markdown-body .code-block .code-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 14px;
  background: var(--color-bg-hover);
  border-bottom: 1px solid var(--color-border-light);
}

.markdown-body .code-block .code-lang {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.markdown-body .code-block .code-copy-btn {
  font-family: var(--font-body);
  font-size: 11px;
  color: var(--color-text-muted);
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 2px 10px;
  cursor: pointer;
  transition: all 150ms ease;
  line-height: 1.6;
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
  padding: 14px;
  background: transparent;
  overflow-x: auto;
}

.markdown-body .code-block pre code {
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.6;
  background: transparent;
}

/* Legacy standalone pre (fallback for non-wrapped code) */
.markdown-body > pre {
  margin: 8px 0;
  padding: 12px;
  border-radius: var(--radius-md);
  background: #F7F5F2;
  border: 1px solid var(--color-border-light);
  overflow-x: auto;
}

.markdown-body > pre code {
  font-family: var(--font-mono);
  font-size: 13px;
  background: transparent;
}

.markdown-body table {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
}

.markdown-body th,
.markdown-body td {
  border: 1px solid var(--color-border-light);
  padding: 6px 12px;
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
  margin: 12px 0;
}
</style>
