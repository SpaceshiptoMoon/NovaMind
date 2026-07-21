/**
 * Knowledge-base document helpers shared by document-related views.
 */
import type { SpaceConfig } from '@/api/types'
import { MODALITY_ACCEPT_MAP, MODALITY_MAX_SIZE_MB } from '@/api/types'

export const taskStatusMap: Record<number, { text: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
  0: { text: '待处理', type: 'info' },
  1: { text: '处理中', type: 'warning' },
  2: { text: '已完成', type: 'success' },
  3: { text: '失败', type: 'danger' },
  4: { text: '已取消', type: 'info' },
}

export const docStatusMap: Record<string, { text: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
  pending: { text: '待处理', type: 'info' },
  processing: { text: '处理中', type: 'warning' },
  completed: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  cancelled: { text: '已取消', type: 'info' },
  '0': { text: '待处理', type: 'info' },
  '1': { text: '处理中', type: 'warning' },
  '2': { text: '已完成', type: 'success' },
  '3': { text: '失败', type: 'danger' },
  '4': { text: '已取消', type: 'info' },
}

export const fileTypeStyles: Record<string, { bg: string; color: string }> = {
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
  jpg: { bg: '#fef3c7', color: '#d97706' },
  jpeg: { bg: '#fef3c7', color: '#d97706' },
  png: { bg: '#fef3c7', color: '#d97706' },
  gif: { bg: '#fef3c7', color: '#d97706' },
  webp: { bg: '#fef3c7', color: '#d97706' },
  mp4: { bg: '#dbeafe', color: '#2563eb' },
  mov: { bg: '#dbeafe', color: '#2563eb' },
  avi: { bg: '#dbeafe', color: '#2563eb' },
  mkv: { bg: '#dbeafe', color: '#2563eb' },
  webm: { bg: '#dbeafe', color: '#2563eb' },
  mp3: { bg: '#fce7f3', color: '#db2777' },
  wav: { bg: '#fce7f3', color: '#db2777' },
  flac: { bg: '#fce7f3', color: '#db2777' },
  aac: { bg: '#fce7f3', color: '#db2777' },
  ogg: { bg: '#fce7f3', color: '#db2777' },
  m4a: { bg: '#fce7f3', color: '#db2777' },
}

export const chunkTypeLabels: Record<string, string> = {
  text: '文本',
  image: '图片',
  video: '视频',
  audio: '音频',
}

export function getFileTypeStyle(filename: string): { bg: string; color: string } {
  const ext = filename?.split('.').pop()?.toLowerCase() || ''
  return fileTypeStyles[ext] || { bg: 'var(--color-file-txt-bg)', color: 'var(--color-file-txt)' }
}

export function getUploadAccept(spaceTypes: string[]): string {
  const exts = new Set<string>()
  for (const t of spaceTypes) {
    const accept = MODALITY_ACCEPT_MAP[t]
    if (accept) accept.split(',').forEach(e => exts.add(e))
  }
  return [...exts].join(',')
}

export function getFileMaxSize(ext: string): number {
  for (const [modality, accept] of Object.entries(MODALITY_ACCEPT_MAP)) {
    const exts = accept.split(',').map(e => e.replace('.', '').trim())
    if (exts.includes(ext.toLowerCase())) return MODALITY_MAX_SIZE_MB[modality] || 100
  }
  return 100
}

export function hasModality(spaceTypes: string[] | undefined | null, modality: string): boolean {
  return Array.isArray(spaceTypes) && spaceTypes.includes(modality)
}

export function normalizeSpaceTypes(config: SpaceConfig | null | undefined): string[] {
  const raw = config?.space_type
  if (!raw) return ['text']
  if (Array.isArray(raw)) return raw
  if (raw === 'text') return ['text']
  return ['text']
}

/** 根据文件扩展名返回文件类型分类 */
export function getFileTypeCategory(fileType: string): 'text' | 'image' | 'video' | 'audio' {
  const imageTypes = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']
  const videoTypes = ['mp4', 'mov', 'avi', 'mkv', 'webm']
  const audioTypes = ['mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a']
  const ext = fileType?.toLowerCase() || ''
  if (imageTypes.includes(ext)) return 'image'
  if (videoTypes.includes(ext)) return 'video'
  if (audioTypes.includes(ext)) return 'audio'
  return 'text'
}
