/**
 * 客户端 CSV 导出：运营页「导出」按钮用。
 *
 * 带 UTF-8 BOM（Excel 中文不乱码）；值内引号/逗号/换行按 RFC 4180 转义。
 * 纯浏览器端生成，不经后端——数据量以页面已在手的数据为上限。
 */

/** CSV 单列定义：字段键 + 表头文案 */
export interface CsvColumn<T> {
  key: keyof T & string
  label: string
}

function escapeCell(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value)
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`
  }
  return text
}

/**
 * 把行数组导出为 CSV 文件并触发浏览器下载。
 *
 * @param filename 文件名（不含扩展名，自动补 .csv）
 * @param columns 列定义（顺序即列序）
 * @param rows 行数据
 */
export function exportCsv<T extends Record<string, unknown>>(
  filename: string,
  columns: Array<CsvColumn<T>>,
  rows: T[],
): void {
  const header = columns.map((c) => escapeCell(c.label)).join(',')
  const body = rows.map((row) => columns.map((c) => escapeCell(row[c.key])).join(','))
  const content = `\uFEFF${[header, ...body].join('\r\n')}`
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename.endsWith('.csv') ? filename : `${filename}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}
