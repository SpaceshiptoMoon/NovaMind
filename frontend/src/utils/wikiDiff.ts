/**
 * Wiki 版本对比工具 —— 按行 LCS diff。
 *
 * 输出统一的行片段序列：equal（两版相同）/ added（新版新增）/
 * removed（旧版删除），供前端渲染双栏或单栏 diff 视图。
 */

export interface DiffLine {
  type: 'equal' | 'added' | 'removed'
  text: string
  /** 旧版行号（removed/equal 有效，1-based） */
  oldLine?: number
  /** 新版行号（added/equal 有效，1-based） */
  newLine?: number
}

/**
 * 按行 LCS 计算两版本文本差异。
 * 行数过大时（>2000 行）退化为「整段替换」单片段，避免 O(n·m) 爆内存。
 */
export function diffLines(oldText: string, newText: string): DiffLine[] {
  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')

  if (oldLines.length > 2000 || newLines.length > 2000) {
    return [
      ...oldLines.map((text, i) => ({ type: 'removed' as const, text, oldLine: i + 1 })),
      ...newLines.map((text, i) => ({ type: 'added' as const, text, newLine: i + 1 })),
    ]
  }

  // LCS 动态规划表
  const n = oldLines.length
  const m = newLines.length
  const dp: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
  for (let i = n - 1; i >= 0; i--) {
    const dpRow = dp[i] as Uint32Array
    const dpNext = dp[i + 1] as Uint32Array
    const oldLine = oldLines[i] as string
    for (let j = m - 1; j >= 0; j--) {
      dpRow[j] =
        oldLine === newLines[j] ? (dpNext[j + 1] ?? 0) + 1 : Math.max(dpNext[j] ?? 0, dpRow[j + 1] ?? 0)
    }
  }

  // 回溯产出片段序列
  const result: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    const oldLine = oldLines[i] as string
    const newLine = newLines[j] as string
    if (oldLine === newLine) {
      result.push({ type: 'equal', text: oldLine, oldLine: i + 1, newLine: j + 1 })
      i++
      j++
    } else {
      const dpNextRow = dp[i + 1] as Uint32Array
      const dpRow = dp[i] as Uint32Array
      if ((dpNextRow[j] ?? 0) >= (dpRow[j + 1] ?? 0)) {
        result.push({ type: 'removed', text: oldLine, oldLine: i + 1 })
        i++
      } else {
        result.push({ type: 'added', text: newLine, newLine: j + 1 })
        j++
      }
    }
  }
  while (i < n) {
    result.push({ type: 'removed', text: oldLines[i] as string, oldLine: i + 1 })
    i++
  }
  while (j < m) {
    result.push({ type: 'added', text: newLines[j] as string, newLine: j + 1 })
    j++
  }
  return result
}

/** 统计差异行数（用于 diff 摘要徽标） */
export function diffStats(lines: DiffLine[]): { added: number; removed: number } {
  let added = 0
  let removed = 0
  for (const line of lines) {
    if (line.type === 'added') added++
    else if (line.type === 'removed') removed++
  }
  return { added, removed }
}
