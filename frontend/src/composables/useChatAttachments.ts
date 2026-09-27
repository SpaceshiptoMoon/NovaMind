/**
 * 聊天附件/图片工具 composable
 *
 * 封装图片 blob 缓存、文件类型判断、URL 预览、格式化等函数。
 * 提取自 ChatView.vue，保持与原逻辑完全一致。
 */
const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'gif', 'webp'])

/** 聊天附件处理的组合式入口，返回一组附件/图片工具函数（模块级缓存全局共享） */
export function useChatAttachments() {
  const imageBlobCache = new Map<number, string>()

  /** 按文件类型（扩展名小写）判断是否图片附件 */
  function isImageFile(type?: string): boolean {
    return !!type && IMAGE_EXTENSIONS.has(type.toLowerCase())
  }

  /** 拉取附件原图并缓存为 Blob URL（带认证头；已缓存或失败时静默跳过） */
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

  /** 附件预览地址：优先后端 preview_url，否则取本地缓存 Blob URL，都无则空串 */
  function getImagePreviewUrl(att: { id?: number; preview_url?: string }): string {
    if (att.preview_url) return att.preview_url
    if (att.id) return imageBlobCache.get(att.id) || ''
    return ''
  }

  /** 取文件扩展名大写徽标文案，无扩展名时显示 FILE */
  function getFileExt(filename?: string): string {
    if (!filename) return 'FILE'
    const ext = filename.split('.').pop()?.toUpperCase() || 'FILE'
    return ext
  }

  /** 触发附件下载（动态引入 chatApi，走统一的认证下载通道） */
  async function handleDownloadAttachment(att: { id?: number; filename: string }) {
    if (!att.id) return
    try {
      const { chatApi } = await import('@/api/chat')
      await chatApi.downloadAttachmentFile(att.id, att.filename)
    } catch {
      // API 层已处理错误
    }
  }

  /** 字节数格式化为人类可读大小（B/KB/MB，一位小数） */
  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  /** 释放全部缓存图片 Blob URL，防内存泄漏（组件卸载时调用） */
  function revokeBlobUrls() {
    imageBlobCache.forEach((url) => URL.revokeObjectURL(url))
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
