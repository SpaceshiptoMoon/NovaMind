/**
 * wikiDiff 单元测试
 */
import { describe, expect, it } from 'vitest'
import { diffLines, diffStats } from '../wikiDiff'

describe('diffLines', () => {
  it('相同文本产出全 equal', () => {
    const lines = diffLines('a\nb\nc', 'a\nb\nc')
    expect(lines.every((l) => l.type === 'equal')).toBe(true)
    expect(lines).toHaveLength(3)
  })

  it('识别新增行', () => {
    const lines = diffLines('a\nc', 'a\nb\nc')
    expect(lines.filter((l) => l.type === 'added')).toEqual([
      { type: 'added', text: 'b', newLine: 2 },
    ])
    expect(diffStats(lines).added).toBe(1)
    expect(diffStats(lines).removed).toBe(0)
  })

  it('识别删除行', () => {
    const lines = diffLines('a\nb\nc', 'a\nc')
    expect(lines.filter((l) => l.type === 'removed')).toEqual([
      { type: 'removed', text: 'b', oldLine: 2 },
    ])
  })

  it('混合增删', () => {
    const lines = diffLines('x\nold\ny', 'x\nnew\ny')
    const stats = diffStats(lines)
    expect(stats.added).toBe(1)
    expect(stats.removed).toBe(1)
  })

  it('空文本处理（空串按一行空行）', () => {
    // ''.split('\n') === ['']，即空串 = 一行空行
    expect(diffLines('', 'a')).toEqual([
      { type: 'removed', text: '', oldLine: 1 },
      { type: 'added', text: 'a', newLine: 1 },
    ])
  })
})
