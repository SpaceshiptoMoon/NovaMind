/**
 * 文档相关共享工具函数和常量
 *
 * 供 DocumentView、DocumentDetailView 等组件复用
 */
import type { SpaceConfig } from '@/api/types'
import { MODALITY_ACCEPT_MAP, MODALITY_MAX_SIZE_MB } from '@/api/types'

/** 文档状态映射（兼容字符串名称和数字编码） */
export const docStatusMap: Record<string, { text: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
  uploaded: { text: '待处理', type: 'info' },
  processing: { text: '处理中', type: 'warning' },
  completed: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  '0': { text: '待处理', type: 'info' },
  '1': { text: '处理中', type: 'warning' },
  '2': { text: '已完成', type: 'success' },
  '3': { text: '失败', type: 'danger' },
}

/** 文件类型样式映射（使用 CSS 自定义属性，支持主题切换） */
export const fileTypeStyles: Record<string, { bg: string; color: string }> = {
  // 文档
  pdf: { bg: 'var(--color-file-pdf-bg)', color: 'var(--color-file-pdf)' },
  docx: { bg: 'var(--color-file-doc-bg)', color: 'var(--color-file-doc)' },
  doc: { bg: 'var(--color-file-doc-bg)', color: 'var(--color-file-doc)' },
  txt: { bg: 'var(--color-file-txt-bg)', color: 'var(--color-file-txt)' },
  md: { bg: 'var(--color-file-md-bg)', color: 'var(--color-file-md)' },
  xlsx: { bg: 'var(--color-file-xlsx-bg)', color: 'var(--color-file-xlsx)' },
  xls: { bg: 'var(--color-file-xlsx-bg)', color: 'var(--color-file-xlsx)' },
  csv: { bg: 'var(--color-file-xlsx-bg)', color: 'var(--color-file-xlsx)' },
  pptx: { bg: 'var(--color-file-pptx-bg)', color: 'var(--color-file-pptx)' },
  ppt: { bg: 'var(--color-file-pptx-bg)', color: 'var(--color-file-pptx)' },
  html: { bg: 'var(--color-file-other-bg)', color: 'var(--color-file-other)' },
  json: { bg: 'var(--color-file-other-bg)', color: 'var(--color-file-other)' },
  // 图片
  jpg: { bg: '#fef3c7', color: '#d97706' },
  jpeg: { bg: '#fef3c7', color: '#d97706' },
  png: { bg: '#fef3c7', color: '#d97706' },
  gif: { bg: '#fef3c7', color: '#d97706' },
  webp: { bg: '#fef3c7', color: '#d97706' },
  // 视频
  mp4: { bg: '#dbeafe', color: '#2563eb' },
  mov: { bg: '#dbeafe', color: '#2563eb' },
  avi: { bg: '#dbeafe', color: '#2563eb' },
  mkv: { bg: '#dbeafe', color: '#2563eb' },
  webm: { bg: '#dbeafe', color: '#2563eb' },
  // 音频
  mp3: { bg: '#fce7f3', color: '#db2777' },
  wav: { bg: '#fce7f3', color: '#db2777' },
  flac: { bg: '#fce7f3', color: '#db2777' },
  aac: { bg: '#fce7f3', color: '#db2777' },
  ogg: { bg: '#fce7f3', color: '#db2777' },
  m4a: { bg: '#fce7f3', color: '#db2777' },
}

/** chunk_type → 展示标签映射 */
export const chunkTypeLabels: Record<string, string> = {
  text: '📄 文档',
  image: '🖼 图片',
  video: '🎬 视频',
  audio: '🎵 音频',
}

/** 根据文件扩展名获取对应的样式 */
export function getFileTypeStyle(filename: string): { bg: string; color: string } {
  const ext = filename?.split('.').pop()?.toLowerCase() || ''
  return fileTypeStyles[ext] || { bg: 'var(--color-file-txt-bg)', color: 'var(--color-file-txt)' }
}

// ========== 全模态工具函数 ==========

/** 从 space_type 数组合并 accept 字符串 */
export function getUploadAccept(spaceTypes: string[]): string {
  const exts = new Set<string>()
  for (const t of spaceTypes) {
    const accept = MODALITY_ACCEPT_MAP[t]
    if (accept) accept.split(',').forEach(e => exts.add(e))
  }
  return [...exts].join(',')
}

/** 按文件扩展名获取该模态的最大文件大小 (MB) */
export function getFileMaxSize(ext: string): number {
  for (const [modality, accept] of Object.entries(MODALITY_ACCEPT_MAP)) {
    const exts = accept.split(',').map(e => e.replace('.', '').trim())
    if (exts.includes(ext.toLowerCase())) return MODALITY_MAX_SIZE_MB[modality] || 100
  }
  return 100
}

/** 判断 space_type 数组是否包含指定模态 */
export function hasModality(spaceTypes: string[] | undefined | null, modality: string): boolean {
  return Array.isArray(spaceTypes) && spaceTypes.includes(modality)
}

/** 从 space_type 数组获取最大文件大小提示文本 */
export function getMaxFileSizeText(spaceTypes: string[]): string {
  let max = 0
  for (const t of spaceTypes) max = Math.max(max, MODALITY_MAX_SIZE_MB[t] || 100)
  return `${max}MB`
}

/** 归一化旧格式 space_type（兼容 "text"/"multimodal" 字符串 → 数组） */
export function normalizeSpaceTypes(config: SpaceConfig | null | undefined): string[] {
  const raw = config?.space_type
  if (!raw) return ['text']
  if (Array.isArray(raw)) return raw
  // 兼容旧字符串格式
  if (raw === 'multimodal') return ['image']
  if (raw === 'text') return ['text']
  return ['text']
}
