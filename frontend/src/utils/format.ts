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

/** 格式化音频/视频时长 (秒 → M:SS) */
export function formatDuration(seconds: number | undefined | null): string {
  if (seconds == null) return '--:--'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

/** 相对时间（刚刚/N分钟前/N小时前/N天前/超一个月落日期）——通知列表等场景 */
export function formatRelativeTime(dateStr: string): string {
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}天前`
  return d.toLocaleDateString()
}
