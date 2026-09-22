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

