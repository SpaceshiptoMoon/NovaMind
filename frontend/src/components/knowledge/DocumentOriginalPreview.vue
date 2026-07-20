<template>
  <div class="original-preview">
    <!-- 文本类文档：显示下载按钮和文件信息 -->
    <template v-if="category === 'text'">
      <div class="preview-section">
        <div class="preview-icon">
          <el-icon :size="48"><Document /></el-icon>
        </div>
        <div class="preview-info">
          <p class="preview-filename">{{ document?.filename }}</p>
          <p class="preview-meta">{{ formatFileSize(document?.file_size || 0) }} · {{ (document?.file_type || 'FILE').toUpperCase() }}</p>
        </div>
        <el-button type="primary" @click="handleDownload">
          <el-icon><Download /></el-icon>
          下载原文件
        </el-button>
      </div>
    </template>

    <!-- 图片类文档：显示原图 -->
    <template v-else-if="category === 'image'">
      <div class="preview-section image-preview">
        <img
          :src="previewUrl"
          :alt="document?.filename"
          class="preview-image"
          loading="lazy"
          @click="imagePreviewVisible = true"
        />
        <el-button type="primary" size="small" plain @click="handleDownload" class="image-download">
          <el-icon><Download /></el-icon>
          下载原图
        </el-button>
      </div>
      <el-dialog
        v-model="imagePreviewVisible"
        :show-close="true"
        width="auto"
        class="image-preview-dialog"
        destroy-on-close
      >
        <img :src="previewUrl" style="max-width: 90vw; max-height: 80vh; object-fit: contain; display: block; margin: auto" />
      </el-dialog>
    </template>

    <!-- 视频类文档：显示提取帧缩略图网格 -->
    <template v-else-if="category === 'video'">
      <div class="preview-section">
        <div class="preview-section-header">
          <h4>视频帧</h4>
          <span v-if="frames.length" class="frame-count">{{ frames.length }} 帧</span>
        </div>
        <div v-if="framesLoading" class="frames-loading">
          <el-skeleton :rows="3" animated />
        </div>
        <div v-else-if="frames.length" class="frames-grid">
          <div
            v-for="frame in frames"
            :key="frame.index"
            class="frame-thumb"
            @click="selectedFrameUrl = frame.url; framePreviewVisible = true"
          >
            <img :src="frame.url" :alt="`帧 ${frame.index + 1}`" loading="lazy" />
            <span class="frame-index">#{{ frame.index + 1 }}</span>
          </div>
        </div>
        <el-empty v-else description="暂无视频帧数据" :image-size="60" />
        <el-button type="primary" size="small" plain @click="handleDownload" style="margin-top: 12px">
          <el-icon><Download /></el-icon>
          下载原视频
        </el-button>
      </div>
      <el-dialog
        v-model="framePreviewVisible"
        :show-close="true"
        width="auto"
        class="image-preview-dialog"
        destroy-on-close
      >
        <img :src="selectedFrameUrl" style="max-width: 90vw; max-height: 80vh; object-fit: contain; display: block; margin: auto" />
      </el-dialog>
    </template>

    <!-- 音频类文档：显示播放器 -->
    <template v-else-if="category === 'audio'">
      <div class="preview-section audio-preview">
        <div class="audio-icon">
          <el-icon :size="48"><Headset /></el-icon>
        </div>
        <p class="preview-filename">{{ document?.filename }}</p>
        <audio :src="previewUrl" controls class="audio-player" preload="metadata">
          您的浏览器不支持音频播放
        </audio>
        <el-button type="primary" size="small" plain @click="handleDownload" style="margin-top: 12px">
          <el-icon><Download /></el-icon>
          下载音频
        </el-button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Document, Download, Headset } from '@element-plus/icons-vue'
import { documentApi } from '@/api/knowledge'
import { getFileTypeCategory } from './document'
import { formatFileSize } from '@/utils/format'
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

const previewUrl = computed(() => {
  if (!props.document) return ''
  return documentApi.getDocumentPreviewUrl(props.spaceId, props.kbId, props.document.id)
})

// 图片预览
const imagePreviewVisible = ref(false)

// 视频帧
const frames = ref<Array<{ index: number; url: string }>>([])
const framesLoading = ref(false)
const framePreviewVisible = ref(false)
const selectedFrameUrl = ref('')

onMounted(async () => {
  if (category.value === 'video' && props.document) {
    framesLoading.value = true
    try {
      const res = await documentApi.getDocumentFrames(props.spaceId, props.kbId, props.document.id)
      frames.value = res.frames || []
    } catch {
      frames.value = []
    } finally {
      framesLoading.value = false
    }
  }
})

async function handleDownload() {
  if (!props.document) return
  try {
    await documentApi.downloadDocument(props.spaceId, props.kbId, props.document.id, props.document.filename)
  } catch {
    // 下载失败已在 interceptor 处理
  }
}
</script>

<style scoped>
.original-preview {
  display: flex;
  flex-direction: column;
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

.frame-count {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.preview-icon,
.audio-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  border-radius: var(--radius-lg);
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}

.preview-info {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.preview-filename {
  margin: 0;
  font-size: var(--text-base);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  word-break: break-all;
}

.preview-meta {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.image-preview {
  align-items: center;
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

.image-download {
  align-self: flex-start;
}

.frames-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: var(--space-2);
  max-height: 400px;
  overflow-y: auto;
}

.frame-thumb {
  position: relative;
  aspect-ratio: 16 / 9;
  border-radius: var(--radius-sm);
  overflow: hidden;
  cursor: pointer;
  border: 2px solid transparent;
  transition: border-color var(--transition-fast);
}

.frame-thumb:hover {
  border-color: var(--color-primary);
}

.frame-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.frame-index {
  position: absolute;
  bottom: 2px;
  right: 4px;
  font-size: 10px;
  color: #fff;
  background: rgba(0, 0, 0, 0.6);
  padding: 1px 4px;
  border-radius: var(--radius-sm);
}

.frames-loading {
  padding: var(--space-3);
}

.audio-preview {
  align-items: center;
}

.audio-player {
  width: 100%;
  max-width: 320px;
}

.image-preview-dialog :deep(.el-dialog__body) {
  padding: 0;
}
</style>