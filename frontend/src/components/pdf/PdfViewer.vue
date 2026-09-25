<template>
  <div class="pdf-viewer">
    <div v-if="error" class="pdf-viewer__error">
      <el-empty :description="error" />
    </div>
    <div v-else class="pdf-viewer__scroll" ref="scrollRef">
      <!-- 只渲染当前页（弹窗场景按页跳转浏览），canvas + 同尺寸 overlay 叠加高亮 -->
      <div class="pdf-viewer__page" :style="{ width: cssWidth + 'px', height: cssHeight + 'px' }">
        <canvas ref="canvasRef" class="pdf-viewer__canvas" />
        <div
          v-for="(rect, i) in overlayRects"
          :key="i"
          class="pdf-viewer__highlight"
          :class="{ 'pdf-viewer__highlight--pulse': i === 0 }"
          :style="rectStyle(rect)"
        />
      </div>
    </div>
    <div v-if="totalPages > 0" class="pdf-viewer__pager">
      <el-button size="small" :disabled="currentPage <= 1" @click="goToPage(currentPage - 1)">
        <el-icon><ArrowUp /></el-icon>
      </el-button>
      <span class="pdf-viewer__page-indicator">{{ currentPage }} / {{ totalPages }}</span>
      <el-button size="small" :disabled="currentPage >= totalPages" @click="goToPage(currentPage + 1)">
        <el-icon><ArrowDown /></el-icon>
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * PDF 查看器（pdfjs-dist canvas 渲染 + bbox 高亮 overlay）。
 *
 * - 动态 import pdfjs-dist，隔离首屏体积；worker 经 Vite `?url` 引入
 * - DeepDoc 坐标（pdfplumber pt，72dpi，原点左上）与 pdf.js scale=1 viewport
 *   线性对齐：overlay 直接按 (pdfPt / viewport.width * cssWidth) 缩放映射
 * - v1 不做 textLayer（无需文本选择，只做查看+高亮）
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import type { ChunkPositionResponse } from '@/api/types'

const props = defineProps<{
  /** 文件 Blob URL（经认证端点获取） */
  src: string
  /** 初始页码（1-based） */
  page: number
  /** 高亮矩形（PDF pt 坐标） */
  bboxes: ChunkPositionResponse['bboxes']
}>()

// 动态 import：pdfjs-dist 体积大，不进首屏 chunk
let pdfjsLib: typeof import('pdfjs-dist') | null = null
async function loadPdfjs() {
  if (pdfjsLib) return pdfjsLib
  pdfjsLib = await import('pdfjs-dist')
  // worker 用 Vite 静态资源 URL（构建后哈希文件名不丢）
  const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
  pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl
  return pdfjsLib
}

const scrollRef = ref<HTMLDivElement>()
const canvasRef = ref<HTMLCanvasElement>()
const error = ref('')
const totalPages = ref(0)
const currentPage = ref(props.page || 1)
const pdfDoc = ref<any>(null)

// 当前页 viewport（scale=1）尺寸，用于 CSS 布局与坐标映射
const viewportWidth = ref(0)
const viewportHeight = ref(0)
const cssWidth = ref(0)
const cssHeight = ref(0)

const overlayRects = computed(() => props.bboxes.filter((b) => b.page === currentPage.value))

function rectStyle(rect: { x0: number; x1: number; top: number; bottom: number }) {
  const scaleX = cssWidth.value / (viewportWidth.value || 1)
  const scaleY = cssHeight.value / (viewportHeight.value || 1)
  return {
    left: `${rect.x0 * scaleX}px`,
    top: `${rect.top * scaleY}px`,
    width: `${(rect.x1 - rect.x0) * scaleX}px`,
    height: `${(rect.bottom - rect.top) * scaleY}px`,
  }
}

let renderTask: any = null

async function renderPage(pageNum: number) {
  const doc = pdfDoc.value
  const canvas = canvasRef.value
  if (!doc || !canvas) return
  try {
    renderTask?.cancel()
    const page = await doc.getPage(pageNum)
    const viewport = page.getViewport({ scale: 1 })
    viewportWidth.value = viewport.width
    viewportHeight.value = viewport.height

    // devicePixelRatio 适配：canvas 物理像素 = css 尺寸 × dpr，避免模糊
    const containerWidth = scrollRef.value?.clientWidth ?? 800
    const cssScale = Math.min((containerWidth - 24) / viewport.width, 1.5)
    const dpr = window.devicePixelRatio || 1
    const outputScale = cssScale * dpr

    cssWidth.value = viewport.width * cssScale
    cssHeight.value = viewport.height * cssScale
    canvas.width = Math.floor(viewport.width * outputScale)
    canvas.height = Math.floor(viewport.height * outputScale)
    canvas.style.width = `${cssWidth.value}px`
    canvas.style.height = `${cssHeight.value}px`

    renderTask = page.render({
      canvasContext: canvas.getContext('2d'),
      transform: outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : undefined,
    })
    await renderTask.promise
    renderTask = null
    // 渲染完成后把首个高亮滚进视野
    requestAnimationFrame(() => {
      scrollRef.value?.scrollTo({ top: Math.max(0, (overlayRects.value[0]?.top ?? 0) * cssScale - 80), behavior: 'smooth' })
    })
  } catch (e: any) {
    // RenderingCancelledException 是切页竞态，非错误
    if (e?.name !== 'RenderingCancelledException' && !String(e?.message ?? '').includes('cancelled')) {
      error.value = 'PDF 页面渲染失败'
    }
  }
}

function goToPage(page: number) {
  if (page < 1 || page > totalPages.value) return
  currentPage.value = page
}

watch(currentPage, (p) => renderPage(p))

onBeforeUnmount(() => {
  renderTask?.cancel()
  pdfDoc.value?.destroy?.()
})

;(async () => {
  try {
    const lib = await loadPdfjs()
    const task = lib.getDocument({ url: props.src })
    pdfDoc.value = await task.promise
    totalPages.value = pdfDoc.value.numPages
    currentPage.value = Math.min(Math.max(1, props.page || 1), totalPages.value)
    await renderPage(currentPage.value)
  } catch (e: any) {
    error.value = e?.name === 'PasswordException' ? 'PDF 已加密，无法预览' : 'PDF 加载失败'
  }
})()
</script>

<style scoped>
.pdf-viewer {
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.pdf-viewer__scroll {
  flex: 1;
  overflow: auto;
  display: flex;
  justify-content: center;
  padding: 12px;
  background: var(--el-fill-color-darker);
}

.pdf-viewer__page {
  position: relative;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
  background: #fff;
}

.pdf-viewer__canvas {
  display: block;
}

.pdf-viewer__highlight {
  position: absolute;
  background: rgba(250, 204, 21, 0.35);
  border: 1px solid rgba(202, 138, 4, 0.55);
  border-radius: 2px;
  pointer-events: none;
}

.pdf-viewer__highlight--pulse {
  animation: pdf-highlight-pulse 1.6s ease-in-out 2;
}

@keyframes pdf-highlight-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(202, 138, 4, 0.45); }
  50% { box-shadow: 0 0 0 6px rgba(202, 138, 4, 0); }
}

.pdf-viewer__pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.pdf-viewer__page-indicator {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  min-width: 64px;
  text-align: center;
}
</style>
