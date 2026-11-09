/**
 * 附件图片预览的共享实现：带 token 的 fetch 拉 Blob URL（img 标签带不上鉴权头）。
 * 缓存为模块级 Map 跨组件共享（消息流内同一附件多处置卡只拉一次）。
 */
const imageBlobCache = new Map<number, string>()
const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

/** 拉取附件图片为 Blob URL 缓存用于预览；失败静默（预览缺席不阻断主流程） */
export async function loadAttachmentImage(attId: number): Promise<void> {
  if (imageBlobCache.has(attId)) return
  try {
    const token = localStorage.getItem('access_token')
    const res = await fetch(`${baseURL}/agent/attachments/${attId}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) return
    const blob = await res.blob()
    imageBlobCache.set(attId, URL.createObjectURL(blob))
  } catch {
    // ignore
  }
}

/** 预览 URL：优先后端预签名 preview_url，否则模块缓存中的 Blob URL */
export function getImagePreviewUrl(att: { id?: number; preview_url?: string }): string {
  if (att.preview_url) return att.preview_url
  if (att.id) return imageBlobCache.get(att.id) || ''
  return ''
}

/** 页面卸载时释放全部 Blob URL（多组件共用一个模块缓存，重复 revoke 是无害 no-op） */
export function revokeAllAttachmentImages(): void {
  for (const url of imageBlobCache.values()) {
    URL.revokeObjectURL(url)
  }
  imageBlobCache.clear()
}
