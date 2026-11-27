<template>
  <div class="compare-view">
    <!-- 顶栏：文件信息 + 同步开关 + 关闭 -->
    <div class="compare-header">
      <span class="compare-title" :title="filename">{{ filename }}</span>
      <span class="compare-mode-tag">{{ leftModeLabel }}</span>
      <div class="compare-actions">
        <el-checkbox v-model="syncScroll" size="small">同步滚动</el-checkbox>
        <el-button size="small" @click="$emit('close')">关闭</el-button>
      </div>
    </div>

    <!-- 主体：左原文 / 右解析 md -->
    <div ref="bodyRef" class="compare-body">
      <div
        ref="leftPaneRef"
        class="compare-pane pane-left"
        :style="{ flexBasis: leftWidthPercent + '%' }"
        @scroll.passive="onLeftScroll"
      >
        <div v-if="compareError" class="compare-unsupported">
          原文渲染失败：{{ compareError }}
        </div>
        <div v-else-if="leftLoading" class="compare-loading">
          <el-skeleton :rows="10" animated />
        </div>

        <!-- 页图序列（VLM/PPT 转写线） -->
        <template v-else-if="leftMode === 'pages'">
          <div v-for="p in pageImages" :key="p.page" class="page-image-wrap">
            <span class="page-badge">第 {{ p.page }} 页</span>
            <img :src="p.url" class="page-image" loading="lazy" />
          </div>
        </template>

        <!-- PDF（pdfjs 现场渲染） -->
        <template v-else-if="leftMode === 'pdf' && leftSource">
          <VuePdfEmbed :source="leftSource" class="pdf-embed" />
        </template>

        <!-- 单张图片（vlm_doc） -->
        <img
          v-else-if="leftMode === 'image' && leftSource"
          :src="leftSource"
          class="page-image"
        />

        <!-- 不支持类型 -->
        <div v-else-if="!leftLoading" class="compare-unsupported">
          该文件类型暂不支持对比预览，可下载源文件查看。
        </div>
      </div>

      <!-- 可拖拽分隔条 -->
      <div
        class="compare-divider"
        @mousedown.prevent="startDrag"
      ></div>

      <div
        ref="rightPaneRef"
        class="compare-pane pane-right"
        :style="{ flexBasis: 100 - leftWidthPercent + '%' }"
        @scroll.passive="onRightScroll"
      >
        <div v-if="mdLoading" class="compare-loading">
          <el-skeleton :rows="14" animated />
        </div>
        <template v-else-if="mdError">
          <div class="compare-unsupported">{{ mdError }}</div>
        </template>
        <MarkdownRenderer v-else :content="mdContent" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 原文 / 解析 MD 左右对比预览（V1）。
 *
 * 左侧按文件类型三分支：页图序列（VLM/PPT 转写线，storage.pages）/
 * PDF 现场渲染（vue-pdf-embed 吃预览 blob URL）/ 原图（vlm_doc）。
 * 右侧为解析产出 markdown（parsed-text 端点，图链已 presign）。
 * 同步滚动为比例映射（左右滚动百分比互映，可关）。
 * chunk 级高亮联动（chunk-position 端点已返回页+bbox）留作 V2。
 */
import { onBeforeUnmount, onMounted, ref, computed, onErrorCaptured } from 'vue'
import VuePdfEmbed from 'vue-pdf-embed'
// pdfjs worker 显式注册（README Option 1 的 Vite 形态；默认 blob 在部分
// 环境会被 CSP/模块解析打断，显式入口更稳）
import PdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { GlobalWorkerOptions } from 'pdfjs-dist'
import { documentApi } from '@/api/knowledge'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'

GlobalWorkerOptions.workerSrc = PdfWorker

// 子树渲染错误（如 pdf 渲染失败）就地捕获并转为错误提示：
// 防止异常打断父级响应链导致对话框关闭失效
const compareError = ref('')
onErrorCaptured((err) => {
  compareError.value = String((err as Error)?.message || err)
  return false
})

const props = defineProps<{
  spaceId: number
  kbId: number
  docId: number
  filename: string
}>()

defineEmits<{ (e: 'close'): void }>()

const leftPaneRef = ref<HTMLElement | null>(null)
const rightPaneRef = ref<HTMLElement | null>(null)

const leftLoading = ref(true)
const mdLoading = ref(true)
const mdError = ref('')
const mdContent = ref('')
const leftMode = ref<'pages' | 'pdf' | 'image' | 'unsupported'>('unsupported')
const leftSource = ref('')
const pageImages = ref<{ page: number; url: string }[]>([])
const syncScroll = ref(true)
const leftWidthPercent = ref(50)

const leftModeLabel = computed(() => {
  if (leftMode.value === 'pages') return '原文页图'
  if (leftMode.value === 'pdf') return '原文 PDF'
  if (leftMode.value === 'image') return '原图'
  return '对比预览'
})

/** 判断图片类扩展名（vlm_doc 入口） */
function isImageType(fileType: string): boolean {
  return ['jpg', 'jpeg', 'png', 'webp', 'bmp', 'gif'].includes(fileType)
}

/** 左侧源解析（纯逻辑，独立可测）：文件类型 + pages 清单 → 模式 */
async function loadLeftSource(): Promise<void> {
  leftLoading.value = true
  try {
    const fileType = (props.filename || '').split('.').pop()?.toLowerCase() || ''

    if (isImageType(fileType)) {
      leftMode.value = 'image'
      leftSource.value = await documentApi.getDocumentImage(props.spaceId, props.kbId, props.docId)
      return
    }

    // 先查页图清单（VLM/PPT 转写线）；空 → pdf 走 pdfjs；其它类型不支持
    if (fileType === 'pdf' || fileType === 'ppt' || fileType === 'pptx') {
      const pagesResult = await documentApi.getDocumentPages(
        props.spaceId, props.kbId, props.docId,
      )
      if (pagesResult.pages.length > 0) {
        leftMode.value = 'pages'
        pageImages.value = pagesResult.pages
        return
      }
      if (fileType === 'pdf') {
        leftMode.value = 'pdf'
        leftSource.value = await documentApi.getDocumentPreviewBlobUrl(
          props.spaceId, props.kbId, props.docId,
        )
        return
      }
      leftMode.value = 'unsupported'
      return
    }

    leftMode.value = 'unsupported'
  } catch {
    leftMode.value = 'unsupported'
  } finally {
    leftLoading.value = false
  }
}

/** 解析 md 加载（parsed-text 端点，图链已 presign） */
async function loadMarkdown(): Promise<void> {
  mdLoading.value = true
  mdError.value = ''
  try {
    mdContent.value = await documentApi.getDocumentParsedText(
      props.spaceId, props.kbId, props.docId,
    )
  } catch (e) {
    mdError.value = '解析结果加载失败：该文档可能尚未完成解析'
  } finally {
    mdLoading.value = false
  }
}

// ── 同步滚动：比例映射（rAF 节流 + 互斥防回环） ──
let syncing = false

function onLeftScroll(): void {
  if (!syncScroll.value || syncing) return
  const left = leftPaneRef.value
  const right = rightPaneRef.value
  if (!left || !right) return
  const leftMax = left.scrollHeight - left.clientHeight
  if (leftMax <= 0) return
  syncing = true
  requestAnimationFrame(() => {
    const ratio = left.scrollTop / leftMax
    const rightMax = right.scrollHeight - right.clientHeight
    if (rightMax > 0) right.scrollTop = ratio * rightMax
    syncing = false
  })
}

function onRightScroll(): void {
  if (!syncScroll.value || syncing) return
  const left = leftPaneRef.value
  const right = rightPaneRef.value
  if (!left || !right) return
  const rightMax = right.scrollHeight - right.clientHeight
  if (rightMax <= 0) return
  syncing = true
  requestAnimationFrame(() => {
    const ratio = right.scrollTop / rightMax
    const leftMax = left.scrollHeight - left.clientHeight
    if (leftMax > 0) left.scrollTop = ratio * leftMax
    syncing = false
  })
}

// ── 可拖拽分隔条 ──
const bodyRef = ref<HTMLElement | null>(null)

function startDrag(): void {
  const body = bodyRef.value
  if (!body) return
  const onMove = (e: MouseEvent) => {
    const rect = body.getBoundingClientRect()
    const percent = ((e.clientX - rect.left) / rect.width) * 100
    leftWidthPercent.value = Math.min(80, Math.max(20, percent))
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
  }
  document.body.style.cursor = 'col-resize'
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

onMounted(async () => {
  await Promise.all([loadLeftSource(), loadMarkdown()])
})

onBeforeUnmount(() => {
  // blob URL 由 api 层管理（DocumentOriginalPreview 同款约定），此处无需额外清理
})
</script>

<style scoped>
.compare-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--color-bg-page, #f5f7fa);
}

.compare-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  flex-shrink: 0;
}

.compare-title {
  font-weight: 600;
  font-size: 14px;
  max-width: 40%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.compare-mode-tag {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border-radius: 4px;
  padding: 2px 8px;
}

.compare-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
}

.compare-body {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.compare-pane {
  overflow: auto;
  min-width: 0;
  padding: 16px;
}

.pane-left {
  background: var(--el-bg-color-page, #fafafa);
}

.pane-right {
  background: var(--el-bg-color);
  border-left: none;
}

.compare-divider {
  width: 5px;
  cursor: col-resize;
  background: var(--el-border-color-lighter);
  flex-shrink: 0;
  transition: background 0.15s;
}

.compare-divider:hover {
  background: var(--el-color-primary-light-5);
}

.page-image-wrap {
  position: relative;
  margin-bottom: 12px;
}

.page-image {
  display: block;
  width: 100%;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
}

.page-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
  border-radius: 4px;
  padding: 1px 8px;
}

.pdf-embed {
  width: 100%;
}

.compare-loading {
  padding: 8px;
}

.compare-unsupported {
  padding: 40px 16px;
  text-align: center;
  color: var(--el-text-color-secondary);
}
</style>
