<template>
  <div class="markdown-body" v-html="rendered" />
</template>

<script setup lang="ts">
/**
 * Markdown 渲染器：经 renderMarkdown 出 HTML 后 v-html 输出；
 * 流式场景下用 requestAnimationFrame 合帧，避免每个 chunk 都同步重渲
 */

import { ref, watch, onUnmounted } from 'vue'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  content: string
}>()

const rendered = ref(props.content ? renderMarkdown(props.content) : '')

let rafId: number | null = null
let latestContent = props.content

/** 流式合帧渲染：sync watch 记下最新内容，rAF 每帧最多重渲一次 */
watch(
  () => props.content,
  (newVal) => {
    latestContent = newVal
    if (rafId !== null) return
    rafId = requestAnimationFrame(() => {
      rendered.value = renderMarkdown(latestContent)
      rafId = null
    })
  },
  { flush: 'sync' },
)

onUnmounted(() => {
  if (rafId !== null) cancelAnimationFrame(rafId)
})
</script>

<!-- .markdown-body 全局排版样式已抽离至 src/assets/markdown.css（main.ts 全局引入），
     本组件只负责渲染，不再携带样式。 -->

