/**
 * 通用格式化工具函数
 *
 * 供 DocumentView、DocumentDetailView、SearchView 等组件复用
 */

/** 格式化文件大小（B / KB / MB） */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** 格式化日期时间（中文本地化，带空值保护） */
export function formatDate(date?: string | null): string {
  if (!date) return '-'
  try {
    return new Date(date).toLocaleDateString('zh-CN') + ' ' +
      new Date(date).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return '-'
  }
}
