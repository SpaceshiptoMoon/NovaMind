/**
 * 文档相关共享工具函数和常量
 *
 * 供 DocumentView、DocumentDetailView 等组件复用
 */

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
}

/** 根据文件扩展名获取对应的样式 */
export function getFileTypeStyle(filename: string): { bg: string; color: string } {
  const ext = filename?.split('.').pop()?.toLowerCase() || ''
  return fileTypeStyles[ext] || { bg: 'var(--color-file-txt-bg)', color: 'var(--color-file-txt)' }
}
