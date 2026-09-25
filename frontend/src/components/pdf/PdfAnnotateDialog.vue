<template>
  <el-dialog
    v-model="visible"
    :title="dialogTitle"
    width="90vw"
    top="4vh"
    destroy-on-close
    class="pdf-annotate-dialog"
    @closed="handleClosed"
  >
    <div v-if="loading" class="pdf-annotate-dialog__loading">
      <el-skeleton :rows="8" animated />
    </div>
    <div v-else-if="loadError" class="pdf-annotate-dialog__loading">
      <el-empty :description="loadError" />
    </div>
    <PdfViewer
      v-else-if="blobUrl"
      :src="blobUrl"
      :page="targetPage"
      :bboxes="bboxes"
    />
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * PDF 原文定位弹窗：取 blob URL + chunk-position → 内嵌 PdfViewer bbox 高亮。
 *
 * 打开流程（open 由父组件调用）：先显示弹窗 → 并行取预览 blob（带认证）
 * 与 chunk 坐标 → 就绪后渲染。坐标加载失败降级为无高亮浏览。
 */
import { computed, ref } from 'vue'
import { documentApi } from '@/api/knowledge/document'
import type { ChunkPositionResponse } from '@/api/types'
import PdfViewer from './PdfViewer.vue'

const visible = ref(false)
const loading = ref(false)
const loadError = ref('')
const blobUrl = ref('')
const targetPage = ref(1)
const bboxes = ref<ChunkPositionResponse['bboxes']>([])

const documentName = ref('')
const documentId = ref<number | null>(null)
const dialogTitle = computed(() =>
  documentName.value ? `原文定位 — ${documentName.value}` : '原文定位',
)

let spaceId = 0
let kbId = 0

async function open(payload: {
  spaceId: number
  kbId: number
  documentId: number
  documentName?: string | null
  chunkId?: string | null
  page?: number | null
}) {
  spaceId = payload.spaceId
  kbId = payload.kbId
  documentId.value = payload.documentId
  documentName.value = payload.documentName || ''
  targetPage.value = payload.page || 1
  bboxes.value = []
  blobUrl.value = ''
  loadError.value = ''
  loading.value = true
  visible.value = true

  // 并行：原始文件 blob（渲染必需）+ 坐标（可选，失败降级无高亮）
  const blobPromise = documentApi.getDocumentPreviewBlobUrl(spaceId, kbId, payload.documentId)
  const positionPromise: Promise<ChunkPositionResponse | null> = payload.chunkId
    ? documentApi
        .getChunkPosition(spaceId, kbId, payload.documentId, payload.chunkId)
        .then((position: ChunkPositionResponse) => position)
        .catch((err) => {
          console.warn('[PdfAnnotateDialog] chunk 坐标获取失败，降级为无高亮浏览', err)
          return null
        })
    : Promise.resolve(null)

  try {
    const [url, position] = await Promise.all([blobPromise, positionPromise])
    blobUrl.value = url
    if (position) {
      // 有坐标时以首矩形页码为准（可能与 QA sources 的代表页不同——跨页 chunk）
      const rects = position.bboxes ?? []
      const firstRect = rects[0]
      if (firstRect && position.page) {
        targetPage.value = firstRect.page
      } else if (position.page) {
        targetPage.value = position.page
      }
      bboxes.value = rects
    }
  } catch (err: any) {
    // blob 是硬依赖：拿不到就无法渲染
    loadError.value = err?.response?.status === 404 ? '文档文件不存在或已被删除' : '文档加载失败'
  } finally {
    loading.value = false
  }
}

function handleClosed() {
  // 释放 blob URL，避免内存泄漏
  if (blobUrl.value) {
    window.URL.revokeObjectURL(blobUrl.value)
    blobUrl.value = ''
  }
}

defineExpose({ open })
</script>

<style scoped>
.pdf-annotate-dialog__loading {
  padding: 24px;
  min-height: 300px;
}

:global(.pdf-annotate-dialog .el-dialog__body) {
  /* 90vh 弹窗：头部/边距占用后给正文留最大渲染高度 */
  height: calc(90vh - 110px);
  padding-top: 8px;
}
</style>
