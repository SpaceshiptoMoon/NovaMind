<template>
  <div class="original-preview">
    <!-- 文件信息 + 操作 -->
    <div class="preview-section file-info-section">
      <div class="source-info">
        <div :class="['source-icon', `source-icon-${category}`]">
          <el-icon :size="28"><component :is="sourceIcon" /></el-icon>
        </div>
        <div class="source-detail">
          <p class="source-filename">{{ document?.filename }}</p>
          <p class="source-meta">{{ formatFileSize(document?.file_size || 0) }} · {{ (document?.file_type || 'FILE').toUpperCase() }}</p>
        </div>
      </div>
      <div class="file-actions">
        <el-button
          type="primary"
          size="small"
          :disabled="!canViewOriginal"
          @click="handleViewOriginal"
        >
          <el-icon><View /></el-icon>
          查看原文
        </el-button>
        <el-button
          size="small"
          :loading="downloadingSource"
          @click="handleDownloadSource"
        >
          <el-icon><Download /></el-icon>
          下载源文件
        </el-button>
      </div>
    </div>

    <!-- 图片内联预览 -->
    <div v-if="category === 'image' && previewUrl" class="preview-section image-inline">
      <div class="preview-section-header">
        <h4>原文预览</h4>
      </div>
      <img
        :src="previewUrl"
        :alt="document?.filename"
        class="preview-image"
        loading="lazy"
        @click="imagePreviewVisible = true"
      />
    </div>

    <!-- 音频内联播放 -->
    <div v-if="category === 'audio' && previewUrl" class="preview-section audio-inline">
      <div class="preview-section-header">
        <h4>原文播放</h4>
      </div>
      <audio :src="previewUrl" controls class="audio-player" preload="metadata">
        您的浏览器不支持音频播放
      </audio>
    </div>

    <!-- 查看原文弹窗 -->
    <el-dialog
      v-model="originalDialogVisible"
      :title="`原文 · ${document?.filename || ''}`"
      width="700px"
      top="5vh"
      destroy-on-close
      class="original-dialog"
      append-to-body
      @opened="handleDialogOpened"
      @close="handleDialogClose"
    >
      <!-- 搜索栏 -->
      <div v-if="parsedText" class="search-bar">
        <el-input
          v-model="searchQuery"
          placeholder="搜索原文内容..."
          size="small"
          clearable
          @input="handleSearchInput"
          @keydown.enter="handleSearchKeydown"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <div v-if="searchQuery" class="search-nav">
          <span class="search-count">{{ totalMatches > 0 ? currentMatchIndex : 0 }}/{{ totalMatches }}</span>
          <el-button size="small" circle :disabled="totalMatches === 0" @click="prevMatch">
            <el-icon><ArrowUp /></el-icon>
          </el-button>
          <el-button size="small" circle :disabled="totalMatches === 0" @click="nextMatch">
            <el-icon><ArrowDown /></el-icon>
          </el-button>
        </div>
      </div>

      <!-- 内容区 -->
      <div v-loading="textLoading" class="original-dialog-content" ref="contentRef">
        <template v-if="!textLoading">
          <MarkdownRenderer v-if="parsedText" :content="parsedText" />
          <el-empty v-else :description="textError || '暂无原文内容'" :image-size="80" />
        </template>
      </div>
    </el-dialog>

    <!-- 图片放大弹窗 -->
    <el-dialog
      v-model="imagePreviewVisible"
      :show-close="true"
      width="auto"
      class="image-preview-dialog"
      destroy-on-close
    >
      <img v-if="previewUrl" :src="previewUrl" style="max-width: 90vw; max-height: 80vh; object-fit: contain; display: block; margin: auto" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { Download, Document, Headset, VideoCamera, View, Search, ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import { documentApi } from '@/api/knowledge'
import { getFileTypeCategory } from './document'
import { formatFileSize } from '@/utils/format'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import type { Document as DocType } from '@/api/types'

const props = defineProps<{
  spaceId: number
  kbId: number
  document: DocType | null
}>()

const category = computed(() => {
  if (!props.document) return 'text'
  return getFileTypeCategory(props.document.file_type)
})

const sourceIcon = computed(() => {
  switch (category.value) {
    case 'image': return Document
    case 'video': return VideoCamera
    case 'audio': return Headset
    default: return Document
  }
})

// 是否可以查看原文（文档已完成解析）
const canViewOriginal = computed(() => props.document?.status === 2)

// 下载状态
const downloadingSource = ref(false)

// 原文数据（按需加载）
const parsedText = ref('')
const textLoading = ref(false)
const textError = ref('')

// 查看原文弹窗
const originalDialogVisible = ref(false)

// 搜索状态
const searchQuery = ref('')
const currentMatchIndex = ref(0)
const totalMatches = ref(0)
const contentRef = ref<HTMLElement | null>(null)
let searchTimer: ReturnType<typeof setTimeout> | null = null

// 带认证的预览 Blob URL（图片/音频通过 fetch + token 获取后创建）
const previewUrl = ref('')

async function loadPreviewUrl() {
  if (!props.document) return
  if (category.value !== 'image' && category.value !== 'audio') return
  if (previewUrl.value) {
    window.URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
  try {
    previewUrl.value = await documentApi.getDocumentPreviewBlobUrl(
      props.spaceId, props.kbId, props.document.id
    )
  } catch {
    previewUrl.value = ''
  }
}

onMounted(loadPreviewUrl)

watch(() => props.document?.id, () => {
  loadPreviewUrl()
  // 文档切换时重置原文数据
  parsedText.value = ''
  textError.value = ''
  originalDialogVisible.value = false
})

onUnmounted(() => {
  if (previewUrl.value) {
    window.URL.revokeObjectURL(previewUrl.value)
  }
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
})

// 图片放大弹窗
const imagePreviewVisible = ref(false)

// 点击查看原文
async function handleViewOriginal() {
  originalDialogVisible.value = true
  if (parsedText.value) return

  textLoading.value = true
  textError.value = ''
  try {
    parsedText.value = await documentApi.getDocumentParsedText(
      props.spaceId, props.kbId, props.document!.id
    )
  } catch (err: unknown) {
    const status = (err as { response?: { status?: number } })?.response?.status
    if (status === 404) {
      textError.value = '文档尚未解析完成'
    } else {
      textError.value = '原文加载失败'
    }
    parsedText.value = ''
  } finally {
    textLoading.value = false
  }
}

// 下载源文件
async function handleDownloadSource() {
  if (!props.document) return
  downloadingSource.value = true
  try {
    await documentApi.downloadDocument(
      props.spaceId, props.kbId, props.document.id, props.document.filename
    )
  } catch {
    // 下载失败已在 interceptor 处理
  } finally {
    downloadingSource.value = false
  }
}

// ===== 搜索功能 =====

function handleDialogOpened() {
  // 弹窗打开后，若已有搜索词，重新应用高亮
  if (searchQuery.value) {
    nextTick(() => applySearch())
  }
}

function handleDialogClose() {
  // 清理搜索状态（DOM 会被 destroy-on-close 销毁）
  totalMatches.value = 0
  currentMatchIndex.value = 0
}

function handleSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    nextTick(() => applySearch())
  }, 250)
}

function handleSearchKeydown(e: KeyboardEvent) {
  e.preventDefault()
  if (e.shiftKey) {
    prevMatch()
  } else {
    nextMatch()
  }
}

/** 在渲染内容中搜索并高亮匹配文本 */
function applySearch() {
  if (!contentRef.value) return
  clearHighlights()

  const query = searchQuery.value.trim()
  if (!query) {
    totalMatches.value = 0
    currentMatchIndex.value = 0
    return
  }

  const lowerQuery = query.toLowerCase()
  const matches: HTMLElement[] = []

  // 收集可搜索的文本节点
  const walker = document.createTreeWalker(contentRef.value, NodeFilter.SHOW_TEXT)
  const textNodes: Text[] = []
  while (walker.nextNode()) {
    const node = walker.currentNode as Text
    const parent = node.parentElement
    if (!parent) continue
    if (parent.tagName === 'SCRIPT' || parent.tagName === 'STYLE') continue
    if (parent.classList.contains('search-highlight') || parent.classList.contains('search-highlight-current')) continue
    if (!node.textContent) continue
    textNodes.push(node)
  }

  // 从后往前替换，避免偏移
  for (let i = textNodes.length - 1; i >= 0; i--) {
    const textNode = textNodes[i]
    const text = textNode.textContent || ''
    const lowerText = text.toLowerCase()

    if (!lowerText.includes(lowerQuery)) continue

    const fragment = document.createDocumentFragment()
    let lastIndex = 0
    let pos = lowerText.indexOf(lowerQuery)

    while (pos !== -1) {
      if (pos > lastIndex) {
        fragment.appendChild(document.createTextNode(text.slice(lastIndex, pos)))
      }
      const mark = document.createElement('mark')
      mark.className = 'search-highlight'
      mark.textContent = text.slice(pos, pos + query.length)
      fragment.appendChild(mark)
      matches.push(mark)
      lastIndex = pos + query.length
      pos = lowerText.indexOf(lowerQuery, lastIndex)
    }

    if (lastIndex < text.length) {
      fragment.appendChild(document.createTextNode(text.slice(lastIndex)))
    }

    textNode.parentNode?.replaceChild(fragment, textNode)
  }

  // matches 是从后往前收集的，需要反转以匹配文档顺序
  matches.reverse()
  totalMatches.value = matches.length
  currentMatchIndex.value = matches.length > 0 ? 1 : 0

  if (matches.length > 0) {
    matches[0].classList.add('search-highlight-current')
    matches[0].scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

function clearHighlights() {
  if (!contentRef.value) return
  const marks = contentRef.value.querySelectorAll('mark.search-highlight, mark.search-highlight-current')
  marks.forEach(mark => {
    const parent = mark.parentNode
    if (parent) {
      parent.replaceChild(document.createTextNode(mark.textContent || ''), mark)
      parent.normalize()
    }
  })
}

function nextMatch() {
  if (totalMatches.value === 0) return
  const idx = currentMatchIndex.value % totalMatches.value
  const nextIdx = (idx + 1) % totalMatches.value
  navigateToMatch(nextIdx)
}

function prevMatch() {
  if (totalMatches.value === 0) return
  const idx = currentMatchIndex.value - 1
  const prevIdx = idx <= 0 ? totalMatches.value - 1 : idx - 1
  navigateToMatch(prevIdx)
}

function navigateToMatch(index: number) {
  if (!contentRef.value) return
  const marks = contentRef.value.querySelectorAll('mark.search-highlight, mark.search-highlight-current')
  if (index < 0 || index >= marks.length) return

  marks.forEach(m => m.classList.remove('search-highlight-current'))
  marks[index].classList.add('search-highlight-current')
  marks[index].scrollIntoView({ behavior: 'smooth', block: 'center' })
  currentMatchIndex.value = index + 1
}
</script>

<style scoped>
.original-preview {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.preview-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
}

.preview-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.preview-section-header h4 {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

/* 文件信息 + 操作区 */
.file-info-section {
  gap: var(--space-4);
}

.source-info {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.source-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  flex-shrink: 0;
}

.source-icon-image { color: #409eff; background: rgba(64, 158, 255, 0.1); }
.source-icon-video { color: #e6a23c; background: rgba(230, 162, 60, 0.1); }
.source-icon-audio { color: #67c23a; background: rgba(103, 194, 58, 0.1); }

.source-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

.source-filename {
  margin: 0;
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-meta {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.file-actions {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* 图片内联预览 */
.image-inline {
  padding: var(--space-3);
}

.preview-image {
  max-width: 100%;
  max-height: 400px;
  border-radius: var(--radius-md);
  object-fit: contain;
  cursor: pointer;
  transition: opacity var(--transition-fast);
}

.preview-image:hover {
  opacity: 0.9;
}

/* 音频内联播放 */
.audio-inline {
  padding: var(--space-3);
  align-items: center;
}

.audio-player {
  width: 100%;
  max-width: 320px;
}

/* 查看原文弹窗 */
.original-dialog :deep(.el-dialog__body) {
  padding: 0;
  display: flex;
  flex-direction: column;
  height: 60vh;
  overflow: hidden;
}

.search-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.search-bar :deep(.el-input) {
  flex: 1;
}

.search-nav {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-shrink: 0;
}

.search-count {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
  min-width: 3em;
  text-align: center;
}

.original-dialog-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4) var(--space-6);
}

/* 搜索高亮 */
:deep(.search-highlight) {
  background: rgba(255, 213, 79, 0.6);
  color: inherit;
  padding: 1px 0;
  border-radius: 2px;
}

:deep(.search-highlight-current) {
  background: rgba(255, 171, 0, 0.85);
  color: inherit;
  padding: 1px 0;
  border-radius: 2px;
}

.image-preview-dialog :deep(.el-dialog__body) {
  padding: 0;
}
</style>