<template>
  <div class="message-row user">
    <div class="message-body">
      <div class="message-text">{{ msg.content }}</div>
      <div v-if="attachments.length" class="message-attachments">
        <template v-for="att in attachments" :key="att.filename">
          <div v-if="isImageFile(att.file_type) && att.id" class="image-card" @click="download(att)">
            <img v-if="getImagePreviewUrl(att)" :src="getImagePreviewUrl(att)" class="image-thumb" loading="lazy" />
            <div v-else class="image-thumb image-thumb-loading">加载中...</div>
            <div class="image-info">
              <span class="image-name">{{ att.filename }}</span>
              <span class="image-size">{{ formatFileSize(att.file_size ?? 0) }}</span>
            </div>
          </div>
          <div v-else class="file-card" @click="download(att)">
            <div class="file-icon-box" :class="getFileIconClass(att.file_type)">
              <span class="file-ext-label">{{ getFileExt(att.filename) }}</span>
            </div>
            <div class="file-info">
              <div class="file-name">{{ att.filename }}</div>
              <div class="file-meta">
                {{ getFileExt(att.filename) }} ·
                {{ formatFileSize(att.file_size ?? 0) }}
              </div>
            </div>
            <div class="file-download-btn" title="下载">
              <el-icon :size="16"><Download /></el-icon>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 用户消息行：右侧气泡 + 附件卡（图片缩略 / 文件卡，点击下载）。
 *
 * 图片预览走带 token 的 fetch 拉 Blob URL（img 标签带不上鉴权头），
 * 缓存为模块级 Map 跨实例共享；下载直接调 API（纯动作，无需上抛）。
 */
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { agentApi } from '@/api/agent'
import type { AgentMessage } from '@/api/types'
import {
  formatFileSize,
  getFileExt,
  getFileIconClass,
  getMessageAttachments,
  isImageFile,
  type MessageAttachment,
} from '@/utils/chatRender'
import { getImagePreviewUrl, loadAttachmentImage } from '@/utils/attachmentPreview'

const props = defineProps<{ msg: AgentMessage }>()

const attachments = computed<MessageAttachment[]>(() => getMessageAttachments(props.msg))

// 历史消息里的图片附件没有 WS 时机，挂载即拉取 Blob URL
for (const att of attachments.value) {
  if (isImageFile(att.file_type) && att.id) void loadAttachmentImage(att.id)
}

async function download(att: MessageAttachment) {
  if (!att.id) return
  try {
    await agentApi.downloadAttachmentFile(att.id, att.filename)
  } catch {
    ElMessage.error('下载失败')
  }
}
</script>

<style scoped>
.message-row.user {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 28px;
  animation: message-in 0.35s ease forwards;
}

@keyframes message-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message-body {
  max-width: 75%;
  min-width: 0;
}

.message-text {
  font-size: var(--text-base);
  line-height: var(--leading-relaxed);
  word-break: break-word;
}

.message-row.user .message-text {
  padding: var(--space-3) var(--space-4);
  border-radius: 18px 18px 4px 18px;
  background: var(--color-user-bubble);
  color: var(--color-user-bubble-text);
  white-space: pre-wrap;
}

/* 附件卡（图片缩略 / 文件卡） */
.message-attachments {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.file-card {
  display: flex;
  align-items: center;
  width: 260px;
  padding: var(--space-3);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  box-sizing: border-box;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.file-card:hover {
  background: var(--color-bg-hover);
}

.file-card .file-icon-box {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: var(--space-3);
  flex-shrink: 0;
}

.file-icon-box .file-ext-label {
  font-size: 11px;
  font-weight: var(--weight-bold);
  color: #fff;
  letter-spacing: 0.3px;
}

.file-icon-box.file-pdf {
  background: var(--color-file-pdf);
}
.file-icon-box.file-doc {
  background: var(--color-file-doc);
}
.file-icon-box.file-txt {
  background: var(--color-file-txt);
}
.file-icon-box.file-md {
  background: var(--color-file-md);
}
.file-icon-box.file-default {
  background: var(--color-file-other);
}
.file-icon-box.file-image {
  background: var(--color-file-image-bg);
  color: var(--color-file-image);
}

.file-card .file-info {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.file-card .file-name {
  font-size: var(--text-sm);
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-card .file-meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-top: var(--space-1);
}

.file-card .file-download-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  color: var(--color-text-muted);
  flex-shrink: 0;
  margin-left: var(--space-1);
  transition: all var(--transition-fast);
}

.file-card:hover .file-download-btn {
  color: var(--color-text);
  background: var(--color-bg-hover);
}

/* 图片卡 */
.image-card {
  display: inline-flex;
  flex-direction: column;
  cursor: pointer;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--color-border-light);
  max-width: 200px;
  transition: border-color 0.15s;
}
.image-card:hover {
  border-color: var(--color-primary);
}
.image-thumb {
  width: 100%;
  max-height: 150px;
  object-fit: cover;
  display: block;
}
.image-thumb-loading {
  height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-hover);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}
.image-info {
  padding: 4px 8px;
  display: flex;
  gap: 6px;
  align-items: center;
  background: var(--color-bg-card);
}
.image-name {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.image-size {
  font-size: 10px;
  color: var(--color-text-muted);
  flex-shrink: 0;
}
</style>
