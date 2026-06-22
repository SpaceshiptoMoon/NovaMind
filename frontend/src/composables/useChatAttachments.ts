/**
 * 聊天附件/图片工具 composable
 *
 * 封装图片 blob 缓存、文件类型判断、URL 预览、格式化等函数。
 * 提取自 ChatView.vue，保持与原逻辑完全一致。
 */
const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'gif', 'webp'])

export function useChatAttachments() {
  const imageBlobCache = new Map<number, string>()

  function isImageFile(type?: string): boolean {
    return !!type && IMAGE_EXTENSIONS.has(type.toLowerCase())
  }

  async function loadAttachmentImage(attId: number) {
    if (imageBlobCache.has(attId)) return
    try {
      const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
      const token = localStorage.getItem('access_token')
      const res = await fetch(`${baseURL}/ai-chat/chat-attachments/${attId}/download`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) return
      const blob = await res.blob()
      imageBlobCache.set(attId, URL.createObjectURL(blob))
    } catch {
      // 静默失败，不阻塞交互
    }
  }

  function getImagePreviewUrl(att: { id?: number; preview_url?: string }): string {
    if (att.preview_url) return att.preview_url
    if (att.id) return imageBlobCache.get(att.id) || ''
    return ''
  }

  function getFileExt(filename?: string): string {
    if (!filename) return 'FILE'
    const ext = filename.split('.').pop()?.toUpperCase() || 'FILE'
    return ext
  }

  async function handleDownloadAttachment(att: { id?: number; filename: string }) {
    if (!att.id) return
    try {
      const { default: chatApi } = await import('@/api/chat')
      await chatApi.downloadAttachmentFile(att.id, att.filename)
    } catch {
      // API 层已处理错误
    }
  }

  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  function revokeBlobUrls() {
    imageBlobCache.forEach(url => URL.revokeObjectURL(url))
    imageBlobCache.clear()
  }

  return {
    imageBlobCache,
    isImageFile,
    loadAttachmentImage,
    getImagePreviewUrl,
    getFileExt,
    handleDownloadAttachment,
    formatFileSize,
    revokeBlobUrls,
  }
}
