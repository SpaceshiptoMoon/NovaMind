/**
 * Knowledge-base document helpers shared by document-related views.
 */
import type { SpaceConfig } from '@/api/types'
import { MODALITY_ACCEPT_MAP, MODALITY_MAX_SIZE_MB } from '@/api/types'

/** 任务状态码 → 展示文案与 el-tag 类型（数字键为后端原始枚举） */
export const taskStatusMap: Record<
  number,
  { text: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }
> = {
  0: { text: '待处理', type: 'info' },
  1: { text: '处理中', type: 'warning' },
  2: { text: '已完成', type: 'success' },
  3: { text: '失败', type: 'danger' },
  4: { text: '已取消', type: 'info' },
}

/** 文档状态字符串 → 展示文案与 el-tag 类型（兼容历史数字字符串键） */
export const docStatusMap: Record<
  string,
  { text: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }
> = {
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

/** 文件扩展名 → 文件图标底色/前景色 CSS 变量映射 */
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
  jpg: { bg: 'var(--color-file-image-bg)', color: 'var(--color-file-image)' },
  jpeg: { bg: 'var(--color-file-image-bg)', color: 'var(--color-file-image)' },
  png: { bg: 'var(--color-file-image-bg)', color: 'var(--color-file-image)' },
  gif: { bg: 'var(--color-file-image-bg)', color: 'var(--color-file-image)' },
  webp: { bg: 'var(--color-file-image-bg)', color: 'var(--color-file-image)' },
  mp4: { bg: 'var(--color-file-video-bg)', color: 'var(--color-file-video)' },
  mov: { bg: 'var(--color-file-video-bg)', color: 'var(--color-file-video)' },
  avi: { bg: 'var(--color-file-video-bg)', color: 'var(--color-file-video)' },
  mkv: { bg: 'var(--color-file-video-bg)', color: 'var(--color-file-video)' },
  webm: { bg: 'var(--color-file-video-bg)', color: 'var(--color-file-video)' },
  mp3: { bg: 'var(--color-file-audio-bg)', color: 'var(--color-file-audio)' },
  wav: { bg: 'var(--color-file-audio-bg)', color: 'var(--color-file-audio)' },
  flac: { bg: 'var(--color-file-audio-bg)', color: 'var(--color-file-audio)' },
  aac: { bg: 'var(--color-file-audio-bg)', color: 'var(--color-file-audio)' },
  ogg: { bg: 'var(--color-file-audio-bg)', color: 'var(--color-file-audio)' },
  m4a: { bg: 'var(--color-file-audio-bg)', color: 'var(--color-file-audio)' },
}

/** 分块类型标识 → 中文展示标签 */
export const chunkTypeLabels: Record<string, string> = {
  text: '文本',
  image: '图片',
  video: '视频',
  audio: '音频',
  // wiki 页 ES 同步（chunk_type="wiki_page"，wiki_es_sync.py）出现在检索结果中
  wiki_page: 'Wiki',
}

/** 按文件名取扩展名并查样式，未知类型回退到 txt 样式 */
export function getFileTypeStyle(filename: string): { bg: string; color: string } {
  const ext = filename?.split('.').pop()?.toLowerCase() || ''
  return fileTypeStyles[ext] || { bg: 'var(--color-file-txt-bg)', color: 'var(--color-file-txt)' }
}

/** 按空间启用的模态聚合出上传 accept 扩展名串（逗号分隔、去重） */
export function getUploadAccept(spaceTypes: string[]): string {
  const exts = new Set<string>()
  for (const t of spaceTypes) {
    const accept = MODALITY_ACCEPT_MAP[t]
    if (accept) accept.split(',').forEach((e) => exts.add(e))
  }
  return [...exts].join(',')
}

/** 按扩展名反查所属模态的上传大小上限（MB），未命中回退 100MB */
export function getFileMaxSize(ext: string): number {
  for (const [modality, accept] of Object.entries(MODALITY_ACCEPT_MAP)) {
    const exts = accept.split(',').map((e) => e.replace('.', '').trim())
    if (exts.includes(ext.toLowerCase())) return MODALITY_MAX_SIZE_MB[modality] || 100
  }
  return 100
}

/** 判断空间是否启用了某模态（容忍 undefined/null 入参） */
export function hasModality(spaceTypes: string[] | undefined | null, modality: string): boolean {
  return Array.isArray(spaceTypes) && spaceTypes.includes(modality)
}

/** 归一化后端 space_type 到模态数组；空/旧格式一律收敛为 ['text'] */
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
